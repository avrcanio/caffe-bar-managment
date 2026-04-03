import json
import logging

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.utils.html import format_html
from django.urls import path, reverse
from django.utils import timezone

from .models import (
    BarionCategory,
    BarionCategorySettings,
    BarionRuntimeMode,
    CheckItemModifierSelection,
    Check,
    CheckItem,
    ItemBundleOption,
    ItemModifierDefaultSelection,
    ItemModifierGroup,
    ItemModifierGroupAssignment,
    ItemModifierOption,
    Layout,
    LayoutTable,
    SettlementPart,
    Table,
    TableState,
    UserLayoutAccess,
    Zone,
)

logger = logging.getLogger(__name__)


@admin.register(BarionCategory)
class BarionCategoryAdmin(admin.ModelAdmin):
    list_display = ("category", "sort_order", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("category__name",)
    autocomplete_fields = ("category",)
    ordering = ("sort_order", "category__name", "id")


@admin.register(BarionCategorySettings)
class BarionCategorySettingsAdmin(admin.ModelAdmin):
    list_display = (
        "day_start",
        "day_end",
        "night_start",
        "night_end",
        "day_lookback_days",
        "night_lookback_days",
        "updated_at",
    )
    fields = (
        "day_start",
        "day_end",
        "night_start",
        "night_end",
        "day_lookback_days",
        "night_lookback_days",
        "updated_at",
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not BarionCategorySettings.objects.filter(pk=1).exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        BarionCategorySettings.get_solo()
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("label", "capacity", "shape", "is_vip", "width", "height", "updated_at")
    list_filter = ("shape", "is_vip")
    search_fields = ("label",)
    ordering = ("label",)


@admin.register(Layout)
class LayoutAdmin(admin.ModelAdmin):
    change_form_template = "admin/barion/layout/change_form.html"
    list_display = ("name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("name",)

    @staticmethod
    def _default_size_for_shape(shape: str) -> tuple[int, int]:
        if shape == Table.Shape.RECTANGLE:
            return (120, 80)
        if shape == Table.Shape.ROUND:
            return (90, 90)
        if shape == Table.Shape.SQUARE:
            return (90, 90)
        return (100, 100)

    @staticmethod
    def _parse_int(value, *, field: str, minimum: int | None = None, maximum: int | None = None):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field} mora biti broj.")
        if minimum is not None and parsed < minimum:
            raise ValueError(f"{field} mora biti >= {minimum}.")
        if maximum is not None and parsed > maximum:
            raise ValueError(f"{field} mora biti <= {maximum}.")
        return parsed

    def _get_layout_for_change(self, request, layout_id: int) -> Layout:
        layout = get_object_or_404(Layout, pk=layout_id)
        if not self.has_change_permission(request, layout):
            raise PermissionDenied("Nemate prava za uređivanje layouta.")
        return layout

    def _build_editor_context(self, request, layout: Layout):
        return {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "layout": layout,
            "title": f"Layout editor: {layout.name}",
            "editor_data_url": reverse("admin:barion_layout_editor_data", args=[layout.id]),
            "editor_save_url": reverse("admin:barion_layout_editor_save", args=[layout.id]),
            "layout_change_url": reverse("admin:barion_layout_change", args=[layout.id]),
        }

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:layout_id>/editor/",
                self.admin_site.admin_view(self.layout_editor_view),
                name="barion_layout_editor",
            ),
            path(
                "<int:layout_id>/editor/data/",
                self.admin_site.admin_view(self.layout_editor_data_view),
                name="barion_layout_editor_data",
            ),
            path(
                "<int:layout_id>/editor/save/",
                self.admin_site.admin_view(self.layout_editor_save_view),
                name="barion_layout_editor_save",
            ),
        ]
        return custom + urls

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        if object_id:
            extra_context["layout_editor_url"] = reverse("admin:barion_layout_editor", args=[object_id])
        return super().change_view(request, object_id, form_url=form_url, extra_context=extra_context)

    def layout_editor_view(self, request, layout_id: int):
        layout = self._get_layout_for_change(request, layout_id)
        return TemplateResponse(
            request,
            "admin/barion/layout/editor.html",
            self._build_editor_context(request, layout),
        )

    def layout_editor_data_view(self, request, layout_id: int):
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])
        layout = self._get_layout_for_change(request, layout_id)

        zone_qs = layout.zones.order_by("order", "id")
        if not zone_qs.exists():
            # Ensure editor always has at least one target zone for add/move operations.
            Zone.objects.create(
                layout=layout,
                name="Main",
                order=1,
                color="#4a90e2",
            )
            zone_qs = layout.zones.order_by("order", "id")

        zones = list(zone_qs.values("id", "name", "order", "color"))
        zone_ids = {z["id"] for z in zones}
        fallback_zone_id = zones[0]["id"]

        placements = [
            {
                "layout_table_id": placement.id,
                "table_id": placement.table_id,
                "label": placement.table.label,
                "shape": placement.table.shape,
                "capacity": placement.table.capacity,
                "is_vip": placement.table.is_vip,
                "x": placement.x,
                "y": placement.y,
                "w": placement.w,
                "h": placement.h,
                "rotation": placement.rotation,
                "is_enabled": placement.is_enabled,
                "z_index": placement.z_index,
                "zone_id": placement.zone_id if placement.zone_id in zone_ids else fallback_zone_id,
            }
            for placement in LayoutTable.objects.select_related("table", "zone")
            .filter(layout=layout)
            .order_by("z_index", "id")
        ]
        available_tables = list(
            Table.objects.exclude(layout_tables__layout=layout)
            .order_by("label")
            .values("id", "label", "shape", "capacity", "is_vip")
        )

        return JsonResponse(
            {
                "layout": {
                    "id": layout.id,
                    "name": layout.name,
                    "is_active": layout.is_active,
                    "updated_at": layout.updated_at.isoformat(),
                },
                "zones": zones,
                "placements": placements,
                "available_tables": available_tables,
            }
        )

    def layout_editor_save_view(self, request, layout_id: int):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        layout = self._get_layout_for_change(request, layout_id)

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Neispravan JSON payload."}, status=400)

        raw_placements = payload.get("placements")
        if not isinstance(raw_placements, list):
            return JsonResponse({"detail": "placements mora biti lista."}, status=400)

        zone_map = {z.id: z for z in layout.zones.all()}
        layout_table_ids = [
            item.get("layout_table_id")
            for item in raw_placements
            if item.get("layout_table_id") is not None
        ]

        updated = 0
        created = 0
        try:
            with transaction.atomic():
                existing = {
                    lt.id: lt
                    for lt in LayoutTable.objects.select_related("table").filter(
                        layout=layout,
                        id__in=layout_table_ids,
                    )
                }
                for item in raw_placements:
                    if not isinstance(item, dict):
                        raise ValueError("Svaki placement mora biti objekt.")
                    lt_id = item.get("layout_table_id")
                    zone_id = self._parse_int(item.get("zone_id"), field="zone_id", minimum=1)
                    zone = zone_map.get(zone_id)
                    if not zone:
                        raise ValueError(f"Zona {zone_id} ne pripada odabranom layoutu.")

                    if lt_id is None:
                        table_id = self._parse_int(item.get("table_id"), field="table_id", minimum=1)
                        table = get_object_or_404(Table, id=table_id)
                        default_w, default_h = self._default_size_for_shape(table.shape)

                        x = self._parse_int(item.get("x", 20), field="x", minimum=0, maximum=1000)
                        y = self._parse_int(item.get("y", 20), field="y", minimum=0, maximum=2000)
                        w = self._parse_int(item.get("w", default_w), field="w", minimum=1, maximum=1000)
                        h = self._parse_int(item.get("h", default_h), field="h", minimum=1, maximum=2000)
                        rotation = self._parse_int(
                            item.get("rotation", 0),
                            field="rotation",
                            minimum=-360,
                            maximum=360,
                        )
                        z_index = self._parse_int(item.get("z_index", 0), field="z_index")

                        try:
                            LayoutTable.objects.create(
                                layout=layout,
                                table=table,
                                zone=zone,
                                x=x,
                                y=y,
                                w=w,
                                h=h,
                                rotation=rotation,
                                is_enabled=bool(item.get("is_enabled", True)),
                                z_index=z_index,
                            )
                        except IntegrityError:
                            return JsonResponse(
                                {"detail": f"Table {table_id} je već u ovom layoutu."},
                                status=400,
                            )
                        created += 1
                        continue

                    lt_id = self._parse_int(lt_id, field="layout_table_id", minimum=1)
                    placement = existing.get(lt_id)
                    if not placement:
                        raise ValueError(f"LayoutTable {lt_id} ne postoji za ovaj layout.")

                    placement.x = self._parse_int(item.get("x", placement.x), field="x", minimum=0, maximum=1000)
                    placement.y = self._parse_int(item.get("y", placement.y), field="y", minimum=0, maximum=2000)
                    placement.w = self._parse_int(item.get("w", placement.w), field="w", minimum=1, maximum=1000)
                    placement.h = self._parse_int(item.get("h", placement.h), field="h", minimum=1, maximum=2000)
                    placement.rotation = self._parse_int(
                        item.get("rotation", placement.rotation),
                        field="rotation",
                        minimum=-360,
                        maximum=360,
                    )
                    placement.is_enabled = bool(item.get("is_enabled", placement.is_enabled))
                    placement.z_index = self._parse_int(item.get("z_index", placement.z_index), field="z_index")
                    placement.zone = zone
                    try:
                        placement.save(
                            update_fields=[
                                "x",
                                "y",
                                "w",
                                "h",
                                "rotation",
                                "is_enabled",
                                "z_index",
                                "zone",
                                "updated_at",
                            ]
                        )
                    except IntegrityError:
                        return JsonResponse(
                            {"detail": f"Table {placement.table_id} je već u ovom layoutu."},
                            status=400,
                        )
                    updated += 1

                layout.updated_at = timezone.now()
                layout.save(update_fields=["updated_at"])
        except ValueError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        except IntegrityError:
            return JsonResponse({"detail": "Spremanje layouta nije uspjelo zbog konflikta podataka."}, status=409)
        except Exception:
            logger.exception("Layout editor save failed for layout_id=%s", layout_id)
            return JsonResponse({"detail": "Neočekivana greška pri spremanju layouta."}, status=500)

        return JsonResponse({"ok": True, "updated": updated, "created": created})


