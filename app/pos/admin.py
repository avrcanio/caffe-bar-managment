from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

from .models import Pos, PosProfile, PosReceipt, PosReceiptItem, PosScreen, PosScreenItem, PosMode, PosModeScreen, PosDevice
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
    list_display = ("device_id", "name", "pos", "is_active", "registered_at")
    list_filter = ("is_active", "pos")
    search_fields = ("device_id", "name")
    autocomplete_fields = ("pos",)


class PosReceiptItemInline(admin.TabularInline):
    model = PosReceiptItem
    extra = 0
    can_delete = True
    autocomplete_fields = ("artikl",)
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
                "receipt_number",
                "issued_on",
                "issued_at",
                "office_code",
                "device_code",
                "payment_type",
                "currency",
                "status",
                "storno_of",
            )
        return base

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
