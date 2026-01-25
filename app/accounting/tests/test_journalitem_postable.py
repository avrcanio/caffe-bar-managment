from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounting.models import Ledger, Account, JournalEntry, JournalItem


class JournalItemPostableAccountTests(TestCase):
    def setUp(self):
        self.ledger = Ledger.objects.create(name="Mozart")

        self.parent_account = Account.objects.create(
            ledger=self.ledger,
            code="120",
            name="Potrazivanja (grupni)",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=False,  # kljuc
            is_active=True,
        )

        self.entry = JournalEntry.objects.create(
            ledger=self.ledger,
            number=1,
            date=date(2026, 3, 1),
            status=JournalEntry.Status.DRAFT,
        )

    def test_cannot_post_to_non_postable_account(self):
        item = JournalItem(
            entry=self.entry,
            account=self.parent_account,
            debit=Decimal("10.00"),
            credit=Decimal("0.00"),
        )

        with self.assertRaises(ValidationError):
            item.full_clean()
