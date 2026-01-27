import time

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.db import models, transaction
from django.utils.html import format_html
from mptt.admin import DraggableMPTTAdmin, TreeRelatedFieldListFilter

from .models import (
    Artikl,
    ArtiklDetail,
    BaseGroupData,
    Deposit,
    DrinkCategory,
    KeyboardGroupData,
    Normativ,
    NormativItem,
    SalesGroupData,
    UnitOfMeasureData,
)
from .remaris_parser import parse_bool, parse_decimal, parse_hidden_inputs, parse_int
from .remaris_connector import RemarisConnector


@admin.action(description="Import artikli from Remaris", permissions=["change"])
def import_artikli_from_remaris(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    created = 0
    updated = 0
    skipped = 0

    with transaction.atomic():
        for artikl in queryset:
            html = connector.get_html(
                _detail_path(artikl.rm_id),
                referer_path="/Product",
            )
            inputs = parse_hidden_inputs(html)
            if not inputs:
                skipped += 1
                continue

            rm_id = parse_int(inputs.get("Id")) or artikl.rm_id
            name = inputs.get("Name") or artikl.name
            code = inputs.get("Code") or artikl.code
            obj, was_created = Artikl.objects.update_or_create(
                rm_id=rm_id,
                defaults={"name": name, "code": code},
            )
            if was_created:
                created += 1
            else:
                updated += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


def _detail_defaults(artikl, inputs):
    return {
        "artikl": artikl,
        "rm_id": parse_int(inputs.get("Id")) or artikl.rm_id,
        "name": inputs.get("Name") or artikl.name,
        "code": inputs.get("Code") or artikl.code,
        "barcode": inputs.get("BarCode", ""),
        "description": inputs.get("Description", ""),
        "external_code": inputs.get("ExternalCode", ""),
        "base_group_id": parse_int(inputs.get("BaseGroupId")),
        "sales_group_id": parse_int(inputs.get("SalesGroupId")),
        "keyboard_group_id": parse_int(inputs.get("KeyboardGroupId")),
        "unit_of_measure_id": parse_int(inputs.get("UnitOfMeasureId")),
        "standard_uom_id": parse_int(inputs.get("StandardUOMId")),
        "standard_uom_name": inputs.get("StandardUOMDisplayName", ""),
        "quantity_in_suom": parse_decimal(inputs.get("QuantityInSUOM")),
        "spillage_allowance": parse_decimal(inputs.get("SpillageAllowance")),
        "ordinal": parse_decimal(inputs.get("Ordinal")),
        "point_of_issue_id": parse_int(inputs.get("PointOfIssueId")),
        "is_for_sale": parse_bool(inputs.get("IsForSale")),
        "is_purchased": parse_bool(inputs.get("IsPurchased")),
        "is_product": parse_bool(inputs.get("IsProduct")),
        "is_commodity": parse_bool(inputs.get("IsCommodity")),
        "is_immaterial": parse_bool(inputs.get("IsImmaterial")),
        "is_used_on_pos": parse_bool(inputs.get("IsUsedOnPOS")),
        "is_package": parse_bool(inputs.get("IsPackage")),
        "is_negative_quantity_allowed": parse_bool(inputs.get("IsNegativeQuantityAllowed")),
        "no_discount": parse_bool(inputs.get("NoDiscount")),
        "has_return_fee": parse_bool(inputs.get("HasReturnFee")),
        "active": parse_bool(inputs.get("Active")),
        "print_on_pricelist": parse_bool(inputs.get("PrintOnPricelist")),
    }


def _detail_path(rm_id):
    return f"Product/Details/{rm_id}?_={int(time.time() * 1000)}"


@admin.action(description="Import artikl details from Remaris", permissions=["change"])
def import_artikl_details_from_remaris(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    created = 0
    updated = 0
    skipped = 0

    with transaction.atomic():
        for artikl in queryset:
            html = connector.get_html(
                _detail_path(artikl.rm_id),
                referer_path="/Product",
            )
            inputs = parse_hidden_inputs(html)
            if not inputs:
                skipped += 1
                continue

            defaults = _detail_defaults(artikl, inputs)
            _, was_created = ArtiklDetail.objects.update_or_create(
                rm_id=defaults["rm_id"],
                defaults=defaults,
            )
            if was_created:
                created += 1
            else:
                updated += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


@admin.register(Artikl)
class ArtiklAdmin(admin.ModelAdmin):
    list_display = (
        "rm_id",
        "code",
        "name",
        "deposit",
        "tax_group",
        "pnp_category",
        "drink_category",
        "is_sellable",
        "is_stock_item",
        "image_preview",
    )
    search_fields = ("rm_id", "code", "name")
    actions = [import_artikli_from_remaris, import_artikl_details_from_remaris]
    inlines = []
    readonly_fields = ("image_preview", "normativ_link")
    list_filter = (("drink_category", TreeRelatedFieldListFilter), "is_sellable", "is_stock_item")
    fields = (
        "rm_id",
        "code",
        "name",
        "deposit",
        "tax_group",
        "pnp_category",
        "drink_category",
        "is_sellable",
        "is_stock_item",
        "image",
        "image_preview",
        "normativ_link",
        "note",
    )

    def image_preview(self, obj):
        if not obj.image:
            return "—"
        return format_html('<img src="{}" style="max-height: 160px;" />', obj.image.url)

    image_preview.short_description = "Preview"

    def normativ_link(self, obj):
        if not obj or not obj.pk:
            return "—"
        if hasattr(obj, "normativ") and obj.normativ_id:
            url = reverse("admin:artikli_normativ_change", args=[obj.normativ_id])
            return format_html('<a href="{}" class="button">Uredi normativ</a>', url)
        url = reverse("admin:artikli_normativ_add")
        return format_html(
            '<a href="{}?product={}" class="button">Dodaj normativ</a>',
            url,
            obj.pk,
        )

    normativ_link.short_description = "Normativ"


class ArtiklDetailInline(admin.StackedInline):
    model = ArtiklDetail
    extra = 0
    can_delete = False
    fk_name = "artikl"
    fields = (
        "rm_id",
        "code",
        "name",
        "barcode",
        "description",
        "external_code",
        "base_group",
        "sales_group",
        "keyboard_group",
        "unit_of_measure",
        "standard_uom_id",
        "standard_uom_name",
        "quantity_in_suom",
        "spillage_allowance",
        "ordinal",
        "point_of_issue",
        "is_for_sale",
        "is_purchased",
        "is_product",
        "is_commodity",
        "is_immaterial",
        "is_used_on_pos",
        "is_package",
        "is_negative_quantity_allowed",
        "no_discount",
        "has_return_fee",
        "active",
        "print_on_pricelist",
    )
    readonly_fields = fields


@admin.register(ArtiklDetail)
class ArtiklDetailAdmin(admin.ModelAdmin):
    list_display = ("rm_id", "code", "name", "base_group", "sales_group", "keyboard_group")
    search_fields = ("rm_id", "code", "name")


class NormativInline(admin.StackedInline):
    model = Normativ
    fk_name = "product"
    extra = 0
    max_num = 1
    fields = ("is_active",)
    show_change_link = True


ArtiklAdmin.inlines = [NormativInline, ArtiklDetailInline]


class NormativItemInline(admin.TabularInline):
    model = NormativItem
    extra = 0
    autocomplete_fields = ("ingredient",)


@admin.register(Normativ)
class NormativAdmin(admin.ModelAdmin):
    list_display = ("product", "is_active")
    list_filter = ("is_active",)
    search_fields = ("product__name", "product__code")
    autocomplete_fields = ("product",)
    inlines = [NormativItemInline]


@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ("id", "amount_eur")
    search_fields = ("id",)
    formfield_overrides = {
        models.DecimalField: {"localize": True},
    }


@admin.register(DrinkCategory)
class DrinkCategoryAdmin(DraggableMPTTAdmin):
    list_display = ("tree_actions", "indented_title", "parent", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.action(description="Import unit measures from Remaris", permissions=["change"])
def import_unit_measures_from_remaris(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    payload = {
        "dataSource": "unitOfMeasureDS",
        "operationType": "fetch",
        "operationId": "unitOfMeasureDS_fetch",
        "textMatchStyle": "exact",
        "componentId": "(cacheAllData fetch)",
        "oldValues": None,
        "data": None,
    }

    response = connector.post_json(
        "Product/UnitOfMeasureData?isc_dataFormat=json",
        payload,
        referer_path="/Product",
    )

    data = response.get("response", {}).get("data", [])

    created = 0
    updated = 0
    skipped = 0

    with transaction.atomic():
        for item in data:
            rm_id = item.get("id")
            name = item.get("name")
            if rm_id is None or name is None:
                skipped += 1
                continue

            _, was_created = UnitOfMeasureData.objects.update_or_create(
                rm_id=rm_id,
                defaults={"name": name},
            )
            if was_created:
                created += 1
            else:
                updated += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


@admin.register(UnitOfMeasureData)
class UnitOfMeasureDataAdmin(admin.ModelAdmin):
    change_list_template = "admin/artikli/unitofmeasuredata/change_list.html"
    list_display = ("rm_id", "name")
    search_fields = ("rm_id", "name")
    actions = [import_unit_measures_from_remaris]

    def response_action(self, request, queryset):
        action = request.POST.get("action")
        if action == "import_unit_measures_from_remaris":
            func = self.get_actions(request)[action][0]
            return func(self, request, UnitOfMeasureData.objects.all())
        return super().response_action(request, queryset)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "sync-remaris/",
                self.admin_site.admin_view(self.sync_remaris),
                name="artikli_unitofmeasuredata_sync_remaris",
            ),
        ]
        return custom_urls + urls

    def sync_remaris(self, request):
        import_unit_measures_from_remaris(self, request, UnitOfMeasureData.objects.all())
        return HttpResponseRedirect(
            reverse("admin:artikli_unitofmeasuredata_changelist")
        )


@admin.action(description="Import sales groups from Remaris", permissions=["change"])
def import_sales_groups_from_remaris(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    payload = {
        "dataSource": "salesGroupDS",
        "operationType": "fetch",
        "operationId": "salesGroupDS_fetch",
        "textMatchStyle": "exact",
        "componentId": "(cacheAllData fetch)",
        "oldValues": None,
        "data": None,
    }

    response = connector.post_json(
        "Product/SalesGroupData?isc_dataFormat=json",
        payload,
        referer_path="/Product",
    )

    data = response.get("response", {}).get("data", [])

    created = 0
    updated = 0
    skipped = 0

    with transaction.atomic():
        for item in data:
            rm_id = item.get("id")
            name = item.get("name")
            if rm_id is None or name is None:
                skipped += 1
                continue

            _, was_created = SalesGroupData.objects.update_or_create(
                rm_id=rm_id,
                defaults={"name": name},
            )
            if was_created:
                created += 1
            else:
                updated += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


@admin.register(SalesGroupData)
class SalesGroupDataAdmin(admin.ModelAdmin):
    list_display = ("rm_id", "name")
    search_fields = ("rm_id", "name")
    actions = [import_sales_groups_from_remaris]

    def response_action(self, request, queryset):
        action = request.POST.get("action")
        if action == "import_sales_groups_from_remaris":
            func = self.get_actions(request)[action][0]
            return func(self, request, SalesGroupData.objects.all())
        return super().response_action(request, queryset)


@admin.action(description="Import keyboard groups from Remaris", permissions=["change"])
def import_keyboard_groups_from_remaris(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    payload = {
        "dataSource": "keyboardGroupDS",
        "operationType": "fetch",
        "operationId": "keyboardGroupDS_fetch",
        "textMatchStyle": "exact",
        "componentId": "(cacheAllData fetch)",
        "oldValues": None,
        "data": None,
    }

    response = connector.post_json(
        "Product/KeyboardGroupData?isc_dataFormat=json",
        payload,
        referer_path="/Product",
    )

    data = response.get("response", {}).get("data", [])

    created = 0
    updated = 0
    skipped = 0

    with transaction.atomic():
        for item in data:
            rm_id = item.get("id")
            name = item.get("name")
            if rm_id is None or name is None:
                skipped += 1
                continue

            _, was_created = KeyboardGroupData.objects.update_or_create(
                rm_id=rm_id,
                defaults={"name": name},
            )
            if was_created:
                created += 1
            else:
                updated += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


@admin.register(KeyboardGroupData)
class KeyboardGroupDataAdmin(admin.ModelAdmin):
    list_display = ("rm_id", "name")
    search_fields = ("rm_id", "name")
    actions = [import_keyboard_groups_from_remaris]

    def response_action(self, request, queryset):
        action = request.POST.get("action")
        if action == "import_keyboard_groups_from_remaris":
            func = self.get_actions(request)[action][0]
            return func(self, request, KeyboardGroupData.objects.all())
        return super().response_action(request, queryset)


@admin.action(description="Import base groups from Remaris", permissions=["change"])
def import_base_groups_from_remaris(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    payload = {
        "dataSource": "baseGroupDS",
        "operationType": "fetch",
        "operationId": "baseGroupDS_fetch",
        "textMatchStyle": "exact",
        "componentId": "(cacheAllData fetch)",
        "oldValues": None,
        "data": None,
    }

    response = connector.post_json(
        "Product/BaseGroupData?isc_dataFormat=json",
        payload,
        referer_path="/Product",
    )

    data = response.get("response", {}).get("data", [])

    created = 0
    updated = 0
    skipped = 0

    with transaction.atomic():
        for item in data:
            rm_id = item.get("id")
            name = item.get("name")
            if rm_id is None or name is None:
                skipped += 1
                continue

            _, was_created = BaseGroupData.objects.update_or_create(
                rm_id=rm_id,
                defaults={"name": name},
            )
            if was_created:
                created += 1
            else:
                updated += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


@admin.register(BaseGroupData)
class BaseGroupDataAdmin(admin.ModelAdmin):
    list_display = ("rm_id", "name")
    search_fields = ("rm_id", "name")
    actions = [import_base_groups_from_remaris]

    def response_action(self, request, queryset):
        action = request.POST.get("action")
        if action == "import_base_groups_from_remaris":
            func = self.get_actions(request)[action][0]
            return func(self, request, BaseGroupData.objects.all())
        return super().response_action(request, queryset)

# Register your models here.
