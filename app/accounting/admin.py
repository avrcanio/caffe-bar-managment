from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone

from accounting.services import get_single_ledger
from .models import Ledger, Account, Period, JournalEntry, JournalItem


@admin.register(Ledger)
class LedgerAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "oib", "company_profile")
    search_fields = ("name", "oib", "company_profile__name", "company_profile__oib")

    def has_add_permission(self, request):
        return not Ledger.objects.exists()


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "type", "normal_side", "is_postable", "is_active", "parent")
    list_filter = ("type", "normal_side", "is_postable", "is_active")
    search_fields = ("code", "name")
    autocomplete_fields = ("parent",)
    ordering = ("ledger", "code")
    exclude = ("ledger",)

    def save_model(self, request, obj, form, change):
        if not obj.ledger_id:
            obj.ledger = get_single_ledger()
        super().save_model(request, obj, form, change)


@admin.register(Period)
class PeriodAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_closed", "closed_at")
    list_filter = ("is_closed",)
    search_fields = ("name",)
    ordering = ("ledger", "-start_date")
    exclude = ("ledger",)

    def save_model(self, request, obj, form, change):
        if not obj.ledger_id:
            obj.ledger = get_single_ledger()
        super().save_model(request, obj, form, change)


class JournalItemInline(admin.TabularInline):
    model = JournalItem
    extra = 0
    autocomplete_fields = ("account",)


@admin.action(description="Storniraj oznacene temeljnice")
def reverse_entries(modeladmin, request, queryset):
    reversed_count = 0
    errors = 0

    for entry in queryset:
        try:
            entry.reverse(reverse_date=timezone.localdate(), user=request.user)
            reversed_count += 1
        except ValidationError as e:
            errors += 1
            messages.error(request, f"#{entry.number}: {e}")
        except Exception as e:
            errors += 1
            messages.error(request, f"#{entry.number}: Neocekivana greska: {e}")

    if reversed_count:
        messages.success(request, f"Stornirano: {reversed_count}")
    if errors and not reversed_count:
        messages.warning(request, f"Nije stornirano nista. Gresaka: {errors}")


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "date",
        "status",
        "description",
        "is_reversed",
        "reverses_link",
        "reversal_link",
        "posted_at",
        "posted_by",
    )
    list_filter = ("status", "date")
    search_fields = ("description",)
    ordering = ("ledger", "-date", "-number")
    inlines = [JournalItemInline]
    exclude = ("ledger",)
    actions = [reverse_entries]

    def save_model(self, request, obj, form, change):
        if not obj.ledger_id:
            obj.ledger = get_single_ledger()
        super().save_model(request, obj, form, change)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def reversal_link(self, obj):
        if hasattr(obj, "reversal"):
            url = reverse("admin:accounting_journalentry_change", args=[obj.reversal.id])
            return format_html("<a href=\"{}\">#{} ({})</a>", url, obj.reversal.number, obj.reversal.date)
        return ""

    reversal_link.short_description = "Storno"

    def reverses_link(self, obj):
        if obj.reversed_entry_id:
            url = reverse("admin:accounting_journalentry_change", args=[obj.reversed_entry_id])
            return format_html(
                "<a href=\"{}\">#{} ({})</a>",
                url,
                obj.reversed_entry.number,
                obj.reversed_entry.date,
            )
        return ""

    reverses_link.short_description = "Stornira"

    def is_reversed(self, obj):
        return hasattr(obj, "reversal")

    is_reversed.boolean = True
    is_reversed.short_description = "Stornirano"


@admin.register(JournalItem)
class JournalItemAdmin(admin.ModelAdmin):
    list_display = ("entry", "account", "debit", "credit", "description", "created_at")
    list_filter = ("entry__ledger",)
    search_fields = ("account__code", "account__name", "description")
    autocomplete_fields = ("entry", "account")
