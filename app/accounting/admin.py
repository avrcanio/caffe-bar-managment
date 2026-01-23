from django.contrib import admin

from accounting.services import get_single_ledger
from .models import Ledger, Account, Period, JournalEntry, JournalItem


@admin.register(Ledger)
class LedgerAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "oib")
    search_fields = ("name", "oib")

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


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("number", "date", "status", "description", "posted_at", "posted_by")
    list_filter = ("status", "date")
    search_fields = ("description",)
    ordering = ("ledger", "-date", "-number")
    inlines = [JournalItemInline]
    exclude = ("ledger",)

    def save_model(self, request, obj, form, change):
        if not obj.ledger_id:
            obj.ledger = get_single_ledger()
        super().save_model(request, obj, form, change)


@admin.register(JournalItem)
class JournalItemAdmin(admin.ModelAdmin):
    list_display = ("entry", "account", "debit", "credit", "description", "created_at")
    list_filter = ("entry__ledger",)
    search_fields = ("account__code", "account__name", "description")
    autocomplete_fields = ("entry", "account")
