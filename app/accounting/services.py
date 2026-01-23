from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from accounting.models import Ledger, JournalItem, JournalEntry, Account


def get_single_ledger() -> Ledger:
    ledger = Ledger.objects.first()
    if not ledger:
        raise RuntimeError("Ne postoji Ledger u bazi. Kreiraj ga prvo.")
    return ledger


@dataclass
class LedgerRow:
    entry_id: int
    entry_number: int
    entry_date: date
    description: str
    debit: Decimal
    credit: Decimal


def account_ledger(account: Account, date_from: date, date_to: date):
    qs = (
        JournalItem.objects
        .filter(
            account=account,
            entry__status=JournalEntry.Status.POSTED,
            entry__date__gte=date_from,
            entry__date__lte=date_to,
        )
        .select_related("entry")
        .order_by("entry__date", "entry__number", "id")
    )

    opening = (
        JournalItem.objects
        .filter(
            account=account,
            entry__status=JournalEntry.Status.POSTED,
            entry__date__lt=date_from,
        )
        .aggregate(
            d=Sum("debit", default=Decimal("0.00")),
            c=Sum("credit", default=Decimal("0.00")),
        )
    )
    opening_balance = (opening["d"] or Decimal("0.00")) - (opening["c"] or Decimal("0.00"))

    rows = [
        LedgerRow(
            entry_id=i.entry_id,
            entry_number=i.entry.number,
            entry_date=i.entry.date,
            description=i.description or i.entry.description or "",
            debit=i.debit,
            credit=i.credit,
        )
        for i in qs
    ]

    totals = qs.aggregate(
        d=Sum("debit", default=Decimal("0.00")),
        c=Sum("credit", default=Decimal("0.00")),
    )
    period_debit = totals["d"] or Decimal("0.00")
    period_credit = totals["c"] or Decimal("0.00")
    period_change = period_debit - period_credit
    closing_balance = opening_balance + period_change

    return {
        "opening_balance": opening_balance,
        "period_debit": period_debit,
        "period_credit": period_credit,
        "closing_balance": closing_balance,
        "rows": rows,
    }


@dataclass
class TrialBalanceRow:
    code: str
    name: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


def trial_balance(date_from: date, date_to: date, *, only_postable: bool = True, only_nonzero: bool = True):
    acc_qs = Account.objects.filter(is_active=True)
    if only_postable:
        acc_qs = acc_qs.filter(is_postable=True)

    items = (
        JournalItem.objects
        .filter(
            entry__status=JournalEntry.Status.POSTED,
            entry__date__gte=date_from,
            entry__date__lte=date_to,
        )
        .values("account_id")
        .annotate(
            d=Sum("debit", default=Decimal("0.00")),
            c=Sum("credit", default=Decimal("0.00")),
        )
    )
    totals_by_account = {
        i["account_id"]: (i["d"] or Decimal("0.00"), i["c"] or Decimal("0.00"))
        for i in items
    }

    rows: list[TrialBalanceRow] = []
    total_d = Decimal("0.00")
    total_c = Decimal("0.00")

    for acc in acc_qs.order_by("code"):
        d, c = totals_by_account.get(acc.id, (Decimal("0.00"), Decimal("0.00")))
        if only_nonzero and d == Decimal("0.00") and c == Decimal("0.00"):
            continue
        bal = d - c
        rows.append(TrialBalanceRow(code=acc.code, name=acc.name, debit=d, credit=c, balance=bal))
        total_d += d
        total_c += c

    return {
        "rows": rows,
        "total_debit": total_d,
        "total_credit": total_c,
        "difference": total_d - total_c,
    }
