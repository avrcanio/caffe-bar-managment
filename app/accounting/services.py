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


def post_purchase_invoice_deferred_from_items(
    *,
    document_type: DocumentType,
    doc_date: date,
    items: Iterable[WarehouseInputItem],
    ap_account: Account,
    deposit_total: Decimal | None = None,
    deposit_account: Account | None = None,
    description: str = "",
) -> JournalEntry:
    if not document_type.expense_account_id:
        raise ValidationError("DocumentType nema postavljen expense_account (trošak/nabava).")

    if not ap_account or not ap_account.is_postable:
        raise ValidationError("AP konto mora biti postable.")

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
        description=description or "Ulazni racun (odgoda)",
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
        account=ap_account,
        debit=Decimal("0.00"),
        credit=totals.payable_total,
        description="Dobavljac (odgoda)",
    )

    entry.post()
    return entry


def post_supplier_invoice_payment(
    *,
    invoice,
    amount: Decimal,
    payment_account: Account,
    paid_date: date,
) -> JournalEntry:
    if invoice.payment_terms != invoice.PaymentTerms.DEFERRED:
        raise ValidationError("Placanje je dozvoljeno samo za odgođene racune.")
    if invoice.payment_status not in (invoice.PaymentStatus.UNPAID, invoice.PaymentStatus.PARTIAL):
        raise ValidationError("Placanje je vec evidentirano.")
    if not invoice.journal_entry_id:
        raise ValidationError("Racun nije proknjizen.")
    if not invoice.ap_account_id:
        raise ValidationError("Racun nema AP konto.")
    if not payment_account or not payment_account.is_postable:
        raise ValidationError("Payment konto mora biti postable.")

    ledger = invoice.document_type.ledger if invoice.document_type_id else get_single_ledger()
    entry = JournalEntry.objects.create(
        ledger=ledger,
        number=_next_entry_number(ledger),
        date=paid_date,
        description=f"Placanje racuna {invoice.invoice_number}",
        status=JournalEntry.Status.DRAFT,
    )

    JournalItem.objects.create(
        entry=entry,
        account=invoice.ap_account,
        debit=amount,
        credit=Decimal("0.00"),
        description="Dobavljac (placanje)",
    )
    JournalItem.objects.create(
        entry=entry,
        account=payment_account,
        debit=Decimal("0.00"),
        credit=amount,
        description="Placanje",
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
    link_inputs: bool = True,
    description: str = "",
) -> JournalEntry:
    items = flatten_input_items(inputs)
    inputs_list = list(inputs)
    if link_inputs and any(wi.journal_entry_id for wi in inputs_list):
        raise ValidationError("Jedna od primki je već proknjižena.")
    entry = post_purchase_invoice_cash_from_items(
        document_type=document_type,
        doc_date=doc_date,
        items=items,
        cash_account=cash_account,
        deposit_account=deposit_account,
        description=description or "Ulazni račun (gotovina) - više primki",
    )
    if link_inputs:
        for wi in inputs_list:
            wi.journal_entry = entry
            wi.save(update_fields=["journal_entry"])
    return entry


