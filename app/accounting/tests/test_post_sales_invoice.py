from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounting.models import Ledger, Account, JournalEntry
from accounting.services import post_sales_invoice
from configuration.models import DocumentType


class PostSalesInvoiceTests(TestCase):
    def setUp(self):
        self.ledger = Ledger.objects.create(name="Mozart")
        self.ar = Account.objects.create(
            ledger=self.ledger,
            code="1200",
            name="Kupci",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.rev = Account.objects.create(
            ledger=self.ledger,
            code="6000",
            name="Prihodi",
            type=Account.AccountType.INCOME,
            normal_side=Account.NormalSide.CREDIT,
            is_postable=True,
            is_active=True,
        )
        self.vat = Account.objects.create(
            ledger=self.ledger,
            code="2400",
            name="PDV obveza",
            type=Account.AccountType.LIABILITY,
            normal_side=Account.NormalSide.CREDIT,
            is_postable=True,
            is_active=True,
        )

        self.doc = DocumentType.objects.create(
            name="Racun",
            code="RACUN",
            direction=DocumentType.DIRECTION_OUT,
            ledger=self.ledger,
            ar_account=self.ar,
            revenue_account=self.rev,
            vat_output_account=self.vat,
        )

    def test_post_sales_invoice_creates_posted_entry(self):
        entry = post_sales_invoice(
            document_type=self.doc,
            date=date(2026, 7, 1),
            net=Decimal("100.00"),
            vat=Decimal("25.00"),
            description="Test racun",
        )

        self.assertEqual(entry.status, JournalEntry.Status.POSTED)
        self.assertEqual(entry.items.count(), 3)

    def test_post_sales_invoice_requires_accounts(self):
        doc = DocumentType.objects.create(
            name="Racun 2",
            code="RACUN2",
            direction=DocumentType.DIRECTION_OUT,
            ledger=self.ledger,
        )
        with self.assertRaises(ValidationError):
            post_sales_invoice(
                document_type=doc,
                date=date(2026, 7, 1),
                net=Decimal("10.00"),
                vat=Decimal("0.00"),
            )
