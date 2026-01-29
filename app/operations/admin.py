from django.contrib import admin

from .models import Shift, ShiftCashCount


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "opened_at", "closed_at", "opened_by", "closed_by", "location")
    list_filter = ("status",)
    search_fields = ("id", "location", "opened_by__username", "closed_by__username")


@admin.register(ShiftCashCount)
class ShiftCashCountAdmin(admin.ModelAdmin):
    list_display = ("id", "shift", "kind", "expected_amount", "counted_amount", "difference_amount", "created_at")
    list_filter = ("kind",)
    search_fields = ("shift__id", "created_by__username")
