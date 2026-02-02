from django.contrib import admin

from .models import AIQueryLog


@admin.register(AIQueryLog)
class AIQueryLogAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("question", "response_text", "error_message")
    readonly_fields = (
        "user",
        "question",
        "response_text",
        "tool_calls",
        "status",
        "error_message",
        "created_at",
    )
