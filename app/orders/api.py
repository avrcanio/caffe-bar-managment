import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q, Sum
from django.urls import reverse
from email.utils import formataddr, parseaddr
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from configuration.models import CompanyProfile, OrderEmailTemplate
from accounting.services import (
    compute_purchase_totals_from_items,
    flatten_input_items,
    post_purchase_invoice_close_receipt,
    post_warehouse_input_to_journal,
)
from .models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemPriceAudit,
    SupplierInvoice,
    WarehouseInput,
    WarehouseInputItem,
    SupplierPriceItem,
    SupplierPriceList,
)
from .pdf import build_order_pdf
from .push_tasks import notify_purchase_order_topic
from stock.models import WarehouseStock, WarehouseId
from stock.services import get_stock_accounting_config, post_warehouse_input_to_stock

logger = logging.getLogger(__name__)


def _serialize_packaging_numeric(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _build_packaging_levels_payload(artikl):
    total = Decimal("1")
    payloads = []
    for level in artikl.packaging_levels.order_by("sort_order", "id"):
        if level.sort_order == 0:
            current_total = Decimal("1")
        else:
            current_total = total * Decimal(str(level.contains_previous or 0))
        payloads.append(
            {
                "id": level.id,
                "sort_order": level.sort_order,
                "unit_of_measure": level.unit_of_measure_id,
                "unit_name": level.unit_of_measure.name,
                "level_name": level.level_name,
                "is_base": level.sort_order == 0,
                "base_quantity_total": _serialize_packaging_numeric(current_total),
                "contains_previous": level.contains_previous,
            }
        )
        total = current_total
    return payloads


def _build_packaging_breakdown(artikl, quantity):
    levels = _build_packaging_levels_payload(artikl)
    if not levels:
        return []

    remaining = Decimal(str(quantity or 0))
    breakdown = []
    for level in reversed(levels):
        level_total = Decimal(str(level["base_quantity_total"]))
        if level["is_base"]:
            level_quantity = remaining
        else:
            level_quantity = remaining // level_total
            remaining -= level_quantity * level_total
        breakdown.append(
            {
                "sort_order": level["sort_order"],
                "unit_of_measure": level["unit_of_measure"],
                "unit_name": level["unit_name"],
                "level_name": level["level_name"],
                "base_quantity_total": level["base_quantity_total"],
                "quantity": _serialize_packaging_numeric(level_quantity),
            }
        )
    return breakdown


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    artikl_name = serializers.CharField(source="artikl.name", read_only=True)
    base_group = serializers.SerializerMethodField()
    unit_name = serializers.CharField(
        source="unit_of_measure.name", read_only=True
    )
    order = serializers.PrimaryKeyRelatedField(read_only=True)
    received_quantity = serializers.SerializerMethodField()
    remaining_quantity = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderItem
        fields = [
            "id",
            "order",
            "artikl",
            "artikl_name",
            "base_group",
            "quantity",
            "unit_of_measure",
            "unit_name",
            "price",
            "received_quantity",
            "remaining_quantity",
        ]

    def get_base_group(self, obj):
        detail = getattr(obj.artikl, "detail", None)
        base_group = getattr(detail, "base_group", None)
        return getattr(base_group, "name", None)

    def get_received_quantity(self, obj):
        info = (self.context.get("remaining_by_item_id") or {}).get(obj.id)
        if not info:
            return None
        return info.get("received")

    def get_remaining_quantity(self, obj):
        info = (self.context.get("remaining_by_item_id") or {}).get(obj.id)
        if not info:
            return None
        return info.get("remaining")


class PurchaseOrderSerializer(serializers.ModelSerializer):
    ordered_at = serializers.DateTimeField(required=False)
    updated_at = serializers.DateTimeField(read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    payment_type_name = serializers.CharField(
        source="payment_type.name", read_only=True
    )
    created_by = serializers.CharField(source="created_by.username", read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    items = PurchaseOrderItemSerializer(many=True, required=False)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "supplier",
            "supplier_name",
            "ordered_at",
            "updated_at",
            "status",
            "status_display",
            "payment_type",
            "payment_type_name",
            "created_by",
            "primka_created",
            "total_net",
            "total_gross",
            "total_deposit",
            "items",
        ]

    def _resolve_default_payment_type(self, validated_data, instance=None):
        payment_type = validated_data.get("payment_type")
        if payment_type is not None:
            return payment_type

        supplier = validated_data.get("supplier")
        if supplier is None and instance is not None:
            supplier = instance.supplier
        if supplier is None:
            return None
        return supplier.default_payment_type

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        request = self.context.get("request")
        if request and request.user and not validated_data.get("created_by"):
            validated_data["created_by"] = request.user
        if not validated_data.get("ordered_at"):
            validated_data["ordered_at"] = timezone.now()
        validated_data["payment_type"] = self._resolve_default_payment_type(validated_data)
        order = PurchaseOrder.objects.create(**validated_data)
        for item_data in items_data:
            PurchaseOrderItem.objects.create(order=order, **item_data)
        order.recalculate_totals()
        return order

    @transaction.atomic
    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        validated_data["payment_type"] = self._resolve_default_payment_type(
            validated_data,
            instance=instance,
        )
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                PurchaseOrderItem.objects.create(order=instance, **item_data)
            instance.recalculate_totals()

        return instance


class PurchaseOrderPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class PurchaseOrderListCreateView(generics.ListCreateAPIView):
    queryset = (
        PurchaseOrder.objects.select_related("supplier", "payment_type", "created_by")
        .prefetch_related("items__artikl__detail__base_group")
        .order_by("-ordered_at", "-id")
    )
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PurchaseOrderPagination

    def get_queryset(self):
        qs = super().get_queryset()
        statuses = self._get_status_filters()
        supplier = self.request.query_params.get("supplier")
        ordered_from = self.request.query_params.get("ordered_from")
        ordered_to = self.request.query_params.get("ordered_to")

        if statuses:
            qs = qs.filter(status__in=statuses)
        if supplier:
            qs = qs.filter(supplier_id=supplier)

        if ordered_from:
            dt = parse_datetime(ordered_from)
            if dt:
                qs = qs.filter(ordered_at__gte=dt)
            else:
                d = parse_date(ordered_from)
                if d:
                    qs = qs.filter(ordered_at__date__gte=d)

        if ordered_to:
            dt = parse_datetime(ordered_to)
            if dt:
                qs = qs.filter(ordered_at__lte=dt)
            else:
                d = parse_date(ordered_to)
                if d:
                    qs = qs.filter(ordered_at__date__lte=d)

        return qs

    def _get_status_filters(self):
        raw_statuses = self.request.query_params.getlist("status")
        statuses = []
        for raw_status in raw_statuses:
            for candidate in raw_status.split(","):
                normalized = candidate.strip()
                if normalized and normalized not in statuses:
                    statuses.append(normalized)
        return statuses

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        summary = queryset.aggregate(
            total_net=Sum("total_net"),
            total_gross=Sum("total_gross"),
            total_deposit=Sum("total_deposit"),
        )
        status_counts = (
            queryset.values("status")
            .annotate(count=Count("id"), total_gross=Sum("total_gross"))
            .order_by()
        )
        response = super().list(request, *args, **kwargs)
        paginated_count = queryset.count()
        paginated_next = None
        paginated_previous = None
        paginated_results = response.data
        if isinstance(response.data, dict):
            paginated_count = response.data.get("count", paginated_count)
            paginated_next = response.data.get("next")
            paginated_previous = response.data.get("previous")
            paginated_results = response.data.get("results", response.data)
        response.data = {
            "count": paginated_count,
            "next": paginated_next,
            "previous": paginated_previous,
            "summary": {
                "count": queryset.count(),
                "total_net": summary["total_net"] or 0,
                "total_gross": summary["total_gross"] or 0,
                "total_deposit": summary["total_deposit"] or 0,
                "status_counts": {
                    item["status"]: {
                        "count": item["count"],
                        "total_gross": item["total_gross"] or 0,
                    }
                    for item in status_counts
                },
            },
            "results": paginated_results,
        }
        return response


def _serialize_purchase_order_detail(view_or_none, instance, request=None):
    po_items = list(instance.items.all().order_by("id"))
    received_by_artikl = _po_received_by_artikl(instance)
    remaining_by_item_id = _po_item_remaining_map(po_items, received_by_artikl)
    serializer_context = {
        "remaining_by_item_id": remaining_by_item_id,
    }
    if request is not None:
        serializer_context["request"] = request
    if view_or_none is not None:
        serializer_context["format"] = getattr(view_or_none, "format_kwarg", None)
        serializer_context["view"] = view_or_none
    serializer = PurchaseOrderSerializer(
        instance,
        context=serializer_context,
    )
    return serializer.data


class PurchaseOrderDetailView(generics.RetrieveUpdateAPIView):
    queryset = (
        PurchaseOrder.objects.select_related("supplier", "payment_type", "created_by")
        .prefetch_related("items__artikl__detail__base_group")
    )
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return Response(_serialize_purchase_order_detail(self, instance, request=request))


class PurchaseOrderItemListCreateView(generics.ListCreateAPIView):
    serializer_class = PurchaseOrderItemSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PurchaseOrderPagination

    def get_queryset(self):
        qs = PurchaseOrderItem.objects.filter(
            order_id=self.kwargs["order_id"]
        ).select_related("artikl", "unit_of_measure", "order")
        artikl = self.request.query_params.get("artikl")
        unit = self.request.query_params.get("unit")
        quantity_min = self.request.query_params.get("quantity_min")
        quantity_max = self.request.query_params.get("quantity_max")
        price_min = self.request.query_params.get("price_min")
        price_max = self.request.query_params.get("price_max")

        if artikl:
            qs = qs.filter(artikl_id=artikl)
        if unit:
            qs = qs.filter(unit_of_measure_id=unit)
        if quantity_min:
            qs = qs.filter(quantity__gte=quantity_min)
        if quantity_max:
            qs = qs.filter(quantity__lte=quantity_max)
        if price_min:
            qs = qs.filter(price__gte=price_min)
        if price_max:
            qs = qs.filter(price__lte=price_max)

        return qs

    def perform_create(self, serializer):
        serializer.save(order_id=self.kwargs["order_id"])


class PurchaseOrderItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = PurchaseOrderItem.objects.select_related(
        "artikl", "unit_of_measure", "order"
    )
    serializer_class = PurchaseOrderItemSerializer
    permission_classes = [IsAuthenticated]


class PurchaseOrderItemPriceUpdateSerializer(serializers.Serializer):
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.00"))
    currency = serializers.CharField(required=False, default="EUR")
    reason = serializers.CharField()

    def validate_currency(self, value):
        if (value or "").upper() != "EUR":
            raise serializers.ValidationError("Podržana valuta je samo EUR.")
        return "EUR"

    def validate_reason(self, value):
        reason = (value or "").strip()
        if not reason:
            raise serializers.ValidationError("Razlog promjene cijene je obavezan.")
        return reason


class PurchaseOrderItemPriceUpdateResponseSerializer(serializers.Serializer):
    purchase_order_item_id = serializers.IntegerField()
    old_price = serializers.CharField()
    new_price = serializers.CharField()
    audit = serializers.DictField()
    po_totals = serializers.DictField()


class PurchaseOrderStatusTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=(
            PurchaseOrder.STATUS_CONFIRMED,
            PurchaseOrder.STATUS_RECEIVED_ALL,
        )
    )


class PurchaseOrderItemPriceUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PurchaseOrderItemPriceUpdateSerializer,
        responses={200: PurchaseOrderItemPriceUpdateResponseSerializer},
    )
    @transaction.atomic
    def patch(self, request, pk):
        serializer = PurchaseOrderItemPriceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        item = (
            PurchaseOrderItem.objects.select_for_update()
            .select_related("order__supplier", "artikl", "unit_of_measure")
            .filter(pk=pk)
            .first()
        )
        if not item:
            return Response({"detail": "Stavka narudzbe ne postoji."}, status=404)

        old_price = Decimal(item.price or Decimal("0.00")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        new_price = Decimal(serializer.validated_data["price"]).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        if old_price == new_price:
            return Response(
                {"detail": "Nova cijena je ista kao postojeca."},
                status=400,
            )

        PurchaseOrderItem.objects.filter(pk=item.pk).update(price=new_price)
        item.price = new_price
        item.order.recalculate_totals()

        audit = PurchaseOrderItemPriceAudit.objects.create(
            purchase_order=item.order,
            purchase_order_item=item,
            artikl=item.artikl,
            supplier=item.order.supplier,
            old_price=old_price,
            new_price=new_price,
            changed_by=request.user if request.user.is_authenticated else None,
            reason=serializer.validated_data["reason"],
        )

        price_list = SupplierPriceList.objects.create(
            supplier=item.order.supplier,
            valid_from=timezone.localdate(),
            valid_to=None,
            is_active=True,
        )
        SupplierPriceItem.objects.update_or_create(
            price_list=price_list,
            artikl=item.artikl,
            defaults={
                "unit_of_measure": item.unit_of_measure,
                "price": new_price,
            },
        )

        item.order.refresh_from_db(fields=["total_net", "total_gross", "total_deposit"])
        user = request.user
        full_name = user.get_full_name().strip() if hasattr(user, "get_full_name") else ""
        return Response(
            {
                "purchase_order_item_id": item.id,
                "old_price": f"{old_price:.2f}",
                "new_price": f"{new_price:.2f}",
                "audit": {
                    "changed_at": audit.changed_at,
                    "changed_by": {
                        "id": user.id if user and user.is_authenticated else None,
                        "username": user.get_username() if user and user.is_authenticated else "",
                        "full_name": full_name or (user.get_username() if user and user.is_authenticated else ""),
                    },
                    "reason": audit.reason,
                },
                "po_totals": {
                    "total_net": f"{Decimal(item.order.total_net or 0):.2f}",
                    "total_gross": f"{Decimal(item.order.total_gross or 0):.2f}",
                    "total_deposit": f"{Decimal(item.order.total_deposit or 0):.2f}",
                },
            }
        )


def _q2(value: Decimal | int | float | str | None) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _po_received_by_artikl(order: PurchaseOrder) -> dict[int, Decimal]:
    rows = (
        WarehouseInputItem.objects.filter(warehouse_input__purchase_order_id=order.id)
        .values("artikl_id")
        .annotate(q=Sum("quantity"))
    )
    return {r["artikl_id"]: (r["q"] or Decimal("0")) for r in rows if r["artikl_id"]}


def _po_item_remaining_map(
    items: list[PurchaseOrderItem], received_by_artikl: dict[int, Decimal]
) -> dict[int, dict[str, Decimal]]:
    received_left = {k: Decimal(v) for k, v in received_by_artikl.items()}
    out: dict[int, dict[str, Decimal]] = {}
    for it in items:
        ordered = it.quantity or Decimal("0")
        a_id = it.artikl_id
        left = received_left.get(a_id, Decimal("0"))
        received_line = min(ordered, left) if ordered > 0 and left > 0 else Decimal("0")
        remaining = ordered - received_line
        if a_id:
            received_left[a_id] = max(left - received_line, Decimal("0"))
        out[it.id] = {
            "ordered": ordered,
            "received": received_line,
            "remaining": max(remaining, Decimal("0")),
        }
    return out


def _is_cash_payment_type(payment_type) -> bool:
    if not payment_type:
        return False
    name = (getattr(payment_type, "name", "") or "").strip().lower()
    return name == "gotovina" or getattr(payment_type, "id", None) == 3


def _next_duplicate_invoice_number(supplier_id: int, base_number: str) -> str:
    base = (base_number or "").strip()
    if not base:
        return "AUTO-1"
    ordinal = 1
    while True:
        candidate = f"{base} ({ordinal})"
        if not SupplierInvoice.objects.filter(
            supplier_id=supplier_id,
            invoice_number=candidate,
        ).exists():
            return candidate
        ordinal += 1


def _post_warehouse_input(warehouse_input: WarehouseInput, *, user) -> bool:
    changed = False
    if not warehouse_input.stock_move_id:
        post_warehouse_input_to_stock(warehouse_input=warehouse_input)
        warehouse_input.refresh_from_db(fields=["stock_move"])
        changed = True
    if not warehouse_input.journal_entry_id:
        post_warehouse_input_to_journal(
            warehouse_input=warehouse_input,
            user=user,
        )
        warehouse_input.refresh_from_db(fields=["journal_entry"])
        changed = True
    return changed


def _create_supplier_invoice_from_warehouse_input(
    warehouse_input: WarehouseInput,
) -> tuple[SupplierInvoice, bool]:
    linked = warehouse_input.supplier_invoices.order_by("id").first()
    if linked:
        return linked, False
    if not warehouse_input.stock_move_id or not warehouse_input.journal_entry_id:
        raise DjangoValidationError("Primka mora biti proknjižena prije kreiranja ulaznog računa.")

    invoice_code = (warehouse_input.invoice_code or "").strip()
    if not invoice_code:
        raise DjangoValidationError("Primka nema broj računa (invoice_code).")

    supplier_id = warehouse_input.supplier_id
    supplier = warehouse_input.supplier
    if not supplier_id or not supplier:
        raise DjangoValidationError("Primka nema dobavljača.")

    invoice_number = invoice_code
    if SupplierInvoice.objects.filter(
        supplier_id=supplier_id,
        invoice_number=invoice_number,
    ).exists():
        invoice_number = _next_duplicate_invoice_number(
            supplier_id,
            invoice_number,
        )

    items = list(warehouse_input.items.select_related("artikl__tax_group", "artikl__deposit"))
    if not items:
        raise DjangoValidationError("Primka nema stavki.")
    totals = compute_purchase_totals_from_items(items, deposit_total=None)

    force_cash = _is_cash_payment_type(warehouse_input.payment_type)
    payment_terms = (
        SupplierInvoice.PaymentTerms.CASH
        if force_cash
        else SupplierInvoice.PaymentTerms.DEFERRED
    )
    document_type_id = 3 if force_cash else warehouse_input.document_type_id

    cfg = None
    try:
        cfg = get_stock_accounting_config()
    except Exception:
        cfg = None

    invoice = SupplierInvoice.objects.create(
        supplier=supplier,
        invoice_number=invoice_number,
        invoice_date=warehouse_input.date or timezone.localdate(),
        payment_terms=payment_terms,
        paid_cash=force_cash,
        document_type_id=document_type_id,
        deposit_total=totals.deposit_total,
        total_net=totals.net_total,
        total_vat=totals.vat_total,
        total_gross=totals.gross_total,
    )
    update_fields: list[str] = []
    if cfg:
        if force_cash and not invoice.cash_account_id and cfg.default_cash_account_id:
            invoice.cash_account = cfg.default_cash_account
            update_fields.append("cash_account")
        if invoice.deposit_total > 0 and not invoice.deposit_account_id:
            if cfg.default_deposit_account_id:
                invoice.deposit_account = cfg.default_deposit_account
            else:
                invoice.deposit_account_id = 1318
            update_fields.append("deposit_account")
    if not force_cash and not invoice.ap_account_id and document_type_id:
        document_type = warehouse_input.document_type
        if document_type and document_type.ap_account_id:
            invoice.ap_account = document_type.ap_account
            update_fields.append("ap_account")
    if update_fields:
        invoice.save(update_fields=update_fields)

    invoice.inputs.add(warehouse_input)
    return invoice, True


def _post_supplier_invoice(invoice: SupplierInvoice, *, user) -> bool:
    if invoice.journal_entry_id:
        return False
    if not invoice.document_type_id:
        raise DjangoValidationError(f"Račun {invoice.id} nema document_type.")

    cfg = None
    try:
        cfg = get_stock_accounting_config()
    except Exception:
        cfg = None

    update_fields: list[str] = []
    if not invoice.ap_account_id and invoice.document_type and invoice.document_type.ap_account_id:
        invoice.ap_account = invoice.document_type.ap_account
        update_fields.append("ap_account")
    if invoice.payment_terms == invoice.PaymentTerms.CASH:
        if not invoice.cash_account_id and cfg and cfg.default_cash_account_id:
            invoice.cash_account = cfg.default_cash_account
            update_fields.append("cash_account")
    if invoice.deposit_total > 0 and not invoice.deposit_account_id and cfg and cfg.default_deposit_account_id:
        invoice.deposit_account = cfg.default_deposit_account
        update_fields.append("deposit_account")
    if update_fields:
        invoice.save(update_fields=update_fields)

    if invoice.payment_terms == invoice.PaymentTerms.CASH and not invoice.cash_account_id:
        raise DjangoValidationError(f"Račun {invoice.id} nema cash_account za gotovinu.")
    if invoice.payment_terms == invoice.PaymentTerms.DEFERRED and not invoice.ap_account_id:
        raise DjangoValidationError(f"Račun {invoice.id} nema ap_account za odgodu.")
    if invoice.deposit_total > 0 and not invoice.deposit_account_id:
        raise DjangoValidationError(f"Račun {invoice.id} ima depozit, ali nema deposit_account.")

    items = flatten_input_items(invoice.inputs.all())
    include_cash = invoice.payment_terms == invoice.PaymentTerms.CASH
    entry = post_purchase_invoice_close_receipt(
        document_type=invoice.document_type,
        doc_date=invoice.invoice_date,
        items=items,
        ap_account=invoice.ap_account,
        deposit_account=invoice.deposit_account,
        cash_account=invoice.cash_account,
        include_cash_payment=include_cash,
        description=f"Ulazni racun {invoice.invoice_number}",
        posted_by=user,
    )
    invoice.journal_entry = entry
    if include_cash:
        invoice.paid_cash = True
        invoice.paid_at = invoice.paid_at or timezone.localdate()
        invoice.payment_status = invoice.PaymentStatus.PAID
    else:
        invoice.payment_status = invoice.PaymentStatus.UNPAID
    invoice.save(update_fields=["journal_entry", "paid_cash", "paid_at", "payment_status"])
    return True


class PurchaseOrderWarehouseInputItemCreateSerializer(serializers.Serializer):
    purchase_order_item_id = serializers.IntegerField()
    received_quantity = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0"))
    confirmed = serializers.BooleanField(required=False, default=False)
    expected_unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))


