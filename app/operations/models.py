from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Shift(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Otvoreno"
        CLOSED = "closed", "Zatvoreno"

    location = models.CharField(max_length=255, blank=True, default="")
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="opened_shifts",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="closed_shifts",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    def __str__(self) -> str:
        location = self.location or "Lokacija ?"
        return f"{location} @ {self.opened_at:%Y-%m-%d %H:%M}"

    class Meta:
        verbose_name = "Smjena"
        verbose_name_plural = "Smjene"


class ShiftCashCount(models.Model):
    class Kind(models.TextChoices):
        OPENING = "OPENING", "Otvaranje"
        CLOSING = "CLOSING", "Zatvaranje"

    shift = models.ForeignKey(
        "operations.Shift",
        on_delete=models.CASCADE,
        related_name="cash_counts",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2)
    counted_amount = models.DecimalField(max_digits=12, decimal_places=2)
    difference_amount = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shift_cash_counts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self) -> None:
        super().clean()
        if self.difference_amount is not None and self.difference_amount != Decimal("0.00"):
            if not (self.note or "").strip():
                raise ValidationError({"note": "Napomena je obavezna kada postoji razlika."})

    def save(self, *args, **kwargs):
        if self.expected_amount is not None and self.counted_amount is not None:
            self.difference_amount = self.counted_amount - self.expected_amount
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.shift_id} {self.kind} {self.counted_amount}"

    class Meta:
        verbose_name = "Prebrojavanje blagajne"
        verbose_name_plural = "Prebrojavanja blagajne"
        ordering = ["-created_at"]
