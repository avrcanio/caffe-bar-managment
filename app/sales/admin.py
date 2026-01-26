from django.contrib import admin, messages
from django.utils import timezone

from sales.models import SalesInvoice, SalesInvoiceItem
from sales.remaris_importer import import_sales_invoices, load_import_defaults


@admin.action(description="Import promet (Remaris)", permissions=["change"])
def import_sales_invoices_action(modeladmin, request, queryset):
    date_from = request.GET.get("from")
    date_to = request.GET.get("to")

    if date_from:
        date_from = timezone.datetime.fromisoformat(date_from).date()
    else:
        date_from = timezone.localdate()

    if date_to:
        date_to = timezone.datetime.fromisoformat(date_to).date()
    else:
        date_to = date_from

    defaults = load_import_defaults()
    created, updated, skipped = import_sales_invoices(
        date_from=date_from,
        date_to=date_to,
        **defaults,
    )

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


@admin.register(SalesInvoice)
class SalesInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "rm_number",
        "issued_on",
        "issued_at",
        "location_name",
        "waiter_name",
        "buyer_name",
        "total_amount",
        "currency",
    )
    search_fields = ("rm_number", "location_name", "waiter_name", "buyer_name")
    actions = [import_sales_invoices_action]


@admin.register(SalesInvoiceItem)
class SalesInvoiceItemAdmin(admin.ModelAdmin):
    list_display = ("invoice", "product_name", "quantity", "amount")
    search_fields = ("product_name", "invoice__rm_number")
