from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from django.core.exceptions import ValidationError
from django.db.models import Sum, Max

from accounting.models import Ledger, JournalItem, JournalEntry, Account
from configuration.models import DocumentType
from orders.models import WarehouseInput, WarehouseInputItem


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


TWOPLACES = Decimal("0.01")


def q2(x: Decimal) -> Decimal:
    return x.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PurchaseTotals:
    net_by_rate: dict[Decimal, Decimal]
    net_total: Decimal
    vat_total: Decimal
    gross_total: Decimal
    deposit_total: Decimal
    payable_total: Decimal


def compute_purchase_totals_from_items(
    items: Iterable[WarehouseInputItem],
    *,
    deposit_total: Decimal | None = None,
) -> PurchaseTotals:
    net_by_rate: dict[Decimal, Decimal] = {}
    computed_deposit = Decimal("0.00")

    for it in items:
        if it.total is None:
            raise ValidationError("WarehouseInputItem.total je NULL – ne mogu izračunati osnovicu.")
        tax_group = getattr(it, "tax_group", None)
        if tax_group is None:
            tax_group = getattr(getattr(it, "artikl", None), "tax_group", None)
        if not tax_group:
            raise ValidationError("WarehouseInputItem nema tax_group – ne mogu izračunati PDV.")

        rate = Decimal(str(tax_group.rate))
        line_net = Decimal(str(it.total))
        percent = q2(rate * Decimal("100.00"))
        net_by_rate[percent] = net_by_rate.get(percent, Decimal("0.00")) + line_net

        if getattr(it, "artikl_id", None) and getattr(it.artikl, "deposit_id", None):
            dep_amount = Decimal(str(it.artikl.deposit.amount_eur))
            qty = Decimal(str(it.quantity))
            computed_deposit += q2(dep_amount * qty)

    net_by_rate = {r: q2(v) for r, v in net_by_rate.items()}
    net_total = q2(sum(net_by_rate.values(), Decimal("0.00")))

    vat_total = Decimal("0.00")
    for percent, base in net_by_rate.items():
        vat_total += q2(base * percent / Decimal("100.00"))
    vat_total = q2(vat_total)

    gross_total = q2(net_total + vat_total)
    if deposit_total is None:
        deposit_total = computed_deposit
    deposit_total = q2(deposit_total or Decimal("0.00"))
    payable_total = q2(gross_total + deposit_total)

    return PurchaseTotals(
        net_by_rate=net_by_rate,
        net_total=net_total,
        vat_total=vat_total,
        gross_total=gross_total,
        deposit_total=deposit_total,
        payable_total=payable_total,
    )


def flatten_input_items(inputs: Iterable[WarehouseInput]) -> list[WarehouseInputItem]:
    items: list[WarehouseInputItem] = []
    for wi in inputs:
        items.extend(list(wi.items.all()))
    return items


def _next_entry_number(ledger: Ledger) -> int:
    last = JournalEntry.objects.filter(ledger=ledger).aggregate(
        max_number=Max("number")
    )["max_number"]
    if last is None:
        last = JournalEntry.objects.filter(ledger=ledger).order_by("-number").values_list("number", flat=True).first()
    return (last or 0) + 1


def post_sales_invoice(*, document_type: DocumentType, date: date, net: Decimal, vat: Decimal, description: str = "") -> JournalEntry:
    if not document_type.ar_account_id:
        raise ValidationError("DocumentType nema postavljen AR konto (kupci).")
    if not document_type.revenue_account_id:
        raise ValidationError("DocumentType nema postavljen revenue konto (prihod).")
    if vat != Decimal("0.00") and not document_type.vat_output_account_id:
        raise ValidationError("DocumentType nema postavljen VAT output konto (PDV obveza).")

    ledger = document_type.ledger or get_single_ledger()
    gross = net + vat

    entry = JournalEntry.objects.create(
        ledger=ledger,
        number=_next_entry_number(ledger),
        date=date,
        description=description or "Izlazni racun",
        status=JournalEntry.Status.DRAFT,
    )

    JournalItem.objects.create(
        entry=entry,
        account=document_type.ar_account,
        debit=gross,
        credit=Decimal("0.00"),
    )
    JournalItem.objects.create(
        entry=entry,
        account=document_type.revenue_account,
        debit=Decimal("0.00"),
        credit=net,
    )

    if vat != Decimal("0.00"):
        JournalItem.objects.create(
            entry=entry,
            account=document_type.vat_output_account,
            debit=Decimal("0.00"),
            credit=vat,
        )

    entry.post()
    return entry


