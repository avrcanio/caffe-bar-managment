from django import forms
from django.contrib import admin

from .models import Pos, PosProfile


class PosProfileForm(forms.ModelForm):
    pin = forms.CharField(required=False, widget=forms.PasswordInput(render_value=True))
    pin_confirm = forms.CharField(required=False, widget=forms.PasswordInput(render_value=True))

    class Meta:
        model = PosProfile
        fields = ("user", "pin", "pin_confirm")

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
    list_display = ("external_pos_id", "name", "platform", "is_active")
    list_filter = ("platform", "is_active")
    search_fields = ("name", "external_pos_id")


@admin.register(PosProfile)
class PosProfileAdmin(admin.ModelAdmin):
    form = PosProfileForm
    list_display = ("user", "has_pin")
    search_fields = ("user__username", "user__first_name", "user__last_name", "user__email")
    autocomplete_fields = ("user",)

    @admin.display(boolean=True, description="PIN")
    def has_pin(self, obj):
        return bool(obj.pin_hash)
