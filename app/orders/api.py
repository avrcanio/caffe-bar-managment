from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.conf import settings
from django.core.mail import EmailMessage
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
from .models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderItemPriceAudit,
    WarehouseInput,
    WarehouseInputItem,
    SupplierPriceItem,
    SupplierPriceList,
)
from .pdf import build_order_pdf
from stock.models import WarehouseStock, WarehouseId


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

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        request = self.context.get("request")
        if request and request.user and not validated_data.get("created_by"):
            validated_data["created_by"] = request.user
        if not validated_data.get("ordered_at"):
            validated_data["ordered_at"] = timezone.now()
        order = PurchaseOrder.objects.create(**validated_data)
        for item_data in items_data:
            PurchaseOrderItem.objects.create(order=order, **item_data)
        order.recalculate_totals()
        return order

    @transaction.atomic
    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
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
        .order_by("-ordered_at")
    )
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PurchaseOrderPagination

    def get_queryset(self):
        qs = super().get_queryset()
        status = self.request.query_params.get("status")
        supplier = self.request.query_params.get("supplier")
        ordered_from = self.request.query_params.get("ordered_from")
        ordered_to = self.request.query_params.get("ordered_to")

        if status:
            qs = qs.filter(status=status)
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
        response.data = {
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
            "results": response.data["results"]
            if isinstance(response.data, dict) and "results" in response.data
            else response.data,
        }
        return response


class PurchaseOrderDetailView(generics.RetrieveUpdateAPIView):
    queryset = (
        PurchaseOrder.objects.select_related("supplier", "payment_type", "created_by")
        .prefetch_related("items__artikl__detail__base_group")
    )
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        po_items = list(instance.items.all().order_by("id"))
        received_by_artikl = _po_received_by_artikl(instance)
        remaining_by_item_id = _po_item_remaining_map(po_items, received_by_artikl)
        serializer = self.get_serializer(
            instance,
            context={
                **self.get_serializer_context(),
                "remaining_by_item_id": remaining_by_item_id,
            },
        )
        return Response(serializer.data)


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
        req_by_id = {int(row["purchase_order_item_id"]): row for row in request_items}
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
            if qty > remaining:
                return Response(
                    {
                        "detail": (
                            f"Kolicina za stavku {po_item.id} ({qty}) prelazi preostalo ({remaining})."
                        )
                    },
                    status=400,
                )
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
            },
            status=201,
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
        message.send()
        if order.status != PurchaseOrder.STATUS_CONFIRMED:
            order.status = PurchaseOrder.STATUS_SENT
            order.save(update_fields=["status"])

        return Response({"detail": "Narudzba poslana.", "order_id": order.id})


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
                "unit_of_measure",
                "price_list",
                "artikl__detail__base_group",
            )
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
        for item, artikl in artikl_entries:
            detail = getattr(artikl, "detail", None)
            base_group = detail.base_group.name if detail and detail.base_group else None
            unit = item.unit_of_measure or (detail.unit_of_measure if detail else None)
            unit_id = unit.id if unit else None
            unit_name = unit.name if unit else None
            image_url = artikl.image.url if artikl and artikl.image else None
            image_46x75_url = None
            if artikl and artikl.image:
                image_46x75_url = f"/api/artikli/{artikl.rm_id}/image-46x75/"
            if image_url and request is not None:
                image_url = request.build_absolute_uri(image_url)
            if image_46x75_url and request is not None:
                image_46x75_url = request.build_absolute_uri(image_46x75_url)
            results.append(
                {
                    "artikl_id": artikl.id if artikl else None,
                    "artikl_rm_id": artikl.rm_id if artikl else None,
                    "name": artikl.name if artikl else None,
                    "code": artikl.code if artikl else None,
                    "image": image_url,
                    "image_46x75": image_46x75_url,
                    "base_group": base_group,
                    "unit_of_measure": unit_id,
                    "unit_name": unit_name,
                    "price": item.price,
                    "stocks": stocks.get(artikl.rm_id, []) if artikl else [],
                }
            )

        return Response({"count": len(results), "results": results})
