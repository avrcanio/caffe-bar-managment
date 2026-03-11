import os
import secrets

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Pos,
    PosProfile,
    PosReceipt,
    PosReceiptItem,
    PosScreen,
    PosScreenItem,
    PosMode,
    PosModeScreen,
    PosDevice,
    PosPrinterInventory,
)
from .fiscal import fiscalize_pos_receipt


class PosProfileForm(forms.ModelForm):
    pin = forms.CharField(required=False, widget=forms.PasswordInput(render_value=True))
    pin_confirm = forms.CharField(required=False, widget=forms.PasswordInput(render_value=True))

    class Meta:
        model = PosProfile
        fields = ("user", "pin", "pin_confirm", "is_registered", "registered_device_id", "registered_at")

    def clean(self):
        cleaned = super().clean()
        pin = cleaned.get("pin") or ""
        pin_confirm = cleaned.get("pin_confirm") or ""
        if pin or pin_confirm:
            if pin != pin_confirm:
                raise forms.ValidationError("PIN i potvrda PIN-a se ne podudaraju.")
            if not pin.isdigit() or len(pin) not in (4, 5, 6):
                raise forms.ValidationError("PIN mora imati 4-6 znamenki.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        pin = self.cleaned_data.get("pin") or ""
        if pin:
            obj.set_pin(pin)
        if commit:
            obj.save()
        return obj


@admin.register(Pos)
class PosAdmin(admin.ModelAdmin):
    list_display = ("external_pos_id", "name", "warehouse", "platform", "is_active")
    list_filter = ("warehouse", "platform", "is_active")
    search_fields = ("name", "external_pos_id")


@admin.register(PosProfile)
class PosProfileAdmin(admin.ModelAdmin):
    form = PosProfileForm
    list_display = ("user", "has_pin", "is_registered", "registered_device_id", "registered_at", "pin_fail_count", "pin_locked_until")
    search_fields = ("user__username", "user__first_name", "user__last_name", "user__email")
    autocomplete_fields = ("user",)
    readonly_fields = ("registered_at",)

    @admin.display(boolean=True, description="PIN")
    def has_pin(self, obj):
        return bool(obj.pin_hash)


@admin.register(PosDevice)
class PosDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "device_id",
        "name",
        "pos",
        "is_active",
        "print_receiver_url",
        "print_receiver_token_masked",
        "receipt_printer",
        "bar_printer",
        "registered_at",
    )
    list_filter = ("is_active", "pos")
    search_fields = ("device_id", "name")
    autocomplete_fields = ("pos", "receipt_printer", "bar_printer")

    @admin.display(description="receiver token")
    def print_receiver_token_masked(self, obj):
        token = str(getattr(obj, "print_receiver_token", "") or "").strip()
        if not token:
            return "-"
        return f"{token[:6]}...{token[-4:]}"

    def save_model(self, request, obj, form, change):
        if not str(obj.print_receiver_token or "").strip():
            obj.print_receiver_token = secrets.token_hex(64)
        super().save_model(request, obj, form, change)


@admin.register(PosPrinterInventory)
class PosPrinterInventoryAdmin(admin.ModelAdmin):
    list_display = ("name", "device", "is_default", "status", "is_active", "last_seen_at")
    list_filter = ("is_active", "is_default", "device__pos")
    search_fields = ("name", "device__device_id", "device__name")
    autocomplete_fields = ("device",)


class PosReceiptItemInline(admin.TabularInline):
    model = PosReceiptItem
    extra = 0
    can_delete = True
    autocomplete_fields = ("artikl",)
    fields = (
        "artikl",
        "quantity",
        "unit_price",
        "product_name",
        "net_amount",
        "vat_amount",
        "total_amount",
    )
    readonly_fields = (
        "product_name",
        "net_amount",
        "vat_amount",
        "total_amount",
    )


class PosScreenItemInline(admin.TabularInline):
    model = PosScreenItem
    extra = 0
    autocomplete_fields = ("artikl",)


