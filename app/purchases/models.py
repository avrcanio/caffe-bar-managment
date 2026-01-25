from decimal import Decimal

from django.db import models

from accounting.models import JournalEntry
from contacts.models import Supplier
from orders.models import WarehouseInput


class SupplierInvoice(models.Model):
    class PaymentTerms(models.TextChoices):
        CASH = "cash", "Gotovina"
        DEFERRED = "deferred", "Odgoda"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Neplaceno"
        PARTIAL = "partial", "Djelomicno"
        PAID = "paid", "Placeno"

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    invoice_number = models.CharField(max_length=50)
    invoice_date = models.DateField()
    received_at = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(
        max_length=20,
        choices=PaymentTerms.choices,
        default=PaymentTerms.CASH,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )
    deposit_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_net = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_vat = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_gross = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True, default="")

    inputs = models.ManyToManyField(WarehouseInput, related_name="supplier_invoices", blank=True)

    journal_entry = models.OneToOneField(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="supplier_invoice",
    )
    document_type = models.ForeignKey(
        "configuration.DocumentType",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="supplier_invoices",
    )
    cash_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    ap_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    deposit_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    paid_cash = models.BooleanField(default=False)
    paid_at = models.DateField(null=True, blank=True)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    payment_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        verbose_name = "Ulazni račun"
        verbose_name_plural = "Ulazni računi"
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "invoice_number"],
                name="uq_supplier_invoice_number",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.supplier} #{self.invoice_number}"
