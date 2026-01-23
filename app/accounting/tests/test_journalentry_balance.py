from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounting.models import Ledger, Account, JournalEntry, JournalItem


class JournalEntryBalanceTests(TestCase):
    def setUp(self):
        self.ledger = Ledger.objects.create(name="Mozart")

        self.acc1 = Account.objects.create(
            ledger=self.ledger,
            code="1000",
            name="Konto D",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.acc2 = Account.objects.create(
            ledger=self.ledger,
            code="2000",
            name="Konto P",
            type=Account.AccountType.LIABILITY,
            normal_side=Account.NormalSide.CREDIT,
            is_postable=True,
            is_active=True,
        )
        self._entry_seq = 1

    def _make_entry(self) -> JournalEntry:
        return JournalEntry.objects.create(
            ledger=self.ledger,
            number=self._next_number(),
            date=date(2026, 4, 1),
            status=JournalEntry.Status.DRAFT,
        )

    def _next_number(self) -> int:
        number = self._entry_seq
        self._entry_seq += 1
        return number

    def test_is_balanced_false_when_not_equal(self):
        e = self._make_entry()
        JournalItem.objects.create(entry=e, account=self.acc1, debit=Decimal("10.00"), credit=Decimal("0.00"))
        JournalItem.objects.create(entry=e, account=self.acc2, debit=Decimal("0.00"), credit=Decimal("5.00"))

        self.assertFalse(e.is_balanced())

    def test_post_raises_when_not_balanced(self):
        e = self._make_entry()
        JournalItem.objects.create(entry=e, account=self.acc1, debit=Decimal("10.00"), credit=Decimal("0.00"))
        JournalItem.objects.create(entry=e, account=self.acc2, debit=Decimal("0.00"), credit=Decimal("5.00"))

        with self.assertRaises(ValidationError):
            e.post()
    def test_post_succeeds_when_balanced(self):
        e = self._make_entry()
        JournalItem.objects.create(entry=e, account=self.acc1, debit=Decimal("10.00"), credit=Decimal("0.00"))
        JournalItem.objects.create(entry=e, account=self.acc2, debit=Decimal("0.00"), credit=Decimal("10.00"))

        e.post()
        self.assertEqual(e.status, JournalEntry.Status.POSTED)
        self.assertIsNotNone(e.posted_at)
