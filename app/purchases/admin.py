from django import forms
from decimal import Decimal
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import SupplierInvoice
from accounting.services import (
    post_purchase_invoice_cash_from_inputs,
    post_purchase_invoice_deferred_from_items,
    post_supplier_invoice_payment,
)
from stock.services import get_stock_accounting_config


class SupplierInvoiceAdminForm(forms.ModelForm):
    class Meta:
        model = SupplierInvoice
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        payment_terms = cleaned.get("payment_terms")
        cash_account = cleaned.get("cash_account")
        ap_account = cleaned.get("ap_account")
        deposit_total = cleaned.get("deposit_total") or 0
        deposit_account = cleaned.get("deposit_account")

        if payment_terms == SupplierInvoice.PaymentTerms.CASH:
            if not cash_account:
                self.add_error("cash_account", "Cash konto je obavezan za gotovinsko placanje.")
        if payment_terms == SupplierInvoice.PaymentTerms.DEFERRED:
            if not ap_account:
                self.add_error("ap_account", "AP konto je obavezan za odgodu placanja.")
        if deposit_total and not deposit_account:
            self.add_error("deposit_account", "Deposit konto je obavezan kad postoji povratna naknada.")

        return cleaned


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    form = SupplierInvoiceAdminForm
    list_display = (
        "id",
        "supplier",
        "invoice_number",
        "invoice_date",
        "total_gross",
        "deposit_total",
        "inputs_count",
        "paid_cash",
        "payment_terms",
        "payment_status",
        "journal_entry",
    )
    list_filter = ("paid_cash", "invoice_date", "supplier")
    search_fields = ("invoice_number", "supplier__name", "supplier__rm_id")
    autocomplete_fields = (
        "supplier",
        "inputs",
        "journal_entry",
        "document_type",
        "cash_account",
        "deposit_account",
        "ap_account",
    )
    filter_horizontal = ("inputs",)
    actions = ["post_supplier_invoice"]

    class Media:
        js = ("purchases/js/supplier_invoice_admin.js",)
        css = {"all": ("purchases/css/supplier_invoice_admin.css",)}

    def save_model(self, request, obj, form, change):
        if change:
            orig = SupplierInvoice.objects.get(pk=obj.pk)
            if obj.payment_terms == obj.PaymentTerms.DEFERRED:
                new_paid = obj.paid_amount or Decimal("0.00")
                old_paid = orig.paid_amount or Decimal("0.00")
                delta = new_paid - old_paid

                if delta < Decimal("0.00"):
                    messages.error(request, "Ne možeš smanjiti plaćeni iznos (paid_amount).")
                    return

                if delta > Decimal("0.00"):
                    if not obj.journal_entry_id or not obj.ap_account_id:
                        messages.error(
                            request,
                            "Račun mora biti proknjižen i imati AP konto prije evidentiranja plaćanja.",
                        )
                        return

                    if not obj.payment_account_id:
                        try:
                            cfg = get_stock_accounting_config()
                        except Exception:
                            cfg = None
                        if cfg and cfg.default_cash_account_id:
                            obj.payment_account = cfg.default_cash_account

                    if not obj.payment_account_id:
                        messages.error(request, "Nedostaje payment konto za evidentiranje plaćanja.")
                        return

                    paid_date = obj.paid_at or timezone.localdate()
                    try:
                        post_supplier_invoice_payment(
                            invoice=obj,
                            amount=delta,
                            payment_account=obj.payment_account,
                            paid_date=paid_date,
                        )
                    except ValidationError as exc:
                        messages.error(request, f"Plaćanje nije evidentirano: {exc}")
                        return
                    messages.success(
                        request,
                        f"Plaćanje evidentirano: {delta} (datum {paid_date}).",
                    )

                    obj.paid_at = paid_date
                    total_payable = (obj.total_gross or Decimal("0.00")) + (obj.deposit_total or Decimal("0.00"))
                    if total_payable > Decimal("0.00") and new_paid >= total_payable:
                        obj.payment_status = obj.PaymentStatus.PAID
                        messages.success(request, "Račun je u potpunosti plaćen (PAID).")
                    else:
                        obj.payment_status = obj.PaymentStatus.PARTIAL
                        messages.info(request, f"Djelomično plaćeno: {new_paid} / {total_payable}")

        # Auto-populate payment status based on terms (gotovina)
        if obj.payment_terms == obj.PaymentTerms.CASH:
            if obj.paid_cash and obj.paid_at:
                obj.payment_status = obj.PaymentStatus.PAID
            else:
                obj.payment_status = obj.PaymentStatus.UNPAID
        super().save_model(request, obj, form, change)

    def inputs_count(self, obj):
        count = obj.inputs.count()
        if not count:
            return "0"
        url = reverse("admin:orders_warehouseinput_changelist")
        return format_html(
            '<a href="{}?supplier_invoices__id__exact={}" title="Račun {}">{}</a>',
            url,
            obj.id,
            obj.invoice_number,
            count,
        )

    inputs_count.short_description = "Primke"

    @admin.action(description="Proknjizi ulazni racun", permissions=["change"])
    def post_supplier_invoice(self, request, queryset):
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
            try:
                cfg = get_stock_accounting_config()
            except Exception:
                cfg = None

            if not invoice.document_type_id:
                failed += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} nema document_type.",
                    level=messages.ERROR,
                )
                continue

            update_fields = []
            if invoice.payment_terms == invoice.PaymentTerms.CASH:
                if not invoice.cash_account_id and cfg and cfg.default_cash_account_id:
                    invoice.cash_account = cfg.default_cash_account
                    update_fields.append("cash_account")
            elif invoice.payment_terms == invoice.PaymentTerms.DEFERRED:
                if not invoice.ap_account_id and invoice.document_type.ap_account_id:
                    invoice.ap_account = invoice.document_type.ap_account
                    update_fields.append("ap_account")

            if invoice.deposit_total > 0 and not invoice.deposit_account_id:
                if cfg and cfg.default_deposit_account_id:
                    invoice.deposit_account = cfg.default_deposit_account
                    update_fields.append("deposit_account")

            if update_fields:
                invoice.save(update_fields=update_fields)

            if invoice.payment_terms == invoice.PaymentTerms.CASH and not invoice.cash_account_id:
                failed += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} nema cash_account za gotovinu.",
                    level=messages.ERROR,
                )
                continue
            if invoice.payment_terms == invoice.PaymentTerms.DEFERRED and not invoice.ap_account_id:
                failed += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} nema ap_account za odgodu.",
                    level=messages.ERROR,
                )
                continue
            if invoice.deposit_total > 0 and not invoice.deposit_account_id:
                failed += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} ima depozit, ali nema deposit_account.",
                    level=messages.ERROR,
                )
                continue

            try:
                if invoice.payment_terms == invoice.PaymentTerms.CASH:
                    entry = post_purchase_invoice_cash_from_inputs(
                        document_type=invoice.document_type,
                        doc_date=invoice.invoice_date,
                        inputs=invoice.inputs.all(),
                        cash_account=invoice.cash_account,
                        deposit_account=invoice.deposit_account,
                        description=f"Ulazni racun {invoice.invoice_number}",
                    )
                    invoice.paid_cash = True
                    invoice.paid_at = invoice.paid_at or timezone.localdate()
                    invoice.payment_status = invoice.PaymentStatus.PAID
                    self.message_user(
                        request,
                        f"Racun {invoice.id} proknjizen kao GOTOVINA.",
                        level=messages.INFO,
                    )
                else:
                    entry = post_purchase_invoice_deferred_from_items(
                        document_type=invoice.document_type,
                        doc_date=invoice.invoice_date,
                        items=invoice.inputs.all(),
                        ap_account=invoice.ap_account,
                        deposit_account=invoice.deposit_account,
                        description=f"Ulazni racun {invoice.invoice_number} (odgoda)",
                    )
                    invoice.payment_status = invoice.PaymentStatus.UNPAID
                    self.message_user(
                        request,
                        f"Racun {invoice.id} proknjizen kao ODGODA.",
                        level=messages.INFO,
                    )
            except ValidationError as exc:
                failed += 1
                self.message_user(request, f"Racun {invoice.id} greska: {exc}", level=messages.ERROR)
                continue

            invoice.journal_entry = entry
            invoice.save(update_fields=["journal_entry", "paid_cash", "paid_at", "payment_status"])
            posted += 1

        if posted:
            self.message_user(request, f"Proknjizeno: {posted}", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Preskoceno: {skipped}", level=messages.WARNING)
        if failed:
            self.message_user(request, f"Greske: {failed}", level=messages.ERROR)

    @admin.action(description="Evidentiraj placanje", permissions=["change"])
    def mark_supplier_invoice_paid(self, request, queryset):
        posted = 0
        skipped = 0
        failed = 0

        amount_input = request.POST.get("amount")
        paid_at_input = request.POST.get("paid_at")
        payment_account_input = request.POST.get("payment_account")

        for invoice in queryset.select_related("payment_account", "ap_account", "document_type"):
            if invoice.payment_terms == invoice.PaymentTerms.CASH:
                skipped += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} je CASH i ne ide kroz evidenciju placanja.",
                    level=messages.WARNING,
                )
                continue
            if invoice.payment_status == invoice.PaymentStatus.PAID:
                skipped += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} je vec placen.",
                    level=messages.WARNING,
                )
                continue
            if not invoice.journal_entry_id or not invoice.ap_account_id:
                failed += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} nema proknjizenu temeljnicu ili ap_account.",
                    level=messages.ERROR,
                )
                continue

            if payment_account_input:
                invoice.payment_account_id = int(payment_account_input)
                invoice.save(update_fields=["payment_account"])

            if not invoice.payment_account_id:
                try:
                    cfg = get_stock_accounting_config()
                except Exception:
                    cfg = None
                if cfg and cfg.default_cash_account_id:
                    invoice.payment_account = cfg.default_cash_account
                    invoice.save(update_fields=["payment_account"])

            if not invoice.payment_account_id:
                failed += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} nema payment_account.",
                    level=messages.ERROR,
                )
                continue

            total_payable = invoice.total_gross + invoice.deposit_total
            already_paid = invoice.paid_amount or Decimal("0.00")
            remaining = total_payable - already_paid
            amount = Decimal(amount_input) if amount_input else remaining
            if amount <= 0:
                failed += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} ima neispravan iznos placanja.",
                    level=messages.ERROR,
                )
                continue
            if amount > remaining:
                failed += 1
                self.message_user(
                    request,
                    f"Racun {invoice.id} iznos prelazi preostalo ({remaining}).",
                    level=messages.ERROR,
                )
                continue

            paid_date = paid_at_input or invoice.paid_at or timezone.localdate()
            try:
                entry = post_supplier_invoice_payment(
                    invoice=invoice,
                    amount=amount,
                    payment_account=invoice.payment_account,
                    paid_date=paid_date,
                )
            except ValidationError as exc:
                failed += 1
                self.message_user(request, f"Racun {invoice.id} greska: {exc}", level=messages.ERROR)
                continue

            invoice.paid_amount = already_paid + amount
            invoice.paid_at = paid_date
            if invoice.paid_amount >= total_payable:
                invoice.payment_status = invoice.PaymentStatus.PAID
            else:
                invoice.payment_status = invoice.PaymentStatus.PARTIAL
            invoice.save(update_fields=["paid_amount", "paid_at", "payment_status"])
            posted += 1

        if posted:
            self.message_user(request, f"Placanje evidentirano: {posted}", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Preskoceno: {skipped}", level=messages.WARNING)
        if failed:
            self.message_user(request, f"Greske: {failed}", level=messages.ERROR)
