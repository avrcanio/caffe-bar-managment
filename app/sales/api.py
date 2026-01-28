from rest_framework import generics, serializers

from artikli.models import Artikl
from sales.models import Representation, RepresentationItem, RepresentationReason


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
            "user",
            "reason_id",
            "reason_name",
            "note",
            "items",
        ]
        read_only_fields = ["occurred_at", "user"]

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
