from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounting.models import Ledger, Account, JournalEntry, JournalItem


class VoidLockingTests(TestCase):
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

    def test_cannot_add_item_to_void_entry(self):
        e = JournalEntry.objects.create(
            ledger=self.ledger,
            number=1,
            date=date(2026, 6, 4),
            status=JournalEntry.Status.DRAFT,
        )
        e.void()

        item = JournalItem(
            entry=e,
            account=self.acc_d,
            debit=Decimal("10.00"),
            credit=Decimal("0.00"),
        )

        with self.assertRaises(ValidationError):
            item.save()

    def test_cannot_change_status_from_void(self):
        e = JournalEntry.objects.create(
            ledger=self.ledger,
            number=2,
            date=date(2026, 6, 4),
            status=JournalEntry.Status.DRAFT,
        )
        e.void()

        e.status = JournalEntry.Status.DRAFT
        with self.assertRaises(ValidationError):
            e.save()