class PurchaseOrderWarehouseInputCreateSerializer(serializers.Serializer):
    document_date = serializers.DateField(required=False)
    warehouse_id = serializers.IntegerField()
    invoice_code = serializers.CharField(required=False, allow_blank=True, default="")
    delivery_note = serializers.CharField(required=False, allow_blank=True, default="")
    currency = serializers.CharField(required=False, default="EUR")
    expected_total_net = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
    )
    items = PurchaseOrderWarehouseInputItemCreateSerializer(many=True)

    def validate_currency(self, value):
        if (value or "").upper() != "EUR":
            raise serializers.ValidationError("Podrzana valuta je samo EUR.")
        return "EUR"

    def validate(self, attrs):
        if not (attrs.get("invoice_code", "").strip() or attrs.get("delivery_note", "").strip()):
            raise serializers.ValidationError("Unesi broj racuna ili broj otpremnice.")
        items = attrs.get("items") or []
        if not items:
            raise serializers.ValidationError("Nedostaju stavke za primku.")
        confirmed_items = [row for row in items if bool(row.get("confirmed"))]
        if not confirmed_items:
            raise serializers.ValidationError("Potvrdi barem jednu stavku za zaprimanje.")
        if not any(Decimal(row.get("received_quantity") or 0) > 0 for row in confirmed_items):
            raise serializers.ValidationError(
                "Barem jedna potvrdena stavka mora imati kolicinu vecu od 0."
            )
        return attrs


