from django.contrib import admin

from .models import SupplierInvoice


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "supplier", "invoice_number", "invoice_date", "paid_cash", "journal_entry")
    list_filter = ("paid_cash", "invoice_date", "supplier")
    search_fields = ("invoice_number", "supplier__name", "supplier__rm_id")
    autocomplete_fields = ("supplier", "inputs", "journal_entry")
    filter_horizontal = ("inputs",)
