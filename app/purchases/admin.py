from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import SupplierInvoice
from accounting.services import post_purchase_invoice_cash_from_inputs
from stock.services import get_stock_accounting_config


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "supplier",
        "invoice_number",
        "invoice_date",
        "total_gross",
        "deposit_total",
        "paid_cash",
        "journal_entry",
    )
    list_filter = ("paid_cash", "invoice_date", "supplier")
    search_fields = ("invoice_number", "supplier__name", "supplier__rm_id")
    autocomplete_fields = ("supplier", "inputs", "journal_entry", "document_type", "cash_account", "deposit_account")
    filter_horizontal = ("inputs",)
    actions = ["post_supplier_invoice_cash"]

    @admin.action(description="Proknjizi ulazni racun (gotovina)", permissions=["change"])
    def post_supplier_invoice_cash(self, request, queryset):
        posted = 0
        skipped = 0
        failed = 0

        for invoice in queryset.select_related("document_type", "cash_account", "deposit_account"):
            if invoice.journal_entry_id:
                skipped += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} preskocen: vec proknjizen.",
                    level=messages.WARNING,
                )
                continue
            if not invoice.document_type_id or not invoice.cash_account_id:
                try:
                    cfg = get_stock_accounting_config()
                except Exception:
                    cfg = None

                update_fields = []
                if not invoice.cash_account_id and cfg and cfg.default_cash_account_id:
                    invoice.cash_account = cfg.default_cash_account
                    update_fields.append("cash_account")
                if invoice.deposit_total > 0 and not invoice.deposit_account_id:
                    if cfg and cfg.default_deposit_account_id:
                        invoice.deposit_account = cfg.default_deposit_account
                        update_fields.append("deposit_account")

                if update_fields:
                    invoice.save(update_fields=update_fields)

            if not invoice.document_type_id or not invoice.cash_account_id:
                failed += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} nema document_type ili cash_account.",
                    level=messages.ERROR,
                )
                continue

            try:
                entry = post_purchase_invoice_cash_from_inputs(
                    document_type=invoice.document_type,
                    doc_date=invoice.invoice_date,
                    inputs=invoice.inputs.all(),
                    cash_account=invoice.cash_account,
                    deposit_account=invoice.deposit_account,
                    description=f"Ulazni racun {invoice.invoice_number}",
                )
            except ValidationError as exc:
                failed += 1
                self.message_user(request, f"Racun {invoice.id} greska: {exc}", level=messages.ERROR)
                continue

            invoice.journal_entry = entry
            invoice.paid_cash = True
            invoice.paid_at = invoice.paid_at or timezone.localdate()
            invoice.save(update_fields=["journal_entry", "paid_cash", "paid_at"])
            posted += 1

        if posted:
            self.message_user(request, f"Proknjizeno: {posted}", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Preskoceno: {skipped}", level=messages.WARNING)
        if failed:
            self.message_user(request, f"Greske: {failed}", level=messages.ERROR)
