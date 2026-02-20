import requests

import hashlib
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.contrib.auth import get_user_model

from artikli.models import Artikl, UnitOfMeasureData
from artikli.remaris_connector import RemarisConnector
from stock.models import Inventory, InventoryItem, WarehouseId
from stock.models import WarehouseStock


class InventorySerializer(serializers.ModelSerializer):
    warehouse = serializers.SlugRelatedField(
        slug_field="rm_id",
        queryset=WarehouseId.objects.all(),
        allow_null=True,
        required=False,
    )
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    created_by = serializers.CharField(source="created_by.username", read_only=True)
    counted_by = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(),
        allow_null=True,
        required=False,
    )
    counted_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Inventory
        fields = [
            "id",
            "name",
            "note",
            "warehouse",
            "warehouse_name",
            "date",
            "created_by",
            "counted_by",
            "counted_by_name",
        ]

    def get_counted_by_name(self, obj):
        u = getattr(obj, "counted_by", None)
        if not u:
            return None
        full = f"{getattr(u,'first_name','') or ''} {getattr(u,'last_name','') or ''}".strip()
        return full or getattr(u, "username", None)


class InventoryListCreateView(generics.ListCreateAPIView):
    queryset = Inventory.objects.all().order_by("-date", "-id")
    serializer_class = InventorySerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class InventoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Inventory.objects.all()
    serializer_class = InventorySerializer
    permission_classes = [IsAuthenticated]


class WarehouseIdSerializer(serializers.ModelSerializer):
    class Meta:
        model = WarehouseId
        fields = ["rm_id", "name", "hidden", "ordinal"]


class WarehouseIdListView(generics.ListAPIView):
    queryset = WarehouseId.objects.all().order_by("rm_id")
    serializer_class = WarehouseIdSerializer


class InventoryItemSerializer(serializers.ModelSerializer):
    inventory = serializers.PrimaryKeyRelatedField(queryset=Inventory.objects.all())
    artikl = serializers.SlugRelatedField(
        slug_field="rm_id",
        queryset=Artikl.objects.all(),
        allow_null=True,
        required=False,
    )
    artikl_name = serializers.CharField(source="artikl.name", read_only=True)
    unit = serializers.SlugRelatedField(
        slug_field="rm_id",
        queryset=UnitOfMeasureData.objects.all(),
        allow_null=True,
        required=False,
    )
    unit_name = serializers.CharField(source="unit.name", read_only=True)

    class Meta:
        model = InventoryItem
        fields = [
            "id",
            "inventory",
            "artikl",
            "artikl_name",
            "quantity",
            "unit",
            "unit_name",
            "note",
        ]


class InventoryItemListCreateView(generics.ListCreateAPIView):
    queryset = InventoryItem.objects.all().order_by("-id")
    serializer_class = InventoryItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset().select_related("artikl", "unit", "inventory")

        # Optional filtering: /api/inventory-items/?inventory=26 or ?inventory=26&inventory=32
        # Keep default behavior (no filter) for existing callers.
        raw_ids = self.request.query_params.getlist("inventory") or self.request.query_params.getlist("inventory_id")
        if not raw_ids:
            raw_single = self.request.query_params.get("inventory")
            if raw_single:
                raw_ids = [raw_single]

        inv_ids = []
        for raw in raw_ids:
            if not raw:
                continue
            # Support comma-separated list: inventory=26,32
            parts = [p.strip() for p in str(raw).split(",") if p.strip()]
            for p in parts:
                try:
                    inv_ids.append(int(p))
                except (TypeError, ValueError):
                    continue

        if inv_ids:
            qs = qs.filter(inventory_id__in=sorted(set(inv_ids)))

        return qs


class InventoryItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = InventoryItem.objects.all()
    serializer_class = InventoryItemSerializer
    permission_classes = [IsAuthenticated]