@admin.register(PosReceipt)
class PosReceiptAdmin(admin.ModelAdmin):
    class PosReceiptAdminForm(forms.ModelForm):
        class Meta:
            model = PosReceipt
            # Keep this intentionally small so issuing a receipt is as simple as possible.
            fields = (
                "pos",
                "warehouse",
                "operator",
                "office_code",
                "device_code",
                "payment_type",
                "currency",
                "issued_at",
            )

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if not getattr(self.instance, "pk", None):
                self.fields["issued_at"].initial = timezone.now()
                self.fields["office_code"].initial = os.getenv("FISCAL_OFFICE_CODE", "POS1")
                self.fields["device_code"].initial = os.getenv("FISCAL_DEVICE_CODE", "1")

    form = PosReceiptAdminForm
    change_form_template = "admin/pos/posreceipt/change_form.html"

    list_display = (
        "receipt_number",
        "issued_at",
        "office_code",
        "device_code",
        "payment_type",
        "total_amount",
        "status",
        "storno_of",
        "pdf_preview",
    )
    list_filter = ("office_code", "device_code", "payment_type", "status", "issued_on")
    search_fields = ("receipt_number",)
    readonly_fields = ()
    inlines = [PosReceiptItemInline]

    def get_readonly_fields(self, request, obj=None):
        base = (
            "receipt_number",
            "issued_on",
            "status",
            "net_amount",
            "vat_amount",
            "total_amount",
            "pdf_preview",
            "zki",
            "jir",
            "qr_payload",
            "error_message",
            "created_at",
            "updated_at",
        )
        if obj is None:
            return base
        if obj.status in (PosReceipt.Status.FISCALIZED, PosReceipt.Status.STORNO):
            return base + (
                "pos",
                "warehouse",
                "operator",
                "issued_at",
                "office_code",
                "device_code",
                "payment_type",
                "currency",
                "storno_of",
            )
        return base

    def save_model(self, request, obj, form, change):
        # Make "issue receipt" from admin as frictionless as possible:
        # - issued_at defaults to now
        # - issued_on derived from issued_at
        # - receipt_number allocated server-side (per office/device/day)
        # - status defaults to ISSUED
        from .services import _next_receipt_number

        with transaction.atomic():
            if not obj.issued_at:
                obj.issued_at = timezone.now()
            obj.issued_on = timezone.localdate(obj.issued_at)

            if not obj.operator_id:
                obj.operator = request.user

            if not obj.office_code:
                obj.office_code = os.getenv("FISCAL_OFFICE_CODE", "POS1")
            if not obj.device_code:
                obj.device_code = os.getenv("FISCAL_DEVICE_CODE", "1")

            if not obj.warehouse_id and obj.pos_id and getattr(obj.pos, "warehouse_id", None):
                obj.warehouse = obj.pos.warehouse

            if not obj.receipt_number:
                obj.receipt_number = _next_receipt_number(
                    office_code=obj.office_code,
                    device_code=obj.device_code,
                    issued_on=obj.issued_on,
                )

            if not obj.status or obj.status == PosReceipt.Status.DRAFT:
                obj.status = PosReceipt.Status.ISSUED

            super().save_model(request, obj, form, change)

    @admin.display(description="PDF")
    def pdf_preview(self, obj):
        if not obj:
            return "-"
        return format_html(
            '<a href="/api/pos/receipts/{}/print/" target="_blank">Preview</a>',
            obj.id,
        )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        receipt = form.instance
        if receipt:
            receipt.recalc_totals(save=True)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<path:object_id>/fiscalize/",
                self.admin_site.admin_view(self.fiscalize_one_view),
                name="pos_posreceipt_fiscalize",
            ),
        ]
        return custom + urls

    def fiscalize_one_view(self, request: HttpRequest, object_id: str):
        if request.method != "POST":
            messages.error(request, "Neispravan zahtjev (očekivan POST).")
            return HttpResponseRedirect(
                reverse("admin:pos_posreceipt_change", args=[object_id])
            )

        receipt = get_object_or_404(PosReceipt, pk=object_id)
        if not self.has_change_permission(request, receipt):
            messages.error(request, "Nemate prava za fiskalizaciju ovog računa.")
            return HttpResponseRedirect(
                reverse("admin:pos_posreceipt_change", args=[object_id])
            )

        if receipt.status == PosReceipt.Status.FISCALIZED:
            messages.info(request, "Račun je već fiskaliziran.")
            return HttpResponseRedirect(
                reverse("admin:pos_posreceipt_change", args=[object_id])
            )

        try:
            fiscalize_pos_receipt(receipt)
            messages.success(request, "Račun je fiskaliziran.")
        except Exception as exc:
            messages.error(request, f"Fiskalizacija nije uspjela: {exc}")

        return HttpResponseRedirect(
            reverse("admin:pos_posreceipt_change", args=[object_id])
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["pos_receipt_fiscalize_url"] = reverse(
            "admin:pos_posreceipt_fiscalize", args=[object_id]
        )
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    @admin.action(description="Fiskaliziraj POS račune", permissions=["change"])
    def fiscalize_receipts(self, request, queryset):
        created = 0
        skipped = 0
        errors = []

        for receipt in queryset:
            if receipt.status == PosReceipt.Status.FISCALIZED:
                skipped += 1
                continue
            try:
                fiscalize_pos_receipt(receipt)
                created += 1
            except Exception as exc:
                errors.append(f"#{receipt.id}: {exc}")

        self.message_user(
            request,
            f"Fiskalizacija završena. ok={created} skipped={skipped}",
            level=messages.SUCCESS,
        )
        for msg in errors[:20]:
            self.message_user(request, msg, level=messages.ERROR)

    @admin.action(description="Storniraj POS račune", permissions=["change"])
    def storno_receipts(self, request, queryset):
        from .services import create_pos_storno

        created = 0
        skipped = 0
        errors = []

        for receipt in queryset:
            if receipt.status == PosReceipt.Status.STORNO:
                skipped += 1
                continue
            try:
                create_pos_storno(original=receipt, operator=request.user)
                created += 1
            except Exception as exc:
                errors.append(f"#{receipt.id}: {exc}")

        self.message_user(
            request,
            f"Storno završeno. created={created} skipped={skipped}",
            level=messages.SUCCESS,
        )
        for msg in errors[:20]:
            self.message_user(request, msg, level=messages.ERROR)

    actions = ["fiscalize_receipts", "storno_receipts"]


class PosModeScreenInline(admin.TabularInline):
    model = PosModeScreen
    extra = 0
    autocomplete_fields = ("screen",)


@admin.register(PosMode)
class PosModeAdmin(admin.ModelAdmin):
    list_display = ("name", "pos", "warehouse", "is_active", "is_default", "sort_order")
    list_filter = ("is_active", "is_default", "pos", "warehouse")
    search_fields = ("name",)
    inlines = [PosModeScreenInline]


@admin.register(PosScreen)
class PosScreenAdmin(admin.ModelAdmin):
    list_display = ("name", "pos", "warehouse", "is_active", "columns", "rows", "sort_order")
    list_filter = ("is_active", "pos", "warehouse")
    search_fields = ("name",)
    inlines = [PosScreenItemInline]
