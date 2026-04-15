import io
import logging
from decimal import Decimal

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework import generics, serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from PIL import Image, ImageOps

from .models import Artikl, ArtiklPackagingLevel, Category
from stock.models import WarehouseStock
from stock.services import refresh_warehouse_stock_for_product_code

logger = logging.getLogger(__name__)


def _serialize_numeric(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _build_packaging_level_payloads(artikl):
    total = Decimal("1")
    payloads = []
    for level in artikl.packaging_levels.order_by("sort_order", "id"):
        if level.sort_order == 0:
            current_total = Decimal("1")
        else:
            current_total = total * Decimal(str(level.contains_previous or 0))
        payloads.append(
            {
                "id": level.id,
                "sort_order": level.sort_order,
                "unit_of_measure": level.unit_of_measure_id,
                "unit_name": level.unit_of_measure.name,
                "level_name": level.level_name,
                "is_base": level.sort_order == 0,
                "base_quantity_total": current_total,
                "contains_previous": level.contains_previous,
            }
        )
        total = current_total
    return payloads


def _build_packaging_breakdown(artikl, quantity):
    levels = _build_packaging_level_payloads(artikl)
    if not levels:
        return []

    remaining = Decimal(str(quantity or 0))
    breakdown = []
    for level in reversed(levels):
        level_total = Decimal(str(level["base_quantity_total"]))
        if level["is_base"]:
            level_quantity = remaining
        else:
            level_quantity = remaining // level_total
            remaining -= level_quantity * level_total
        breakdown.append(
            {
                "sort_order": level["sort_order"],
                "unit_of_measure": level["unit_of_measure"],
                "unit_name": level["unit_name"],
                "level_name": level["level_name"],
                "base_quantity_total": _serialize_numeric(level["base_quantity_total"]),
                "quantity": _serialize_numeric(level_quantity),
            }
        )
    return breakdown


class ArtiklPackagingLevelSerializer(serializers.ModelSerializer):
    unit_name = serializers.CharField(source="unit_of_measure.name", read_only=True)
    level_name = serializers.SerializerMethodField()
    is_base = serializers.SerializerMethodField()
    base_quantity_total = serializers.SerializerMethodField()

    class Meta:
        model = ArtiklPackagingLevel
        fields = [
            "id",
            "sort_order",
            "unit_of_measure",
            "unit_name",
            "level_name",
            "is_base",
            "base_quantity_total",
            "contains_previous",
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_level_name(self, obj):
        return obj.level_name

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_base(self, obj):
        return obj.sort_order == 0

    @extend_schema_field(OpenApiTypes.NUMBER)
    def get_base_quantity_total(self, obj):
        for level in _build_packaging_level_payloads(obj.artikl):
            if level["id"] == obj.id:
                return _serialize_numeric(level["base_quantity_total"])
        return None


class ArtiklSerializer(serializers.ModelSerializer):
    image_46x75 = serializers.SerializerMethodField()
    image_50x75 = serializers.SerializerMethodField()
    image_125x200 = serializers.SerializerMethodField()
    vat_rate = serializers.SerializerMethodField()
    deposit_amount = serializers.SerializerMethodField()
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=Category.objects.all(),
        allow_null=True,
        required=False,
    )
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
    )
    category_sort_order = serializers.IntegerField(
        source="category.sort_order",
        read_only=True,
        allow_null=True,
    )
    packaging_path = serializers.SerializerMethodField()
    packaging_levels = ArtiklPackagingLevelSerializer(many=True, read_only=True)

    class Meta:
        model = Artikl
        fields = [
            "rm_id",
            "name",
            "code",
            "image",
            "image_46x75",
            "image_50x75",
            "image_125x200",
            "vat_rate",
            "deposit_amount",
            "category_id",
            "category_name",
            "category_sort_order",
            "packaging_path",
            "packaging_levels",
            "is_sellable",
            "is_stock_item",
        ]

    def get_image_46x75(self, obj):
        return _build_artikl_image_url(self.context.get("request"), obj, "image-46x75")

    def get_image_50x75(self, obj):
        return _build_artikl_image_url(self.context.get("request"), obj, "image-50x75")

    def get_image_125x200(self, obj):
        return _build_artikl_image_url(self.context.get("request"), obj, "image-125x200")

    def get_vat_rate(self, obj):
        tax_group = getattr(obj, "tax_group", None)
        return tax_group.rate if tax_group else 0

    def get_deposit_amount(self, obj):
        deposit = getattr(obj, "deposit", None)
        return deposit.amount_eur if deposit else 0

    @extend_schema_field(OpenApiTypes.STR)
    def get_packaging_path(self, obj):
        return obj.packaging_path_summary()