class PublicInventoryItemSerializer(serializers.ModelSerializer):
    artikl_rm_id = serializers.IntegerField(source="artikl.rm_id", read_only=True)
    artikl_name = serializers.CharField(source="artikl.name", read_only=True)
    artikl_code = serializers.CharField(source="artikl.code", read_only=True)
    image_46x75 = serializers.SerializerMethodField()
    unit_rm_id = serializers.IntegerField(source="unit.rm_id", read_only=True)
    unit_name = serializers.CharField(source="unit.name", read_only=True)

    class Meta:
        model = InventoryItem
        fields = [
            "id",
            "artikl_rm_id",
            "artikl_name",
            "artikl_code",
            "image_46x75",
            "quantity",
            "unit_rm_id",
            "unit_name",
            "note",
        ]

    def get_image_46x75(self, obj):
        artikl = getattr(obj, "artikl", None)
        if not artikl or not getattr(artikl, "image", None):
            return None
        request = self.context.get("request")
        url = f"/api/artikli/{artikl.rm_id}/image-46x75/"
        return request.build_absolute_uri(url) if request else url


class PublicInventorySerializer(serializers.ModelSerializer):
    warehouse_rm_id = serializers.IntegerField(source="warehouse.rm_id", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    counted_by_name = serializers.SerializerMethodField()
    readonly = serializers.SerializerMethodField()
    items = PublicInventoryItemSerializer(many=True, read_only=True)

    class Meta:
        model = Inventory
        fields = [
            "id",
            "name",
            "warehouse_rm_id",
            "warehouse_name",
            "date",
            "opens_at",
            "closes_at",
            "status",
            "submitted_at",
            "counted_by_name",
            "readonly",
            "items",
        ]

    def get_counted_by_name(self, obj):
        u = getattr(obj, "counted_by", None)
        if not u:
            return None
        full = f"{getattr(u,'first_name','') or ''} {getattr(u,'last_name','') or ''}".strip()
        return full or getattr(u, "username", None)

    def get_readonly(self, obj):
        return bool(obj.submitted_at) or obj.status == Inventory.Status.CLOSED


class InventoryPublicDetailView(APIView):
    """
    Public inventory view used by `/inventory/<token>` frontend.
    Token is a bearer secret; we store sha256(token) in Inventory.public_token_digest.
    """

    # Public endpoint: disable session auth to avoid CSRF enforcement.
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token: str):
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        inv = (
            Inventory.objects.select_related("warehouse")
            .prefetch_related("items__artikl", "items__unit")
            .filter(public_token_digest=digest)
            .first()
        )
        if not inv:
            return Response({"detail": "Not found."}, status=404)

        now = timezone.now()
        if inv.opens_at and now < inv.opens_at:
            return Response({"detail": "Inventura još nije otvorena."}, status=403)
        if inv.closes_at and now > inv.closes_at:
            return Response({"detail": "Inventura je istekla."}, status=403)

        ser = PublicInventorySerializer(inv, context={"request": request})
        return Response(ser.data)


def _parse_decimal(raw):
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw))
    if isinstance(raw, str):
        s = raw.replace(",", ".").strip()
        if s == "":
            return None
        return Decimal(s)
    raise InvalidOperation()


