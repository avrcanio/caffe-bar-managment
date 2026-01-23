from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounting.models import Ledger, Account, JournalEntry, JournalItem
from accounting.services import trial_balance


class TrialBalanceTests(TestCase):
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

    def test_trial_balance_totals(self):
        e = JournalEntry.objects.create(
            ledger=self.ledger,
            number=1,
            date=date(2026, 6, 15),
            status=JournalEntry.Status.DRAFT,
        )
        JournalItem.objects.create(entry=e, account=self.acc_d, debit=Decimal("50.00"), credit=Decimal("0.00"))
        JournalItem.objects.create(entry=e, account=self.acc_p, debit=Decimal("0.00"), credit=Decimal("50.00"))
        e.post()

        tb = trial_balance(date(2026, 6, 1), date(2026, 6, 30))
        self.assertEqual(tb["total_debit"], Decimal("50.00"))
        self.assertEqual(tb["total_credit"], Decimal("50.00"))
        self.assertEqual(tb["difference"], Decimal("0.00"))
        self.assertEqual(len(tb["rows"]), 2)

    def test_trial_balance_empty_when_no_entries(self):
        tb = trial_balance(date(2026, 6, 1), date(2026, 6, 30))
        self.assertEqual(len(tb["rows"]), 0)
