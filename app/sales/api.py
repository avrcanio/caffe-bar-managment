from datetime import date

from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from artikli.models import Artikl
from sales.models import Representation, RepresentationItem, RepresentationReason, SalesInvoice
from sales.remaris_importer import import_sales_invoices, load_import_defaults
from sales.services import resolve_waiter_user


class RepresentationItemSerializer(serializers.ModelSerializer):
    artikl = serializers.SlugRelatedField(
        slug_field="rm_id",
        queryset=Artikl.objects.all(),
    )

    class Meta:
        model = RepresentationItem
        fields = ["id", "artikl", "quantity", "price"]


class RepresentationSerializer(serializers.ModelSerializer):
    items = RepresentationItemSerializer(many=True)
    warehouse_id = serializers.IntegerField(read_only=True)
    reason_id = serializers.PrimaryKeyRelatedField(
        source="reason",
        queryset=RepresentationReason.objects.all(),
    )
    reason_name = serializers.CharField(source="reason.name", read_only=True)

    class Meta:
        model = Representation
        fields = [
            "id",
            "occurred_at",
            "warehouse",
            "warehouse_id",
            "user",
            "reason_id",
            "reason_name",
            "note",
            "items",
        ]
        read_only_fields = ["occurred_at", "user"]

    def to_internal_value(self, data):
        if isinstance(data, dict) and "warehouse" not in data and "warehouse_id" in data:
            data = data.copy()
            data["warehouse"] = data["warehouse_id"]
        return super().to_internal_value(data)

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            validated_data["user"] = request.user
        representation = Representation.objects.create(**validated_data)
        RepresentationItem.objects.bulk_create(
            [
                RepresentationItem(representation=representation, **item)
                for item in items_data
            ]
        )
        return representation

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if items_data is not None:
            instance.items.all().delete()
            RepresentationItem.objects.bulk_create(
                [
                    RepresentationItem(representation=instance, **item)
                    for item in items_data
                ]
            )
        return instance


class RepresentationListView(generics.ListCreateAPIView):
    queryset = Representation.objects.all().order_by("-occurred_at")
    serializer_class = RepresentationSerializer


class RepresentationDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Representation.objects.all()
    serializer_class = RepresentationSerializer


class RepresentationReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = RepresentationReason
        fields = ["id", "code", "name", "is_active", "sort_order"]


class RepresentationReasonListView(generics.ListCreateAPIView):
    queryset = RepresentationReason.objects.all().order_by("sort_order", "name")
    serializer_class = RepresentationReasonSerializer


class RepresentationReasonDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = RepresentationReason.objects.all()
    serializer_class = RepresentationReasonSerializer


class RemarisImportView(APIView):
    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        date_from = serializers.DateField(required=False)
        date_to = serializers.DateField(required=False)

    def post(self, request):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        date_from = serializer.validated_data.get("date_from") or timezone.localdate()
        date_to = serializer.validated_data.get("date_to") or date_from

        defaults = load_import_defaults()
        created, updated, skipped = import_sales_invoices(
            date_from=date_from,
            date_to=date_to,
            **defaults,
        )

        mapped = 0
        for invoice in SalesInvoice.objects.filter(issued_on__gte=date_from, issued_on__lte=date_to, user__isnull=True):
            user = resolve_waiter_user(invoice.waiter_name)
            if user:
                invoice.user = user
                invoice.save(update_fields=["user"])
                mapped += 1

        return Response(
            {
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "mapped": mapped,
            },
            status=status.HTTP_200_OK,
        )