class InventoryPublicSubmitView(APIView):
    # Public endpoint: disable session auth to avoid CSRF enforcement.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, token: str):
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()

        with transaction.atomic():
            inv = (
                Inventory.objects.select_for_update()
                .filter(public_token_digest=digest)
                .first()
            )
            if not inv:
                return Response({"detail": "Not found."}, status=404)

            now = timezone.now()
            if inv.opens_at and now < inv.opens_at:
                return Response({"detail": "Inventura još nije otvorena."}, status=403)
            if inv.closes_at and now > inv.closes_at:
                return Response({"detail": "Inventura je istekla."}, status=403)
            if inv.submitted_at or inv.status == Inventory.Status.CLOSED:
                return Response({"detail": "Inventura je već predana i zaključana."}, status=409)

            payload_items = request.data.get("items") or []
            if not isinstance(payload_items, list) or not payload_items:
                return Response({"detail": "Nema stavki."}, status=400)

            inv_items = list(
                InventoryItem.objects.select_for_update()
                .filter(inventory=inv)
            )
            by_id = {it.id: it for it in inv_items}
            expected_ids = set(by_id.keys())

            seen = set()
            updates = []
            for row in payload_items:
                if not isinstance(row, dict):
                    return Response({"detail": "Neispravan format stavki."}, status=400)
                item_id = row.get("id")
                if item_id is None:
                    return Response({"detail": "Stavka mora imati id."}, status=400)
                try:
                    item_id = int(item_id)
                except Exception:
                    return Response({"detail": "Neispravan id stavke."}, status=400)
                if item_id in seen:
                    return Response({"detail": "Duplikat stavke."}, status=400)
                seen.add(item_id)
                it = by_id.get(item_id)
                if not it:
                    return Response({"detail": "Stavka ne pripada inventuri."}, status=400)
                try:
                    qty = _parse_decimal(row.get("quantity"))
                except (InvalidOperation, Exception):
                    return Response({"detail": "Neispravna količina."}, status=400)
                if qty is None:
                    return Response({"detail": "Količina je obavezna za sve stavke."}, status=400)
                if qty < 0:
                    return Response({"detail": "Količina mora biti >= 0."}, status=400)
                note = row.get("note", None)
                if note is None:
                    note = ""
                if not isinstance(note, str):
                    return Response({"detail": "Neispravna napomena."}, status=400)
                it.quantity = qty.quantize(Decimal("0.0001"))
                it.note = note.strip()[:2000]
                updates.append(it)

            if seen != expected_ids:
                return Response(
                    {"detail": "Morate poslati sve stavke inventure."},
                    status=400,
                )

            InventoryItem.objects.bulk_update(updates, ["quantity", "note"])

            inv.submitted_at = now
            inv.submitted_by_name = (request.data.get("submitted_by_name") or "").strip()[:120]
            inv.submitted_ip = request.META.get("REMOTE_ADDR")
            inv.submitted_user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:400]
            if inv.status != Inventory.Status.CLOSED:
                inv.status = Inventory.Status.COUNTED
            inv.save(
                update_fields=[
                    "submitted_at",
                    "submitted_by_name",
                    "submitted_ip",
                    "submitted_user_agent",
                    "status",
                ]
            )

        return Response({"detail": "OK", "inventory_id": inv.id, "submitted_at": inv.submitted_at})


class WarehouseStockSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        warehouses = list(WarehouseId.objects.all())
        if not warehouses:
            return Response(
                {"detail": "Nema skladista za sync."},
                status=400,
            )

        connector = RemarisConnector()
        connector.login()

        created = 0
        updated = 0
        skipped = 0

        try:
            with transaction.atomic():
                for warehouse in warehouses:
                    payload = {
                        "dataSource": "warehouseStockDS",
                        "operationType": "fetch",
                        "startRow": 0,
                        "endRow": 10001,
                        "textMatchStyle": "exact",
                        "componentId": "warehouseStockGrid",
                        "oldValues": None,
                        "data": {
                            "warehouseId": warehouse.rm_id,
                            "allBaseGroups": True,
                            "showFilter": 20,
                            "request": "?_3403.578121292664",
                        },
                    }

                    response = connector.post_json(
                        "WarehouseStock/GetGridData?isc_dataFormat=json",
                        payload,
                        referer_path="/WarehouseStock",
                    )

                    data = response.get("response", {}).get("data", [])

                    for item in data:
                        wh_id = item.get("id")
                        if wh_id is None:
                            skipped += 1
                            continue

                        product_code = item.get("productCode", "")
                        product = None
                        if product_code:
                            product = Artikl.objects.filter(code=product_code).first()

                        defaults = {
                            "warehouse_id_id": warehouse.rm_id,
                            "product": product,
                            "product_name": item.get("productName", ""),
                            "product_code": product_code,
                            "unit": item.get("unit", ""),
                            "quantity": item.get("quantity", 0),
                            "base_group_name": item.get("baseGroupName", ""),
                            "active": bool(item.get("active", False)),
                        }

                        _, was_created = WarehouseStock.objects.update_or_create(
                            wh_id=wh_id,
                            defaults=defaults,
                        )
                        if was_created:
                            created += 1
                        else:
                            updated += 1
        except requests.RequestException as exc:
            status_code = None
            response_text = None
            if getattr(exc, "response", None) is not None:
                status_code = exc.response.status_code
                response_text = exc.response.text
            detail = "status={status} response={response}".format(
                status=status_code if status_code is not None else "n/a",
                response=response_text if response_text else "n/a",
            )
            return Response(
                {"detail": f"Sync failed. Remaris request error. {detail}"},
                status=502,
            )

        return Response(
            {
                "detail": "Sync complete.",
                "created": created,
                "updated": updated,
                "skipped": skipped,
            }
        )