@admin.register(UserLayoutAccess)
class UserLayoutAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "layout", "is_default", "is_active", "updated_at")
    list_filter = ("is_default", "is_active", "layout")
    search_fields = ("user__username", "user__email", "layout__name")
    autocomplete_fields = ("user", "layout")
    ordering = ("user__username", "-is_default", "layout__name")


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "layout", "order", "color", "updated_at")
    list_filter = ("layout",)
    search_fields = ("name", "layout__name")
    autocomplete_fields = ("layout",)
    ordering = ("layout", "order", "name")


@admin.register(LayoutTable)
class LayoutTableAdmin(admin.ModelAdmin):
    list_display = ("layout", "table", "zone", "x", "y", "w", "h", "rotation", "is_enabled", "z_index")
    list_filter = ("layout", "zone", "is_enabled", "table__shape", "table__is_vip")
    search_fields = ("layout__name", "zone__name", "table__label")
    autocomplete_fields = ("layout", "table", "zone")
    ordering = ("layout", "z_index", "id")


@admin.register(TableState)
class TableStateAdmin(admin.ModelAdmin):
    list_display = ("layout_table", "state", "open_check_id", "updated_by", "updated_at")
    list_filter = ("state", "layout_table__layout", "layout_table__zone")
    search_fields = ("layout_table__table__label", "layout_table__layout__name", "=open_check_id")
    autocomplete_fields = ("layout_table", "updated_by")
    ordering = ("layout_table__layout", "layout_table__z_index", "layout_table__id")