def post_sales_cash(
    *,
    document_type: DocumentType,
    date: date,
    net: Decimal,
    vat: Decimal,
    cash_account: Account,
    description: str = "",
) -> JournalEntry:
    if not cash_account:
        raise ValidationError("Nedostaje cash konto.")
    if not document_type.revenue_account_id:
        raise ValidationError("DocumentType nema revenue konto.")
    if vat != Decimal("0.00") and not document_type.vat_output_account_id:
        raise ValidationError("DocumentType nema VAT output konto.")

    ledger = document_type.ledger or get_single_ledger()
    gross = net + vat

    entry = JournalEntry.objects.create(
        ledger=ledger,
        number=_next_entry_number(ledger),
        date=date,
        description=description or "Gotovinska prodaja",
        status=JournalEntry.Status.DRAFT,
    )

    JournalItem.objects.create(
        entry=entry,
        account=cash_account,
        debit=gross,
        credit=Decimal("0.00"),
    )
    JournalItem.objects.create(
        entry=entry,
        account=document_type.revenue_account,
        debit=Decimal("0.00"),
        credit=net,
    )

    if vat != Decimal("0.00"):
        JournalItem.objects.create(
            entry=entry,
            account=document_type.vat_output_account,
            debit=Decimal("0.00"),
            credit=vat,
        )

    entry.post()
    return entry


def post_purchase_invoice_cash_from_items(
    *,
    document_type: DocumentType,
    doc_date: date,
    items: Iterable[WarehouseInputItem],
    cash_account: Account,
    deposit_total: Decimal | None = None,
    deposit_account: Account | None = None,
    description: str = "",
) -> JournalEntry:
    if not document_type.expense_account_id:
        raise ValidationError("DocumentType nema postavljen expense_account (trošak/nabava).")

    if not cash_account.is_postable:
        raise ValidationError("Cash konto mora biti postable.")


    items_list = list(items)
    if not items_list:
        raise ValidationError("Nema stavki (items) – ne mogu knjižiti ulazni račun.")

    totals = compute_purchase_totals_from_items(items_list, deposit_total=deposit_total)

    if totals.vat_total != Decimal("0.00") and not document_type.vat_input_account_id:
        raise ValidationError("Imamo PDV na stavkama, ali DocumentType nema vat_input_account (pretporez).")

    if totals.deposit_total != Decimal("0.00") and not deposit_account:
        raise ValidationError("Na stavkama postoji depozit, ali deposit_account nije zadan.")

    ledger = document_type.ledger or get_single_ledger()

    entry = JournalEntry.objects.create(
        ledger=ledger,
        number=_next_entry_number(ledger),
        date=doc_date,
        description=description or "Ulazni račun (gotovina)",
        status=JournalEntry.Status.DRAFT,
    )

    JournalItem.objects.create(
        entry=entry,
        account=document_type.expense_account,
        debit=totals.net_total,
        credit=Decimal("0.00"),
        description="Nabava/trošak (osnovica)",
    )

    if totals.vat_total != Decimal("0.00"):
        JournalItem.objects.create(
            entry=entry,
            account=document_type.vat_input_account,
            debit=totals.vat_total,
            credit=Decimal("0.00"),
            description="Pretporez (PDV ulaz)",
        )

    if totals.deposit_total != Decimal("0.00"):
        JournalItem.objects.create(
            entry=entry,
            account=deposit_account,
            debit=totals.deposit_total,
            credit=Decimal("0.00"),
            description="Povratna naknada (ambalaža/depozit)",
        )

    JournalItem.objects.create(
        entry=entry,
        account=cash_account,
        debit=Decimal("0.00"),
        credit=totals.payable_total,
        description="Plaćeno gotovinom",
    )

    entry.post()
    return entry


def post_purchase_invoice_cash_from_inputs(
    *,
    document_type: DocumentType,
    doc_date: date,
    inputs: Iterable[WarehouseInput],
    cash_account: Account,
    deposit_account: Account | None = None,
    description: str = "",
) -> JournalEntry:
    items = flatten_input_items(inputs)
    inputs_list = list(inputs)
    if any(wi.journal_entry_id for wi in inputs_list):
        raise ValidationError("Jedna od primki je već proknjižena.")
    entry = post_purchase_invoice_cash_from_items(
        document_type=document_type,
        doc_date=doc_date,
        items=items,
        cash_account=cash_account,
        deposit_account=deposit_account,
        description=description or "Ulazni račun (gotovina) - više primki",
    )
    for wi in inputs_list:
        wi.journal_entry = entry
        wi.save(update_fields=["journal_entry"])
    return entry
