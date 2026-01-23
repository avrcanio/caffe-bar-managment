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

from configuration.models import CompanyProfile, OrderEmailTemplate
from .models import PurchaseOrder, PurchaseOrderItem, SupplierPriceItem
from .pdf import build_order_pdf
from stock.models import WarehouseStock


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    artikl_name = serializers.CharField(source="artikl.name", read_only=True)
    base_group = serializers.SerializerMethodField()
    unit_name = serializers.CharField(
        source="unit_of_measure.name", read_only=True
    )
    order = serializers.PrimaryKeyRelatedField(read_only=True)

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
        ]

    def get_base_group(self, obj):
        detail = getattr(obj.artikl, "detail", None)
        base_group = getattr(detail, "base_group", None)
        return getattr(base_group, "name", None)


class PurchaseOrderSerializer(serializers.ModelSerializer):
    ordered_at = serializers.DateTimeField(required=False)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    payment_type_name = serializers.CharField(
        source="payment_type.name", read_only=True
    )
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
            "primka_created",
            "total_net",
            "total_gross",
            "total_deposit",
            "items",
        ]

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
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
        PurchaseOrder.objects.select_related("supplier", "payment_type")
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
        PurchaseOrder.objects.select_related("supplier", "payment_type")
        .prefetch_related("items__artikl__detail__base_group")
    )
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated]


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
                        "quantity": row.quantity,
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
            if image_url and request is not None:
                image_url = request.build_absolute_uri(image_url)
            results.append(
                {
                    "artikl_id": artikl.id if artikl else None,
                    "artikl_rm_id": artikl.rm_id if artikl else None,
                    "name": artikl.name if artikl else None,
                    "code": artikl.code if artikl else None,
                    "image": image_url,
                    "base_group": base_group,
                    "unit_of_measure": unit_id,
                    "unit_name": unit_name,
                    "price": item.price,
                    "stocks": stocks.get(artikl.rm_id, []) if artikl else [],
                }
            )

        return Response({"count": len(results), "results": results})
