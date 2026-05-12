from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated

from .models import Supplier


class SupplierSerializer(serializers.ModelSerializer):
    default_payment_type = serializers.IntegerField(
        source="default_payment_type_id",
        read_only=True,
    )

    class Meta:
        model = Supplier
        fields = ["id", "rm_id", "name", "default_payment_type"]


class SupplierListView(generics.ListAPIView):
    queryset = Supplier.objects.select_related("default_payment_type").order_by("name")
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated]