def post_purchase_invoice_close_receipt(
    *,
    document_type: DocumentType,
    doc_date: date,
    items: Iterable[WarehouseInputItem],
    ap_account: Account | None,
    deposit_account: Account | None = None,
    cash_account: Account | None = None,
    include_cash_payment: bool = False,
    description: str = "",
) -> JournalEntry:
    if not document_type.counterpart_account_id:
        raise ValidationError("DocumentType nema postavljen konto protustavke.")
    if not include_cash_payment:
        if not ap_account or not ap_account.is_postable:
            raise ValidationError("AP konto mora biti postable.")

    items_list = list(items)
    if not items_list:
        raise ValidationError("Nema stavki (items) – ne mogu knjižiti ulazni račun.")

    totals = compute_purchase_totals_from_items(items_list, deposit_total=None)

    if totals.vat_total != Decimal("0.00") and not document_type.vat_input_account_id:
        raise ValidationError("Imamo PDV na stavkama, ali DocumentType nema vat_input_account (pretporez).")
    if totals.deposit_total != Decimal("0.00") and not deposit_account:
        raise ValidationError("Na stavkama postoji depozit, ali deposit_account nije zadan.")
    if include_cash_payment:
        if not cash_account or not cash_account.is_postable:
            raise ValidationError("Cash konto mora biti postable.")

    ledger = document_type.ledger or get_single_ledger()
    counterpart_account = _resolve_account_by_code(
        ledger=ledger,
        code=document_type.counterpart_account.code,
        label="counterpart_account",
    )

    entry = JournalEntry.objects.create(
        ledger=ledger,
        number=_next_entry_number(ledger),
        date=doc_date,
        description=description or "Ulazni racun (zatvaranje primke)",
        status=JournalEntry.Status.DRAFT,
    )

    JournalItem.objects.create(
        entry=entry,
        account=counterpart_account,
        debit=totals.net_total,
        credit=Decimal("0.00"),
        description="Zatvaranje primke (osnovica)",
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

    if include_cash_payment:
        JournalItem.objects.create(
            entry=entry,
            account=cash_account,
            debit=Decimal("0.00"),
            credit=totals.payable_total,
            description="Placanje gotovinom",
        )
    else:
        JournalItem.objects.create(
            entry=entry,
            account=ap_account,
            debit=Decimal("0.00"),
            credit=totals.payable_total,
            description="Dobavljac",
        )

    entry.post()
    return entry


def _resolve_account_by_code(*, ledger: Ledger, code: str, label: str) -> Account:
    account = (
        Account.objects
        .filter(ledger=ledger, code=code, is_postable=True)
        .first()
    )
    if not account:
        raise ValidationError(f"Nedostaje {label} konto u ledgeru (code={code}).")
    return account


def _warehouse_input_total_from_items(items: Iterable[WarehouseInputItem]) -> Decimal:
    total = Decimal("0.00")
    for it in items:
        if it.total is not None:
            line_total = Decimal(str(it.total))
        else:
            unit_cost_raw = (
                it.buying_price
                if it.buying_price is not None
                else it.price_on_stock_card
                if it.price_on_stock_card is not None
                else it.price
            )
            if unit_cost_raw is None:
                raise ValidationError("Nabavna cijena nije postavljena na stavci primke.")
            line_total = Decimal(str(unit_cost_raw)) * Decimal(str(it.quantity))
        total += line_total
    return q2(total)


def _warehouse_input_total_from_stock_move(warehouse_input: WarehouseInput) -> Decimal | None:
    if not warehouse_input.stock_move_id:
        return None
    lines = list(warehouse_input.stock_move.lines.all())
    if not lines:
        return None
    total = Decimal("0.00")
    for line in lines:
        if line.unit_cost is None:
            raise ValidationError("StockMoveLine nema unit_cost.")
        total += Decimal(str(line.quantity)) * Decimal(str(line.unit_cost))
    return q2(total)


def post_warehouse_input_to_journal(*, warehouse_input: WarehouseInput, user=None) -> JournalEntry:
    if warehouse_input.journal_entry_id:
        raise ValidationError("Primka je vec proknjizena u journal.")

    document_type = warehouse_input.document_type
    if not document_type:
        code = (warehouse_input.document_type_code or "").strip()
        if code:
            document_type = DocumentType.objects.filter(code=code).first()
    if not document_type:
        raise ValidationError("Primka nema tip dokumenta (DocumentType).")

    if not document_type.stock_account_id:
        raise ValidationError("DocumentType nema postavljen konto zalihe.")
    if not document_type.counterpart_account_id:
        raise ValidationError("DocumentType nema postavljen konto protustavke.")

    ledger = document_type.ledger or get_single_ledger()
    stock_account = _resolve_account_by_code(
        ledger=ledger,
        code=document_type.stock_account.code,
        label="stock_account",
    )
    counterpart_account = _resolve_account_by_code(
        ledger=ledger,
        code=document_type.counterpart_account.code,
        label="counterpart_account",
    )

    total = _warehouse_input_total_from_stock_move(warehouse_input)
    if total is None:
        total = _warehouse_input_total_from_items(warehouse_input.items.all())

    if total <= 0:
        raise ValidationError("Ukupan iznos primke mora biti > 0.")

    entry = JournalEntry.objects.create(
        ledger=ledger,
        number=_next_entry_number(ledger),
        date=warehouse_input.date,
        description=f"Primka #{warehouse_input.id}",
        status=JournalEntry.Status.DRAFT,
    )

    JournalItem.objects.create(
        entry=entry,
        account=stock_account,
        debit=total,
        credit=Decimal("0.00"),
        description="Zaliha (primka)",
    )
    JournalItem.objects.create(
        entry=entry,
        account=counterpart_account,
        debit=Decimal("0.00"),
        credit=total,
        description="Protustavka (primka)",
    )

    entry.post(user=user)
    warehouse_input.journal_entry = entry
    warehouse_input.save(update_fields=["journal_entry"])
    return entry
