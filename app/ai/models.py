from django.conf import settings
from django.db import models


class AIQueryLog(models.Model):
    STATUS_OK = "ok"
    STATUS_ERROR = "error"
    STATUS_CHOICES = (
        (STATUS_OK, "OK"),
        (STATUS_ERROR, "Error"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_queries",
    )
    question = models.TextField()
    response_text = models.TextField(blank=True, default="")
    tool_calls = models.JSONField(blank=True, default=list)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OK)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        user_label = self.user.username if self.user else "anon"
        return f"AIQuery {self.id} ({user_label})"

    class Meta:
        verbose_name = "AI upit"
        verbose_name_plural = "AI upiti"
        ordering = ["-created_at"]