class PurchaseOrderWarehouseInputCreateResponseSerializer(serializers.Serializer):
    warehouse_input = serializers.DictField()
    purchase_order = serializers.DictField()
    automation = serializers.DictField(required=False)


class PurchaseOrderWarehouseInputCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PurchaseOrderWarehouseInputCreateSerializer,
        responses={201: PurchaseOrderWarehouseInputCreateResponseSerializer},
    )
    @transaction.atomic
    def post(self, request, pk):
        serializer = PurchaseOrderWarehouseInputCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order = (
            PurchaseOrder.objects.select_for_update()
            .select_related("supplier")
            .prefetch_related("items__artikl__tax_group", "items__unit_of_measure")
            .filter(pk=pk)
            .first()
        )
        if not order:
            return Response({"detail": "Narudzba ne postoji."}, status=404)
        if order.status not in (
            PurchaseOrder.STATUS_CONFIRMED,
            PurchaseOrder.STATUS_RECEIVED,
        ):
            return Response(
                {
                    "detail": (
                        "Primka se moze kreirati samo za potvrdenu "
                        "ili djelomicno zaprimljenu narudzbu."
                    )
                },
                status=400,
            )

        warehouse = (
            WarehouseId.objects.filter(id=data["warehouse_id"]).first()
            or WarehouseId.objects.filter(rm_id=data["warehouse_id"]).first()
        )
        if not warehouse:
            return Response({"detail": "Skladiste nije pronadeno."}, status=400)

        po_items = list(order.items.all().order_by("id"))
        po_item_map = {it.id: it for it in po_items}
        request_items = data["items"]
        request_item_ids = [int(row["purchase_order_item_id"]) for row in request_items]
        if len(set(request_item_ids)) != len(request_item_ids):
            return Response({"detail": "Stavke se ne smiju ponavljati."}, status=400)
        po_item_ids = {it.id for it in po_items}
        if any(item_id not in po_item_ids for item_id in request_item_ids):
            return Response({"detail": "Neke stavke ne pripadaju ovoj narudzbi."}, status=400)

        received_by_artikl_before = _po_received_by_artikl(order)
        remaining_map_before = _po_item_remaining_map(po_items, received_by_artikl_before)

        lines: list[WarehouseInputItem] = []
        computed_total_net = Decimal("0.00")
        ordinal = 0
        for req in request_items:
            po_item = po_item_map[int(req["purchase_order_item_id"])]
            if not bool(req.get("confirmed")):
                continue
            expected_price = _q2(req["expected_unit_price"])
            actual_price = _q2(po_item.price)
            if actual_price != expected_price:
                return Response(
                    {
                        "detail": (
                            f"Cijena stavke {po_item.id} ne odgovara narudzbi "
                            f"({actual_price:.2f} != {expected_price:.2f})."
                        )
                    },
                    status=400,
                )

            qty = Decimal(req["received_quantity"] or 0)
            if qty <= 0:
                continue
            remaining = (remaining_map_before.get(po_item.id) or {}).get(
                "remaining", Decimal("0")
            )
            if remaining <= 0:
                return Response(
                    {
                        "detail": (
                            f"Stavka {po_item.id} je vec u potpunosti zaprimljena."
                        )
                    },
                    status=400,
                )
            if qty > (po_item.quantity or Decimal("0")):
                po_item.quantity = qty
                po_item.save(update_fields=["quantity"])
            ordinal += 1
            line_total = (actual_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            tax_rate = (
                po_item.artikl.tax_group.rate
                if po_item.artikl and getattr(po_item.artikl, "tax_group", None)
                else Decimal("0")
            )
            gross = (line_total * (Decimal("1") + Decimal(tax_rate))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            computed_total_net += line_total
            lines.append(
                WarehouseInputItem(
                    artikl=po_item.artikl,
                    product_id=po_item.artikl.rm_id if po_item.artikl else None,
                    product_name=po_item.artikl.name if po_item.artikl else "",
                    unit_of_measure=po_item.unit_of_measure,
                    unit_name=po_item.unit_of_measure.name if po_item.unit_of_measure else "",
                    quantity=qty,
                    price=actual_price,
                    total=line_total,
                    buying_price=actual_price,
                    gross_price=gross,
                    tax_rate=tax_rate,
                    calculate_tax=True,
                    ordinal=ordinal,
                )
            )

        if not lines:
            return Response(
                {
                    "detail": (
                        "Nema potvrdenih stavki s dostupnom preostalom kolicinom za zaprimanje."
                    )
                },
                status=400,
            )

        wi = WarehouseInput.objects.create(
            order=order,
            supplier=order.supplier,
            payment_type=order.payment_type,
            date=data.get("document_date") or timezone.localdate(),
            total=Decimal("0.00"),
            purchase_order=order,
            document_type_id=1,
            warehouse=warehouse,
            invoice_code=(data.get("invoice_code") or "").strip(),
            delivery_note=(data.get("delivery_note") or "").strip(),
        )
        for line in lines:
            line.warehouse_input = wi
        WarehouseInputItem.objects.bulk_create(lines)
        wi.recalculate_total(persist=True)

        automation = {
            "warehouse_input_posted": False,
            "supplier_invoice_created": False,
            "supplier_invoice_posted": False,
            "supplier_invoice_id": None,
            "supplier_invoice_number": "",
        }
        try:
            automation["warehouse_input_posted"] = _post_warehouse_input(
                wi,
                user=request.user,
            ) or bool(wi.stock_move_id and wi.journal_entry_id)

            invoice_code = (wi.invoice_code or "").strip()
            if invoice_code:
                supplier_invoice, created = _create_supplier_invoice_from_warehouse_input(wi)
                automation["supplier_invoice_created"] = created
                automation["supplier_invoice_id"] = supplier_invoice.id
                automation["supplier_invoice_number"] = supplier_invoice.invoice_number
                if _is_cash_payment_type(wi.payment_type):
                    posted = _post_supplier_invoice(supplier_invoice, user=request.user)
                    automation["supplier_invoice_posted"] = posted or bool(
                        supplier_invoice.journal_entry_id
                    )
        except DjangoValidationError as exc:
            transaction.set_rollback(True)
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=400)

        po_items = list(order.items.all().order_by("id"))
        received_by_artikl = _po_received_by_artikl(order)
        remaining_map = _po_item_remaining_map(po_items, received_by_artikl)
        if all(v["remaining"] == Decimal("0") for v in remaining_map.values()):
            order.status = PurchaseOrder.STATUS_RECEIVED_ALL
        else:
            order.status = PurchaseOrder.STATUS_RECEIVED
        if not order.primka_created:
            order.primka_created = True
            order.save(update_fields=["status", "primka_created"])
        else:
            order.save(update_fields=["status"])

        return Response(
            {
                "warehouse_input": {
                    "id": wi.id,
                    "document_date": wi.date,
                    "warehouse_id": warehouse.id,
                    "delivery_note": wi.delivery_note,
                    "invoice_code": wi.invoice_code,
                    "total_net": f"{_q2(wi.total):.2f}",
                },
                "purchase_order": {
                    "id": order.id,
                    "status_code": order.status,
                    "status_label": order.get_status_display(),
                    "primka_created": order.primka_created,
                },
                "automation": automation,
            },
            status=201,
        )


class WarehouseInputCreateSupplierInvoiceResponseSerializer(serializers.Serializer):
    warehouse_input_id = serializers.IntegerField()
    supplier_invoice_id = serializers.IntegerField()
    invoice_number = serializers.CharField()
    created = serializers.BooleanField()
    posted = serializers.BooleanField()


class WarehouseInputCreateSupplierInvoiceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: WarehouseInputCreateSupplierInvoiceResponseSerializer},
    )
    @transaction.atomic
    def post(self, request, pk):
        warehouse_input = (
            WarehouseInput.objects.select_related(
                "supplier",
                "document_type__ap_account",
                "payment_type",
            )
            .prefetch_related("supplier_invoices", "items__artikl__tax_group", "items__artikl__deposit")
            .filter(pk=pk)
            .first()
        )
        if not warehouse_input:
            return Response({"detail": "Primka ne postoji."}, status=404)

        try:
            supplier_invoice, created = _create_supplier_invoice_from_warehouse_input(warehouse_input)
        except DjangoValidationError as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=400)

        return Response(
            {
                "warehouse_input_id": warehouse_input.id,
                "supplier_invoice_id": supplier_invoice.id,
                "invoice_number": supplier_invoice.invoice_number,
                "created": created,
                "posted": bool(supplier_invoice.journal_entry_id),
            }
        )


