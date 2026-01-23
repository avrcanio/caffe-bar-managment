from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounting.models import Ledger, Account, JournalEntry
from accounting.services import post_purchase_invoice_cash_from_items
from configuration.models import DocumentType, TaxGroup
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from contacts.models import Supplier
from artikli.models import Artikl, Deposit


class PostPurchaseInvoiceCashTests(TestCase):
    def setUp(self):
        self.ledger = Ledger.objects.create(name="Mozart")

        self.expense = Account.objects.create(
            ledger=self.ledger,
            code="4000",
            name="Rashodi",
            type=Account.AccountType.EXPENSE,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.vat_in = Account.objects.create(
            ledger=self.ledger,
            code="1400",
            name="Pretporez",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.cash = Account.objects.create(
            ledger=self.ledger,
            code="1020",
            name="Blagajna",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.deposit = Account.objects.create(
            ledger=self.ledger,
            code="1310",
            name="Depozit",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )

        self.doc = DocumentType.objects.create(
            name="Ulazni racun",
            code="UR",
            direction=DocumentType.DIRECTION_IN,
            ledger=self.ledger,
            expense_account=self.expense,
            vat_input_account=self.vat_in,
        )

        supplier = Supplier.objects.create(rm_id=1, name="Test dobavljac")
        po = PurchaseOrder.objects.create(supplier=supplier, ordered_at=timezone.now())
        tg_5 = TaxGroup.objects.create(name="PDV 5", rate=Decimal("0.0500"), code="PDV5", is_active=True)
        tg_25 = TaxGroup.objects.create(name="PDV 25", rate=Decimal("0.2500"), code="PDV25", is_active=True)
        deposit = Deposit.objects.create(amount_eur=Decimal("0.10"))
        artikl_5 = Artikl.objects.create(name="Test artikl 5%", tax_group=tg_5, deposit=deposit)
        artikl_25 = Artikl.objects.create(name="Test artikl 25%", tax_group=tg_25, deposit=deposit)

        self.wi = WarehouseInput.objects.create(
            order=po,
            supplier=supplier,
            date=date(2026, 7, 2),
        )
        WarehouseInputItem.objects.create(
            warehouse_input=self.wi,
            artikl=artikl_5,
            quantity=Decimal("1.00"),
            total=Decimal("14.04"),
        )
        WarehouseInputItem.objects.create(
            warehouse_input=self.wi,
            artikl=artikl_25,
            quantity=Decimal("1.00"),
            total=Decimal("82.69"),
        )

    def test_post_purchase_invoice_cash(self):
        entry = post_purchase_invoice_cash_from_items(
            document_type=self.doc,
            doc_date=date(2026, 7, 2),
            items=self.wi.items.all(),
            cash_account=self.cash,
            deposit_account=self.deposit,
            description="Ulazni racun",
        )

        self.assertEqual(entry.status, JournalEntry.Status.POSTED)
        self.assertEqual(entry.items.count(), 4)
        self.assertTrue(entry.items.filter(account=self.deposit, debit=Decimal("0.20")).exists())

    def test_requires_expense_account(self):
        doc = DocumentType.objects.create(
            name="Ulazni racun 2",
            code="UR2",
            direction=DocumentType.DIRECTION_IN,
            ledger=self.ledger,
        )
        with self.assertRaises(ValidationError):
            post_purchase_invoice_cash_from_items(
                document_type=doc,
                doc_date=date(2026, 7, 2),
                items=self.wi.items.all(),
                cash_account=self.cash,
                deposit_total=Decimal("0.00"),
            )
