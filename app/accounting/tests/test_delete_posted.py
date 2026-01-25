from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounting.models import Ledger, Account, JournalEntry, JournalItem


class DeletePostedTests(TestCase):
    def setUp(self):
        self.ledger = Ledger.objects.create(name="Mozart")

        self.acc_d = Account.objects.create(
            ledger=self.ledger,
            code="1000",
            name="Test D",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.acc_p = Account.objects.create(
            ledger=self.ledger,
            code="2000",
            name="Test P",
            type=Account.AccountType.LIABILITY,
            normal_side=Account.NormalSide.CREDIT,
            is_postable=True,
            is_active=True,
        )

        self.entry = JournalEntry.objects.create(
            ledger=self.ledger,
            number=1,
            date=date(2026, 4, 10),
            status=JournalEntry.Status.DRAFT,
        )
        self.item1 = JournalItem.objects.create(
            entry=self.entry, account=self.acc_d, debit=Decimal("10.00"), credit=Decimal("0.00")
        )
        self.item2 = JournalItem.objects.create(
            entry=self.entry, account=self.acc_p, debit=Decimal("0.00"), credit=Decimal("10.00")
        )

    def test_can_delete_draft_entry(self):
        entry_id = self.entry.id
        self.entry.delete()
        self.assertFalse(JournalEntry.objects.filter(id=entry_id).exists())

    def test_cannot_delete_posted_entry(self):
        self.entry.post()
        with self.assertRaises(ValidationError):
            self.entry.delete()

    def test_cannot_delete_item_of_posted_entry(self):
        self.entry.post()
        with self.assertRaises(ValidationError):
            self.item1.delete()