class SupplierInvoicePostResponseSerializer(serializers.Serializer):
    supplier_invoice_id = serializers.IntegerField()
    journal_entry_id = serializers.IntegerField(allow_null=True)
    posted = serializers.BooleanField()
    already_posted = serializers.BooleanField()
    payment_status = serializers.CharField()


class SupplierInvoicePostView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: SupplierInvoicePostResponseSerializer},
    )
    @transaction.atomic
    def post(self, request, pk):
        supplier_invoice = (
            SupplierInvoice.objects.select_related(
                "document_type__ap_account",
                "cash_account",
                "ap_account",
                "deposit_account",
                "journal_entry",
            )
            .prefetch_related("inputs__items__artikl__tax_group", "inputs__items__artikl__deposit")
            .filter(pk=pk)
            .first()
        )
        if not supplier_invoice:
            return Response({"detail": "Ulazni račun ne postoji."}, status=404)

        already_posted = bool(supplier_invoice.journal_entry_id)
        posted = False
        if not already_posted:
            try:
                posted = _post_supplier_invoice(supplier_invoice, user=request.user)
            except DjangoValidationError as exc:
                detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                return Response({"detail": detail}, status=400)
            supplier_invoice.refresh_from_db(fields=["journal_entry", "payment_status"])

        return Response(
            {
                "supplier_invoice_id": supplier_invoice.id,
                "journal_entry_id": supplier_invoice.journal_entry_id,
                "posted": posted,
                "already_posted": already_posted,
                "payment_status": supplier_invoice.payment_status,
            }
        )


