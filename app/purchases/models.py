from decimal import Decimal

from django.db import models

from accounting.models import JournalEntry
from contacts.models import Supplier
from orders.models import WarehouseInput


class SupplierInvoice(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    invoice_number = models.CharField(max_length=50)
    invoice_date = models.DateField()
    received_at = models.DateField(null=True, blank=True)
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
    deposit_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    paid_cash = models.BooleanField(default=False)
    paid_at = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "invoice_number"],
                name="uq_supplier_invoice_number",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.supplier} #{self.invoice_number}"
