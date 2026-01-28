import io
import logging

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView
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
                "quantity": row.quantity,
            }
            for row in rows
        ]


class ArtiklListView(generics.ListCreateAPIView):
    queryset = Artikl.objects.all().order_by("id")
    serializer_class = ArtiklSerializer


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

    class Meta:
        model = DrinkCategory
        fields = [
            "id",
            "name",
            "parent_id",
            "parent_name",
            "is_active",
            "sort_order",
        ]


class DrinkCategoryListView(generics.ListCreateAPIView):
    queryset = DrinkCategory.objects.all().order_by("tree_id", "lft")
    serializer_class = DrinkCategorySerializer


class DrinkCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = DrinkCategory.objects.all()
    serializer_class = DrinkCategorySerializer


class ArtiklImage46x75View(APIView):
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
