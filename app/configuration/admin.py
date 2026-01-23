from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.db import transaction

from accounting.services import get_single_ledger
from artikli.remaris_connector import RemarisConnector
from .models import (
    Account,
    CompanyProfile,
    DocumentType,
    OrderEmailTemplate,
    PaymentType,
    PointOfIssueData,
    RemarisCookie,
    TaxGroup,
)


@admin.action(description="Import mjesta izdavanja from Remaris", permissions=["change"])
def import_point_of_issue_from_remaris(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    payload = {
        "dataSource": "pointOfIssueDS",
        "operationType": "fetch",
        "operationId": "pointOfIssueDS_fetch",
        "textMatchStyle": "exact",
        "componentId": "(cacheAllData fetch)",
        "oldValues": None,
        "data": None,
    }

    response = connector.post_json(
        "Product/PointOfIssueData?isc_dataFormat=json",
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

            _, was_created = PointOfIssueData.objects.update_or_create(
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


@admin.register(PointOfIssueData)
class PointOfIssueDataAdmin(admin.ModelAdmin):
    list_display = ("rm_id", "name")
    search_fields = ("rm_id", "name")
    actions = [import_point_of_issue_from_remaris]

    def response_action(self, request, queryset):
        action = request.POST.get("action")
        if action == "import_point_of_issue_from_remaris":
            func = self.get_actions(request)[action][0]
            return func(self, request, PointOfIssueData.objects.all())
        return super().response_action(request, queryset)


@admin.register(RemarisCookie)
class RemarisCookieAdmin(admin.ModelAdmin):
    list_display = ("updated_at",)
    readonly_fields = ("updated_at",)


@admin.register(TaxGroup)
class TaxGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "rate", "code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")


@admin.action(description="Import payment types from Remaris", permissions=["change"])
def import_payment_types_from_remaris(modeladmin, request, queryset):
    created, updated, skipped = _sync_payment_types_from_remaris()
    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


def _sync_payment_types_from_remaris():
    connector = RemarisConnector()
    connector.login()

    payload = {
        "sort": "Name",
        "page": 0,
        "perpage": None,
        "AppContext": {
            "OrganizationId": 2,
            "LocationId": 5,
            "WarehouseId": None,
            "RegimeId": None,
            "PriceListId": None,
            "ContactId": None,
            "DiscountId": None,
            "SalesGroupId": None,
            "ProductTags": None,
            "FiscalPaymentTypes": None,
            "SelectedCustomerIds": None,
            "PosId": None,
            "ShowFilter": None,
            "ShowDateRange": None,
            "DateFrom": None,
            "DateTo": None,
            "OnDate": None,
            "Year": None,
            "ReportYear": None,
            "ReportMonth": None,
            "CustomerId": None,
            "WaiterId": None,
            "PdvIraReportType": None,
            "TableTotalType": 0,
            "IncludeInvoices": False,
            "IncludeDeliveryNotes": False,
            "IncludeArchivedTables": False,
            "IncludeOpenOrders": False,
            "IncludeHotelOrders": False,
            "GroupByDiscountValue": False,
            "Billed": False,
            "NonBilled": False,
            "ShowInitialCustomer": False,
            "IncludeCanceled": False,
            "IncludeCancels": False,
            "WithBuyerOnly": False,
            "WithDiscountOnly": False,
            "LoginLogoutInvoice": 0,
            "PDV2014Margin": False,
            "AllBaseGroups": True,
            "ProductBaseGroupIds": None,
            "AllWarehouseOperationDocumentTypes": True,
            "WarehouseOperationDocumentTypes": None,
            "ProductId": None,
            "OrderCancelReasonId": None,
            "PointOfIssueId": None,
            "PaymentMethodId": None,
            "SupplyerId": None,
            "HotelGuestOrders": False,
            "HotelReceptionOrders": False,
            "NoGrouping": False,
            "NoProduction": False,
            "TableNumber": None,
            "TextSearch": None,
            "ByPaymentFilter": 0,
            "NotPayedByDate": None,
            "Currency": None,
            "IncludePivot": False,
        },
    }

    response = connector.post_json(
        "PaymentMethod/GetPaymentMethods",
        payload,
        referer_path="/PaymentMethod",
    )

    data = response.get("response", {}).get("data", response.get("data", []))

    created = 0
    updated = 0
    skipped = 0

    for item in data or []:
        rm_id = item.get("Id") or item.get("id")
        name = item.get("Name") or item.get("name")
        if rm_id is None or not name:
            skipped += 1
            continue

        code = item.get("Code") or item.get("code") or ""
        active = item.get("Active")
        if active is None:
            active = True

        _, was_created = PaymentType.objects.update_or_create(
            rm_id=rm_id,
            defaults={
                "name": name,
                "code": code,
                "is_active": bool(active),
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1

    return created, updated, skipped


@admin.register(PaymentType)
class PaymentTypeAdmin(admin.ModelAdmin):
    change_list_template = "admin/configuration/paymenttype/change_list.html"
    list_display = ("rm_id", "name", "code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("rm_id", "name", "code")
    actions = [import_payment_types_from_remaris]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "sync-remaris/",
                self.admin_site.admin_view(self.sync_remaris),
                name="configuration_paymenttype_sync_remaris",
            ),
        ]
        return custom_urls + urls

    def sync_remaris(self, request):
        created, updated, skipped = _sync_payment_types_from_remaris()
        self.message_user(
            request,
            f"Import complete. created={created} updated={updated} skipped={skipped}",
            level=messages.SUCCESS,
        )
        return HttpResponseRedirect(
            reverse("admin:configuration_paymenttype_changelist")
        )

    def response_action(self, request, queryset):
        action = request.POST.get("action")
        if action == "import_payment_types_from_remaris":
            func = self.get_actions(request)[action][0]
            return func(self, request, PaymentType.objects.all())
        return super().response_action(request, queryset)


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "oib", "email", "phone")
    search_fields = ("name", "oib", "email", "phone", "city")


@admin.register(OrderEmailTemplate)
class OrderEmailTemplateAdmin(admin.ModelAdmin):
    list_display = ("subject_template", "active")
    list_filter = ("active",)


@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "ar_code",
        "ap_code",
        "vat_output_code",
        "vat_input_code",
        "revenue_code",
        "expense_code",
    )
    list_filter = ("direction", "is_active")
    search_fields = ("name", "code")
    ordering = ("sort_order", "name")
    autocomplete_fields = (
        "stock_account",
        "counterpart_account",
        "ar_account",
        "ap_account",
        "vat_output_account",
        "vat_input_account",
        "revenue_account",
        "expense_account",
    )
    exclude = ("ledger",)

    def ar_code(self, obj):
        return getattr(obj.ar_account, "code", "")

    ar_code.short_description = "AR"

    def ap_code(self, obj):
        return getattr(obj.ap_account, "code", "")

    ap_code.short_description = "AP"

    def vat_output_code(self, obj):
        return getattr(obj.vat_output_account, "code", "")

    vat_output_code.short_description = "PDV izlaz"

    def vat_input_code(self, obj):
        return getattr(obj.vat_input_account, "code", "")

    vat_input_code.short_description = "PDV ulaz"

    def revenue_code(self, obj):
        return getattr(obj.revenue_account, "code", "")

    revenue_code.short_description = "Prihod"

    def expense_code(self, obj):
        return getattr(obj.expense_account, "code", "")

    expense_code.short_description = "Rashod"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        fk_names = {
            "ar_account",
            "ap_account",
            "vat_output_account",
            "vat_input_account",
            "revenue_account",
            "expense_account",
        }

        obj_id = request.resolver_match.kwargs.get("object_id")
        if db_field.name in fk_names and obj_id:
            try:
                obj = DocumentType.objects.get(pk=obj_id)
                if obj.ledger_id:
                    kwargs["queryset"] = Account.objects.filter(
                        ledger=obj.ledger,
                        is_postable=True,
                        is_active=True,
                    ).order_by("code")
            except DocumentType.DoesNotExist:
                pass

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not obj.ledger_id:
            obj.ledger = get_single_ledger()
        super().save_model(request, obj, form, change)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
