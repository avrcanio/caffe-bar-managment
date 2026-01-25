from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounting.models import Ledger, Account, JournalEntry, JournalItem
from accounting.services import account_ledger


class AccountLedgerTests(TestCase):
    def setUp(self):
        self.ledger = Ledger.objects.create(name="Mozart")
        self.acc = Account.objects.create(
            ledger=self.ledger,
            code="1000",
            name="Test konto",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.acc_p = Account.objects.create(
            ledger=self.ledger,
            code="2000",
            name="Protukonto",
            type=Account.AccountType.LIABILITY,
            normal_side=Account.NormalSide.CREDIT,
            is_postable=True,
            is_active=True,
        )

        # Opening entry (before period)
        e1 = JournalEntry.objects.create(
            ledger=self.ledger,
            number=1,
            date=date(2026, 5, 31),
            status=JournalEntry.Status.DRAFT,
            description="Opening",
        )
        JournalItem.objects.create(entry=e1, account=self.acc, debit=Decimal("100.00"), credit=Decimal("0.00"))
        JournalItem.objects.create(entry=e1, account=self.acc_p, debit=Decimal("0.00"), credit=Decimal("100.00"))
        e1.post()

        # Period entry
        e2 = JournalEntry.objects.create(
            ledger=self.ledger,
            number=2,
            date=date(2026, 6, 10),
            status=JournalEntry.Status.DRAFT,
            description="Period",
        )
        JournalItem.objects.create(entry=e2, account=self.acc, debit=Decimal("20.00"), credit=Decimal("0.00"))
        JournalItem.objects.create(entry=e2, account=self.acc_p, debit=Decimal("0.00"), credit=Decimal("20.00"))
        e2.post()

    def test_account_ledger_balances(self):
        report = account_ledger(self.acc, date(2026, 6, 1), date(2026, 6, 30))
        self.assertEqual(report["opening_balance"], Decimal("100.00"))
        self.assertEqual(report["period_debit"], Decimal("20.00"))
        self.assertEqual(report["period_credit"], Decimal("0.00"))
        self.assertEqual(report["closing_balance"], Decimal("120.00"))
        self.assertEqual(len(report["rows"]), 1)
