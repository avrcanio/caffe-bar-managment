from rest_framework import generics, serializers

from artikli.models import Artikl, UnitOfMeasureData
from stock.models import Inventory, InventoryItem, WarehouseId


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
