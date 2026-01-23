import requests

from django.db import transaction
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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

    class Meta:
        model = Inventory
        fields = [
            "id",
            "warehouse",
            "warehouse_name",
            "date",
            "created_by",
        ]


class InventoryListCreateView(generics.ListCreateAPIView):
    queryset = Inventory.objects.all().order_by("-date", "-id")
    serializer_class = InventorySerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class InventoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Inventory.objects.all()
    serializer_class = InventorySerializer


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


class InventoryItemDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = InventoryItem.objects.all()
    serializer_class = InventoryItemSerializer


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
