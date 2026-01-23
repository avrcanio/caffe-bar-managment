from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounting.models import Ledger, Account, JournalEntry, JournalItem, Period


class JournalEntryReversalTests(TestCase):
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
            date=date(2026, 5, 10),
            status=JournalEntry.Status.DRAFT,
        )
        JournalItem.objects.create(
            entry=self.entry, account=self.acc_d, debit=Decimal("10.00"), credit=Decimal("0.00")
        )
        JournalItem.objects.create(
            entry=self.entry, account=self.acc_p, debit=Decimal("0.00"), credit=Decimal("10.00")
        )
        self.entry.post()

    def test_reverse_creates_posted_reversal(self):
        reversal = self.entry.reverse(reverse_date=date(2026, 5, 11))

        self.assertEqual(reversal.status, JournalEntry.Status.POSTED)
        self.assertEqual(reversal.reversed_entry_id, self.entry.id)
        self.assertTrue(hasattr(self.entry, "reversal"))
        self.assertEqual(self.entry.reversal.id, reversal.id)

        items = list(reversal.items.order_by("id"))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].debit, Decimal("0.00"))
        self.assertEqual(items[0].credit, Decimal("10.00"))
        self.assertEqual(items[1].debit, Decimal("10.00"))
        self.assertEqual(items[1].credit, Decimal("0.00"))

    def test_reverse_only_posted_allowed(self):
        draft = JournalEntry.objects.create(
            ledger=self.ledger,
            number=2,
            date=date(2026, 5, 12),
            status=JournalEntry.Status.DRAFT,
        )
        JournalItem.objects.create(
            entry=draft, account=self.acc_d, debit=Decimal("10.00"), credit=Decimal("0.00")
        )
        JournalItem.objects.create(
            entry=draft, account=self.acc_p, debit=Decimal("0.00"), credit=Decimal("10.00")
        )

        with self.assertRaises(ValidationError):
            draft.reverse()

    def test_reverse_fails_if_already_reversed(self):
        self.entry.reverse(reverse_date=date(2026, 5, 11))
        with self.assertRaises(ValidationError):
            self.entry.reverse(reverse_date=date(2026, 5, 12))

    def test_cannot_reverse_reversal_entry(self):
        reversal = self.entry.reverse(reverse_date=date(2026, 5, 11))
        with self.assertRaises(ValidationError):
            reversal.reverse(reverse_date=date(2026, 5, 12))

    def test_reverse_respects_closed_period(self):
        Period.objects.create(
            ledger=self.ledger,
            name="2026-05",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            is_closed=True,
        )

        with self.assertRaises(ValidationError):
            self.entry.reverse(reverse_date=date(2026, 5, 20))
