import io
import logging

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework import generics, serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiParameter, extend_schema
from PIL import Image, ImageOps

from .models import Artikl, DrinkCategory
from stock.models import WarehouseStock
from stock.services import refresh_warehouse_stock_for_product_code

logger = logging.getLogger(__name__)


class ArtiklSerializer(serializers.ModelSerializer):
    image_46x75 = serializers.SerializerMethodField()
    image_125x200 = serializers.SerializerMethodField()
    drink_category_id = serializers.PrimaryKeyRelatedField(
        source="drink_category",
        queryset=DrinkCategory.objects.all(),
        allow_null=True,
        required=False,
    )
    drink_category_name = serializers.CharField(
        source="drink_category.name",
        read_only=True,
    )

    class Meta:
        model = Artikl
        fields = [
            "rm_id",
            "name",
            "code",
            "image",
            "image_46x75",
            "image_125x200",
            "drink_category_id",
            "drink_category_name",
            "is_sellable",
            "is_stock_item",
        ]

    def get_image_46x75(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        url = f"/api/artikli/{obj.rm_id}/image-46x75/"
        return request.build_absolute_uri(url) if request else url

    def get_image_125x200(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        url = f"/api/artikli/{obj.rm_id}/image-125x200/"
        return request.build_absolute_uri(url) if request else url


class ArtiklDetailSerializer(serializers.ModelSerializer):
    warehouse_stock = serializers.SerializerMethodField()
    image_46x75 = serializers.SerializerMethodField()
    image_125x200 = serializers.SerializerMethodField()
    drink_category_id = serializers.PrimaryKeyRelatedField(
        source="drink_category",
        queryset=DrinkCategory.objects.all(),
        allow_null=True,
        required=False,
    )
    drink_category_name = serializers.CharField(
        source="drink_category.name",
        read_only=True,
    )

    class Meta:
        model = Artikl
        fields = [
            "rm_id",
            "name",
            "code",
            "image",
            "image_46x75",
            "image_125x200",
            "warehouse_stock",
            "drink_category_id",
            "drink_category_name",
            "is_sellable",
            "is_stock_item",
        ]

    def get_image_46x75(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        url = f"/api/artikli/{obj.rm_id}/image-46x75/"
        return request.build_absolute_uri(url) if request else url

    def get_image_125x200(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        url = f"/api/artikli/{obj.rm_id}/image-125x200/"
        return request.build_absolute_uri(url) if request else url

    def get_warehouse_stock(self, obj):
        if not obj.code:
            return []
        rows = (
            WarehouseStock.objects.filter(product_code=obj.code)
            .select_related("warehouse_id")
            .order_by("id")
        )
        return [
            {
                "warehouse_id": row.warehouse_id.rm_id if row.warehouse_id else None,
                "warehouse_name": row.warehouse_id.name if row.warehouse_id else None,
                "quantity": row.internal_quantity,
            }
            for row in rows
        ]


class ArtiklListView(generics.ListCreateAPIView):
    queryset = Artikl.objects.all().order_by("id")
    serializer_class = ArtiklSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="drink_category_id",
                type=int,
                required=False,
                location=OpenApiParameter.QUERY,
                description="Filtriraj artikle po drink kategoriji.",
            ),
            OpenApiParameter(
                name="q",
                type=str,
                required=False,
                location=OpenApiParameter.QUERY,
                description="Pretraga po nazivu ili šifri artikla.",
            ),
            OpenApiParameter(
                name="is_sellable",
                type=bool,
                required=False,
                location=OpenApiParameter.QUERY,
                description="Filtriraj po prodajnom artiklu (true/false).",
            ),
            OpenApiParameter(
                name="is_stock_item",
                type=bool,
                required=False,
                location=OpenApiParameter.QUERY,
                description="Filtriraj po skladišnom artiklu (true/false).",
            ),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()

        raw_category_id = self.request.query_params.get("drink_category_id")
        if raw_category_id not in (None, ""):
            try:
                category_id = int(raw_category_id)
            except (TypeError, ValueError):
                raise ValidationError({"drink_category_id": "drink_category_id mora biti cijeli broj."})
            qs = qs.filter(drink_category_id=category_id)

        q = str(self.request.query_params.get("q", "")).strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))

        def parse_bool(value: str, field_name: str):
            normalized = str(value).strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
            raise ValidationError({field_name: f"{field_name} mora biti true/false ili 1/0."})

        raw_is_sellable = self.request.query_params.get("is_sellable")
        if raw_is_sellable not in (None, ""):
            qs = qs.filter(is_sellable=parse_bool(raw_is_sellable, "is_sellable"))

        raw_is_stock_item = self.request.query_params.get("is_stock_item")
        if raw_is_stock_item not in (None, ""):
            qs = qs.filter(is_stock_item=parse_bool(raw_is_stock_item, "is_stock_item"))

        return qs


class ArtiklDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Artikl.objects.all()
    serializer_class = ArtiklDetailSerializer
    lookup_field = "rm_id"
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        try:
            refresh_warehouse_stock_for_product_code(obj.code)
        except Exception:
            logger.exception("Failed to refresh warehouse stock for %s", obj.code)
        return super().get(request, *args, **kwargs)


from .models import UnitOfMeasureData


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasureData
        fields = ["rm_id", "name"]


class UnitOfMeasureListView(generics.ListAPIView):
    queryset = UnitOfMeasureData.objects.all().order_by("rm_id")
    serializer_class = UnitOfMeasureSerializer


class DrinkCategorySerializer(serializers.ModelSerializer):
    parent_id = serializers.PrimaryKeyRelatedField(
        source="parent",
        queryset=DrinkCategory.objects.all(),
        allow_null=True,
        required=False,
    )
    parent_name = serializers.CharField(source="parent.name", read_only=True)
    level = serializers.IntegerField(read_only=True)

    class Meta:
        model = DrinkCategory
        fields = [
            "id",
            "name",
            "parent_id",
            "parent_name",
            "level",
            "is_active",
            "sort_order",
        ]


class DrinkCategoryListView(generics.ListCreateAPIView):
    queryset = DrinkCategory.objects.all().order_by("tree_id", "lft")
    serializer_class = DrinkCategorySerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="include_inactive",
                type=int,
                required=False,
                location=OpenApiParameter.QUERY,
                description="Ako je 1, vraća i neaktivne kategorije (samo staff).",
            ),
            OpenApiParameter(
                name="level",
                type=int,
                required=False,
                location=OpenApiParameter.QUERY,
                description="Filtriraj po razini stabla (npr. 1, 2, 3).",
            ),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        include_inactive = str(self.request.query_params.get("include_inactive", "")).strip().lower()
        wants_inactive = include_inactive in {"1", "true", "yes", "on"}
        if wants_inactive:
            if not self.request.user.is_staff:
                raise PermissionDenied("Samo staff korisnici mogu tražiti neaktivne kategorije.")
        else:
            qs = qs.filter(is_active=True)

        raw_level = self.request.query_params.get("level")
        if raw_level not in (None, ""):
            try:
                level = int(raw_level)
            except (TypeError, ValueError):
                raise ValidationError({"level": "level mora biti cijeli broj."})
            if level < 0:
                raise ValidationError({"level": "level mora biti >= 0."})
            qs = qs.filter(level=level)
        return qs


class DrinkCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = DrinkCategory.objects.all()
    serializer_class = DrinkCategorySerializer


class ArtiklImage46x75View(APIView):
    permission_classes = [AllowAny]

    def get(self, request, rm_id):
        artikl = get_object_or_404(Artikl, rm_id=rm_id)
        if not artikl.image:
            raise Http404("Image not found")
        with artikl.image.open("rb") as image_file:
            img = Image.open(image_file)
            img = ImageOps.exif_transpose(img)
            img = ImageOps.fit(img, (46, 75), Image.LANCZOS)
            img_format = (img.format or "PNG").upper()
            if img_format == "JPG":
                img_format = "JPEG"
            if img_format == "JPEG" and img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            buffer = io.BytesIO()
            img.save(buffer, format=img_format)
            buffer.seek(0)
            content_type = Image.MIME.get(img_format, "application/octet-stream")
            return HttpResponse(buffer.getvalue(), content_type=content_type)


class ArtiklImage125x200View(APIView):
    permission_classes = [AllowAny]

    def get(self, request, rm_id):
        artikl = get_object_or_404(Artikl, rm_id=rm_id)
        if not artikl.image:
            raise Http404("Image not found")
        with artikl.image.open("rb") as image_file:
            img = Image.open(image_file)
            img = ImageOps.exif_transpose(img)
            img = ImageOps.fit(img, (125, 200), Image.LANCZOS)
            img_format = (img.format or "PNG").upper()
            if img_format == "JPG":
                img_format = "JPEG"
            if img_format == "JPEG" and img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            buffer = io.BytesIO()
            img.save(buffer, format=img_format)
            buffer.seek(0)
            content_type = Image.MIME.get(img_format, "application/octet-stream")
            return HttpResponse(buffer.getvalue(), content_type=content_type)