@admin.register(Check)
class CheckAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "table",
        "status",
        "pos_receipt",
        "pos_receipt_ids_summary",
        "opened_by",
        "closed_by",
        "opened_at",
        "closed_at",
    )
    list_filter = ("status",)
    search_fields = ("=id", "table__label", "=settlement_parts__confirmed_receipt__id")
    autocomplete_fields = ("table", "opened_by", "closed_by")
    readonly_fields = ("pos_receipt_ids_display",)
    ordering = ("-opened_at",)

    @admin.display(description="POS receipts")
    def pos_receipt_ids_summary(self, obj: Check):
        ids = obj.pos_receipt_ids
        if not ids:
            return "-"
        return ", ".join(str(i) for i in ids)

    @admin.display(description="POS receipt IDs (multi)")
    def pos_receipt_ids_display(self, obj: Check):
        ids = obj.pos_receipt_ids
        if not ids:
            return "-"
        links = [
            format_html('<a href="{}">#{}</a>', reverse("admin:pos_posreceipt_change", args=[rid]), rid)
            for rid in ids
        ]
        return format_html(", ".join(["{}"] * len(links)), *links)


class CheckItemInline(admin.TabularInline):
    model = CheckItem
    extra = 0
    autocomplete_fields = ("artikl",)
    fields = (
        "artikl",
        "quantity",
        "unit_price",
        "vat_rate",
        "net_amount",
        "vat_amount",
        "total_amount",
        "round_number",
        "sent_to_bar",
        "line_type",
        "sent_at",
        "note",
    )
    readonly_fields = ("net_amount", "vat_amount", "total_amount", "sent_at")


