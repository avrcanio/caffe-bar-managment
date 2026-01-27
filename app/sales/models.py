from decimal import Decimal

from django.db import models


class SalesInvoice(models.Model):
    rm_number = models.IntegerField(unique=True)
    issued_on = models.DateField()
    issued_at = models.DateTimeField()
    location_name = models.CharField(max_length=255, blank=True, default="")
    buyer_name = models.CharField(max_length=255, blank=True, default="")
    waiter_name = models.CharField(max_length=255, blank=True, default="")
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    currency = models.CharField(max_length=10, blank=True, default="")
    organization_id = models.IntegerField(null=True, blank=True)
    location_id = models.IntegerField(null=True, blank=True)
    pos_id = models.IntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Racun {self.rm_number} ({self.issued_on:%Y-%m-%d})"

    class Meta:
        verbose_name = "Racun (promet)"
        verbose_name_plural = "Racuni (promet)"
        constraints = []


class SalesInvoiceItem(models.Model):
    invoice = models.ForeignKey(
        "sales.SalesInvoice",
        on_delete=models.CASCADE,
        related_name="items",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_invoice_items",
    )
    product_name = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    discount_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    discount_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )

    def __str__(self) -> str:
        return f"{self.product_name} x {self.quantity}"

    class Meta:
        verbose_name = "Stavka racuna (promet)"
        verbose_name_plural = "Stavke racuna (promet)"
