from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated

from .models import PaymentType


class PaymentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentType
        fields = ["id", "name"]


class PaymentTypeListView(generics.ListAPIView):
    queryset = PaymentType.objects.all().order_by("name")
    serializer_class = PaymentTypeSerializer
    permission_classes = [IsAuthenticated]