class SettlementPartInline(admin.TabularInline):
    model = SettlementPart
    extra = 0
    fields = (
        "id",
        "method",
        "amount",
        "tip_amount",
        "total_charged",
        "fiscal_amount",
        "status",
        "provider_ref",
        "external_txn_id",
        "confirmed_receipt",
        "confirmed_by",
        "confirmed_at",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields
    can_delete = False


CheckAdmin.inlines = (CheckItemInline, SettlementPartInline)


@admin.register(CheckItem)
class CheckItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "barion_check",
        "artikl",
        "quantity",
        "unit_price",
        "vat_rate",
        "total_amount",
        "round_number",
        "sent_to_bar",
        "line_type",
        "sent_at",
    )
    list_filter = ("barion_check__status", "sent_to_bar", "line_type")
    search_fields = ("=id", "=barion_check__id", "artikl__name", "artikl__code")
    autocomplete_fields = ("barion_check", "artikl")
    ordering = ("barion_check", "id")


@admin.register(BarionRuntimeMode)
class BarionRuntimeModeAdmin(admin.ModelAdmin):
    list_display = ("active_mode", "updated_by", "updated_at")
    fields = ("active_mode", "updated_by", "updated_at")
    readonly_fields = ("updated_by", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        BarionRuntimeMode.get_solo()
        return super().changelist_view(request, extra_context=extra_context)


class ItemModifierOptionInline(admin.TabularInline):
    model = ItemModifierOption
    extra = 0
    fields = ("name", "code", "is_active", "sort_order")
    ordering = ("sort_order", "name")


class ItemBundleOptionInline(admin.TabularInline):
    model = ItemBundleOption
    extra = 0
    fields = ("artikl", "price_delta", "affects_stock", "stock_ratio", "is_active", "sort_order")
    autocomplete_fields = ("artikl",)
    ordering = ("sort_order", "artikl__name")


@admin.register(ItemModifierGroup)
class ItemModifierGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "type", "selection_mode", "min_select", "max_select", "allow_note", "is_active")
    list_filter = ("is_active", "type", "selection_mode", "allow_note")
    search_fields = ("name", "code")
    ordering = ("sort_order", "name")

    def get_inlines(self, request, obj):
        if obj is None:
            return [ItemModifierOptionInline, ItemBundleOptionInline]
        if obj.type == ItemModifierGroup.Type.BUNDLE:
            return [ItemBundleOptionInline]
        return [ItemModifierOptionInline]


@admin.register(ItemModifierOption)
class ItemModifierOptionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "group", "is_active", "sort_order")
    list_filter = ("is_active", "group")
    search_fields = ("name", "code", "group__name", "group__code")
    autocomplete_fields = ("group",)
    ordering = ("group__name", "sort_order", "name")


@admin.register(ItemBundleOption)
class ItemBundleOptionAdmin(admin.ModelAdmin):
    list_display = ("artikl", "group", "price_delta", "affects_stock", "stock_ratio", "is_active", "sort_order")
    list_filter = ("is_active", "group")
    search_fields = ("artikl__name", "artikl__code", "group__name", "group__code")
    autocomplete_fields = ("artikl", "group")
    ordering = ("group__name", "sort_order", "artikl__name")


class ItemModifierDefaultSelectionInline(admin.TabularInline):
    model = ItemModifierDefaultSelection
    extra = 0
    fields = ("option", "bundle_option", "quantity")
    autocomplete_fields = ("option", "bundle_option")


@admin.register(ItemModifierGroupAssignment)
class ItemModifierGroupAssignmentAdmin(admin.ModelAdmin):
    list_display = ("artikl", "group", "is_active", "is_required", "min_select_override", "max_select_override")
    list_filter = ("is_active", "is_required", "group__type")
    search_fields = ("artikl__name", "artikl__code", "group__name", "group__code")
    autocomplete_fields = ("artikl", "group")
    ordering = ("artikl__name", "group__name")
    inlines = [ItemModifierDefaultSelectionInline]


@admin.register(ItemModifierDefaultSelection)
class ItemModifierDefaultSelectionAdmin(admin.ModelAdmin):
    list_display = ("assignment", "option", "bundle_option", "quantity", "created_at")
    list_filter = ("assignment__group", "assignment__artikl")
    search_fields = (
        "assignment__artikl__name",
        "assignment__group__name",
        "option__name",
        "bundle_option__artikl__name",
    )
    autocomplete_fields = ("assignment", "option", "bundle_option")
    ordering = ("assignment__artikl__name", "assignment__group__name", "id")


@admin.register(CheckItemModifierSelection)
class CheckItemModifierSelectionAdmin(admin.ModelAdmin):
    list_display = ("check_item", "group", "option", "bundle_option", "created_at")
    list_filter = ("group",)
    search_fields = (
        "check_item__id",
        "option__name",
        "option__code",
        "bundle_option__artikl__name",
        "bundle_option__artikl__code",
        "group__name",
    )
    autocomplete_fields = ("check_item", "group", "option")
    ordering = ("check_item", "id")
