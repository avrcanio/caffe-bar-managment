from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated

from .models import Supplier


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "rm_id", "name"]


class SupplierListView(generics.ListAPIView):
    queryset = Supplier.objects.all().order_by("name")
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated]
