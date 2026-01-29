from decimal import Decimal

from django.db import models


class SalesInvoice(models.Model):
    rm_number = models.IntegerField(unique=True)
    issued_on = models.DateField()
    issued_at = models.DateTimeField()
    location_name = models.CharField(max_length=255, blank=True, default="")
    buyer_name = models.CharField(max_length=255, blank=True, default="")
    waiter_name = models.CharField(max_length=255, blank=True, default="")
    net_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    vat_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
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


class SalesZPosting(models.Model):
    issued_on = models.DateField()
    location_id = models.IntegerField(null=True, blank=True)
    pos_id = models.IntegerField(null=True, blank=True)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cash_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    revenue_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    vat_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_z_postings",
    )
    posted_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_z_postings",
    )
    posted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        loc = self.location_id if self.location_id is not None else "?"
        pos = self.pos_id if self.pos_id is not None else "?"
        return f"Z {self.issued_on} (lok {loc}, POS {pos})"

    class Meta:
        verbose_name = "Z knjiženje (promet)"
        verbose_name_plural = "Z knjiženja (promet)"
        constraints = [
            models.UniqueConstraint(
                fields=["issued_on", "location_id", "pos_id"],
                name="uq_sales_z_posting",
            )
        ]


class Representation(models.Model):
    occurred_at = models.DateTimeField(auto_now_add=True, verbose_name="Vrijeme")
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        to_field="rm_id",
        on_delete=models.PROTECT,
        related_name="representations",
        verbose_name="Skladiste",
    )
    user = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="representations",
        verbose_name="Korisnik",
    )
    reason = models.ForeignKey(
        "sales.RepresentationReason",
        on_delete=models.PROTECT,
        related_name="representations",
        verbose_name="Razlog reprezentacije",
    )
    note = models.TextField(blank=True, default="", verbose_name="Napomena")

    def __str__(self) -> str:
        return f"Reprezentacija {self.occurred_at:%Y-%m-%d %H:%M}"

    class Meta:
        verbose_name = "Reprezentacija"
        verbose_name_plural = "Reprezentacije"


class RepresentationReason(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Razlog reprezentacije"
        verbose_name_plural = "Razlozi reprezentacije"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class RepresentationItem(models.Model):
    representation = models.ForeignKey(
        "sales.Representation",
        on_delete=models.CASCADE,
        related_name="items",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.PROTECT,
        related_name="representation_items",
        limit_choices_to={"is_sellable": True},
        verbose_name="Artikl",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=4, verbose_name="Kolicina")
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Cijena",
    )

    def __str__(self) -> str:
        return f"{self.artikl} x {self.quantity}"

    class Meta:
        verbose_name = "Stavka reprezentacije"
        verbose_name_plural = "Stavke reprezentacije"
