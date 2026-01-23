from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounting.models import Ledger, Period, Account, JournalEntry, JournalItem


class JournalEntryLockingTests(TestCase):
    def setUp(self):
        self.ledger = Ledger.objects.create(name="Mozart", oib="")

        # Minimalna konta (postable) za balans
        self.acc1 = Account.objects.create(
            ledger=self.ledger,
            code="1000",
            name="Test konto D",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.acc2 = Account.objects.create(
            ledger=self.ledger,
            code="2000",
            name="Test konto P",
            type=Account.AccountType.LIABILITY,
            normal_side=Account.NormalSide.CREDIT,
            is_postable=True,
            is_active=True,
        )

    def _make_balanced_entry(self, d: date) -> JournalEntry:
        e = JournalEntry.objects.create(
            ledger=self.ledger,
            number=1,
            date=d,
            description="Test",
            status=JournalEntry.Status.DRAFT,
        )
        JournalItem.objects.create(entry=e, account=self.acc1, debit=Decimal("10.00"), credit=Decimal("0.00"))
        JournalItem.objects.create(entry=e, account=self.acc2, debit=Decimal("0.00"), credit=Decimal("10.00"))
        return e

    def test_cannot_post_into_closed_period(self):
        Period.objects.create(
            ledger=self.ledger,
            name="2026-01",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            is_closed=True,
        )

        e = self._make_balanced_entry(date(2026, 1, 15))

        with self.assertRaises(ValidationError):
            e.post()

    def test_cannot_save_posted_entry_in_closed_period(self):
        # period otvoren u trenutku postanja
        Period.objects.create(
            ledger=self.ledger,
            name="2026-01",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            is_closed=False,
        )

        e = self._make_balanced_entry(date(2026, 1, 10))
        e.post()  # treba proci

        # zakljuca se period nakon sto je entry vec POSTED
        p = Period.objects.get(ledger=self.ledger, name="2026-01")
        p.is_closed = True
        p.save(update_fields=["is_closed"])

        # bilo koji save POSTED entryja u zatvorenom periodu treba pasti
        e.description = "Promjena opisa"
        with self.assertRaises(ValidationError):
            e.save()

    def test_cannot_change_status_or_date_once_posted(self):
        Period.objects.create(
            ledger=self.ledger,
            name="2026-02",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
            is_closed=False,
        )

        e = self._make_balanced_entry(date(2026, 2, 5))
        e.post()

        # promjena statusa
        e.status = JournalEntry.Status.DRAFT
        with self.assertRaises(ValidationError):
            e.save()

        # reload pa test promjene datuma
        e = JournalEntry.objects.get(pk=e.pk)
        e.date = date(2026, 2, 6)
        with self.assertRaises(ValidationError):
            e.save()