class ArtiklDetailSerializer(serializers.ModelSerializer):
    warehouse_stock = serializers.SerializerMethodField()
    image_46x75 = serializers.SerializerMethodField()
    image_50x75 = serializers.SerializerMethodField()
    image_125x200 = serializers.SerializerMethodField()
    vat_rate = serializers.SerializerMethodField()
    deposit_amount = serializers.SerializerMethodField()
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=Category.objects.all(),
        allow_null=True,
        required=False,
    )
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
    )
    category_sort_order = serializers.IntegerField(
        source="category.sort_order",
        read_only=True,
        allow_null=True,
    )
    packaging_path = serializers.SerializerMethodField()
    packaging_levels = ArtiklPackagingLevelSerializer(many=True, read_only=True)

    class Meta:
        model = Artikl
        fields = [
            "rm_id",
            "name",
            "code",
            "image",
            "image_46x75",
            "image_50x75",
            "image_125x200",
            "vat_rate",
            "deposit_amount",
            "warehouse_stock",
            "category_id",
            "category_name",
            "category_sort_order",
            "packaging_path",
            "packaging_levels",
            "is_sellable",
            "is_stock_item",
        ]

    def get_image_46x75(self, obj):
        return _build_artikl_image_url(self.context.get("request"), obj, "image-46x75")

    def get_image_50x75(self, obj):
        return _build_artikl_image_url(self.context.get("request"), obj, "image-50x75")

    def get_image_125x200(self, obj):
        return _build_artikl_image_url(self.context.get("request"), obj, "image-125x200")

    def get_vat_rate(self, obj):
        tax_group = getattr(obj, "tax_group", None)
        return tax_group.rate if tax_group else 0

    def get_deposit_amount(self, obj):
        deposit = getattr(obj, "deposit", None)
        return deposit.amount_eur if deposit else 0

    @extend_schema_field(OpenApiTypes.STR)
    def get_packaging_path(self, obj):
        return obj.packaging_path_summary()

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
                "packaging_breakdown": _build_packaging_breakdown(obj, row.internal_quantity),
            }
            for row in rows
        ]


class ArtiklListView(generics.ListCreateAPIView):
    queryset = (
        Artikl.objects.select_related("tax_group", "deposit")
        .prefetch_related("packaging_levels__unit_of_measure")
        .order_by("id")
    )
    serializer_class = ArtiklSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="category_id",
                type=int,
                required=False,
                location=OpenApiParameter.QUERY,
                description="Filtriraj artikle po kategoriji.",
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

        raw_category_id = self.request.query_params.get("category_id")
        if raw_category_id not in (None, ""):
            try:
                category_id = int(raw_category_id)
            except (TypeError, ValueError):
                raise ValidationError({"category_id": "category_id mora biti cijeli broj."})
            qs = qs.filter(category_id=category_id)

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
    queryset = Artikl.objects.select_related("tax_group", "deposit").prefetch_related(
        "packaging_levels__unit_of_measure"
    )
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


class CategorySerializer(serializers.ModelSerializer):
    parent_id = serializers.PrimaryKeyRelatedField(
        source="parent",
        queryset=Category.objects.all(),
        allow_null=True,
        required=False,
    )
    parent_name = serializers.CharField(source="parent.name", read_only=True)
    level = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "parent_id",
            "parent_name",
            "level",
            "is_active",
            "sort_order",
        ]


class CategoryListView(generics.ListCreateAPIView):
    queryset = Category.objects.all().order_by("tree_id", "lft")
    serializer_class = CategorySerializer

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


class CategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


def _build_artikl_image_url(request, artikl, variant: str):
    if not artikl.image:
        return None
    url = f"/api/artikli/{artikl.rm_id}/{variant}/"
    return request.build_absolute_uri(url) if request else url


def _render_artikl_image(artikl, *, size: tuple[int, int], mode: str):
    if not artikl.image:
        raise Http404("Image not found")
    with artikl.image.open("rb") as image_file:
        img = Image.open(image_file)
        img = ImageOps.exif_transpose(img)
        if mode == "fit":
            img = ImageOps.fit(img, size, Image.LANCZOS)
        elif mode == "contain":
            img = ImageOps.contain(img, size, Image.LANCZOS)
        else:
            raise ValueError(f"Unsupported image render mode: {mode}")
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


class ArtiklImage46x75View(APIView):
    permission_classes = [AllowAny]

    def get(self, request, rm_id):
        artikl = get_object_or_404(Artikl, rm_id=rm_id)
        return _render_artikl_image(artikl, size=(46, 75), mode="fit")


class ArtiklImage50x75View(APIView):
    permission_classes = [AllowAny]

    def get(self, request, rm_id):
        artikl = get_object_or_404(Artikl, rm_id=rm_id)
        return _render_artikl_image(artikl, size=(50, 75), mode="contain")


class ArtiklImage125x200View(APIView):
    permission_classes = [AllowAny]

    def get(self, request, rm_id):
        artikl = get_object_or_404(Artikl, rm_id=rm_id)
        return _render_artikl_image(artikl, size=(125, 200), mode="fit")