def _safe_format(template, context):
    try:
        return template.format_map(context)
    except KeyError:
        return template


class PurchaseOrderSendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        order = (
            PurchaseOrder.objects.select_related("supplier")
            .prefetch_related("items__artikl", "items__unit_of_measure")
            .filter(pk=pk)
            .first()
        )
        if not order:
            return Response({"detail": "Narudzba ne postoji."}, status=404)

        recipient = order.supplier.orders_email
        if not recipient:
            return Response({"detail": "Dobavljac nema email."}, status=400)

        template = (
            OrderEmailTemplate.objects.filter(active=True).order_by("-id").first()
        )
        company = CompanyProfile.objects.order_by("-id").first()

        token = order.ensure_confirmation_token()
        confirmation_url = request.build_absolute_uri(
            reverse("orders:purchase-order-confirm", args=[token])
        )
        context = {
            "order_id": order.id,
            "supplier_name": order.supplier.name,
            "confirmation_url": confirmation_url,
            "confirmation_link": confirmation_url,
        }
        subject_template = template.subject_template if template else "Narudzba #{order_id}"
        body_template = (
            template.body_template if template else "U prilogu se nalazi narudzba {order_id}."
        )
        subject = _safe_format(subject_template, context)
        body = _safe_format(body_template, context)
        if "{confirmation_url}" not in body_template and "{confirmation_link}" not in body_template:
            body = (
                f"{body}\n\nMolimo potvrdite primitak narudzžbe klikom na sljedeći link: {confirmation_url}"
            )

        pdf_bytes = build_order_pdf(order, company)
        from_email = None
        if settings.DEFAULT_FROM_EMAIL:
            name, addr = parseaddr(settings.DEFAULT_FROM_EMAIL)
            if addr:
                if name:
                    from_email = formataddr((name, addr))
                else:
                    from_email = formataddr(("Mozart Caffe Narudzbe", addr))
            else:
                from_email = settings.DEFAULT_FROM_EMAIL
        message = EmailMessage(
            subject=subject,
            body=body,
            to=[recipient],
            from_email=from_email,
        )
        message.attach(f"narudzba_{order.id}.pdf", pdf_bytes, "application/pdf")
        try:
            message.send()
        except Exception:
            logger.exception("purchase_order_email_send_failed order_id=%s", order.id)
            return Response(
                {
                    "detail": (
                        "Slanje emaila dobavljacu nije uspjelo (SMTP). "
                        "Provjerite postanski posluzitelj i mrezu; pokusajte ponovno kasnije."
                    )
                },
                status=502,
            )
        if order.status != PurchaseOrder.STATUS_CONFIRMED:
            order.status = PurchaseOrder.STATUS_SENT
            order.save(update_fields=["status"])

        supplier_name = order.supplier.name
        order_id = order.id
        transaction.on_commit(
            lambda: notify_purchase_order_topic.delay(
                event="sent",
                order_id=order_id,
                supplier_name=supplier_name,
            )
        )

        return Response({"detail": "Narudzba poslana.", "order_id": order.id})


class PurchaseOrderStatusTransitionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PurchaseOrderStatusTransitionSerializer,
        responses={200: PurchaseOrderSerializer},
    )
    @transaction.atomic
    def post(self, request, pk):
        serializer = PurchaseOrderStatusTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_status = serializer.validated_data["status"]

        order = (
            PurchaseOrder.objects.select_for_update()
            .filter(pk=pk)
            .first()
        )
        if not order:
            return Response({"detail": "Narudzba ne postoji."}, status=404)

        current_status = order.status
        allowed_transitions = {
            PurchaseOrder.STATUS_CREATED: PurchaseOrder.STATUS_CONFIRMED,
            PurchaseOrder.STATUS_SENT: PurchaseOrder.STATUS_CONFIRMED,
            PurchaseOrder.STATUS_RECEIVED: PurchaseOrder.STATUS_RECEIVED_ALL,
        }
        expected_target = allowed_transitions.get(current_status)
        if expected_target != target_status:
            return Response(
                {
                    "detail": (
                        f"Rucna promjena statusa iz '{current_status}' u "
                        f"'{target_status}' nije dopustena."
                    )
                },
                status=400,
            )

        update_fields = ["status"]
        order.status = target_status
        if target_status == PurchaseOrder.STATUS_CONFIRMED:
            order.confirmed_at = timezone.now()
            update_fields.append("confirmed_at")
        order.save(update_fields=update_fields)
        order = (
            PurchaseOrder.objects.select_related("supplier", "payment_type", "created_by")
            .prefetch_related("items__artikl__detail__base_group")
            .get(pk=order.pk)
        )

        if target_status == PurchaseOrder.STATUS_CONFIRMED:
            supplier_name = order.supplier.name
            order_id = order.pk
            transaction.on_commit(
                lambda: notify_purchase_order_topic.delay(
                    event="confirmed",
                    order_id=order_id,
                    supplier_name=supplier_name,
                )
            )

        return Response(
            _serialize_purchase_order_detail(
                None,
                order,
                request=request,
            )
        )


class SupplierArtiklListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, supplier_id):
        ordered_param = request.query_params.get("ordered_at")
        ordered_at = parse_datetime(ordered_param) if ordered_param else None
        if not ordered_at:
            ordered_at = timezone.now()
        order_date = ordered_at.date()

        items = (
            SupplierPriceItem.objects.select_related(
                "artikl",
                "artikl__category",
                "artikl__tax_group",
                "artikl__deposit",
                "unit_of_measure",
                "price_list",
                "artikl__detail__base_group",
            )
            .prefetch_related("artikl__packaging_levels__unit_of_measure")
            .filter(
                price_list__supplier_id=supplier_id,
                price_list__is_active=True,
            )
            .filter(
                Q(price_list__valid_from__isnull=True)
                | Q(price_list__valid_from__lte=order_date),
                Q(price_list__valid_to__isnull=True)
                | Q(price_list__valid_to__gte=order_date),
            )
            .order_by("-price_list__valid_from", "-price_list__created_at")
        )

        seen = set()
        artikl_entries = []
        artikl_rm_ids = set()
        for item in items:
            if not item.artikl_id:
                continue
            key = (item.artikl_id, item.unit_of_measure_id)
            if key in seen:
                continue
            seen.add(key)
            artikl = item.artikl
            if artikl and artikl.rm_id:
                artikl_rm_ids.add(artikl.rm_id)
            artikl_entries.append((item, artikl))

        stocks = {}
        if artikl_rm_ids:
            stock_rows = (
                WarehouseStock.objects.select_related("warehouse_id")
                .filter(product_id__in=artikl_rm_ids)
            )
            for row in stock_rows:
                stocks.setdefault(row.product_id, []).append(
                    {
                        "warehouse_id": row.warehouse_id.rm_id
                        if row.warehouse_id
                        else None,
                        "warehouse_name": row.warehouse_id.name
                        if row.warehouse_id
                        else "Skladiste",
                        "quantity": row.internal_quantity,
                    }
                )

        results = []
        category_path_cache = {}
        packaging_cache = {}
        for item, artikl in artikl_entries:
            detail = getattr(artikl, "detail", None)
            base_group = detail.base_group.name if detail and detail.base_group else None
            category = getattr(artikl, "category", None)
            if category and category.id not in category_path_cache:
                category_path_cache[category.id] = list(
                    category.get_ancestors(include_self=True).values_list("name", flat=True)
                )
            category_path = category_path_cache.get(category.id, []) if category else []
            unit = item.unit_of_measure or (detail.unit_of_measure if detail else None)
            unit_id = unit.id if unit else None
            unit_name = unit.name if unit else None
            image_url = artikl.image.url if artikl and artikl.image else None
            image_50x75_url = None
            vat_rate = artikl.tax_group.rate if artikl and getattr(artikl, "tax_group", None) else 0
            deposit_amount = artikl.deposit.amount_eur if artikl and getattr(artikl, "deposit", None) else 0
            packaging_levels = []
            packaging_path = ""
            if artikl:
                packaging_levels = packaging_cache.setdefault(
                    artikl.id,
                    _build_packaging_levels_payload(artikl),
                )
                packaging_path = artikl.packaging_path_summary()
            if artikl and artikl.image:
                image_50x75_url = f"/api/artikli/{artikl.rm_id}/image-50x75/"
            if image_url and request is not None:
                image_url = request.build_absolute_uri(image_url)
            if image_50x75_url and request is not None:
                image_50x75_url = request.build_absolute_uri(image_50x75_url)
            results.append(
                {
                    "artikl_id": artikl.id if artikl else None,
                    "artikl_rm_id": artikl.rm_id if artikl else None,
                    "name": artikl.name if artikl else None,
                    "code": artikl.code if artikl else None,
                    "image": image_url,
                    "image_50x75": image_50x75_url,
                    "base_group": base_group,
                    "vat_rate": vat_rate,
                    "deposit_amount": deposit_amount,
                    "category_id": category.id if category else None,
                    "category_name": category.name if category else None,
                    "category_sort_order": category.sort_order if category else None,
                    "category_path": category_path,
                    "packaging_path": packaging_path,
                    "packaging_levels": packaging_levels,
                    "unit_of_measure": unit_id,
                    "unit_name": unit_name,
                    "price": item.price,
                    "stocks": [
                        {
                            **stock_row,
                            "packaging_breakdown": _build_packaging_breakdown(
                                artikl, stock_row.get("quantity")
                            ),
                        }
                        for stock_row in stocks.get(artikl.rm_id, [])
                    ]
                    if artikl
                    else [],
                }
            )

        return Response({"count": len(results), "results": results})
