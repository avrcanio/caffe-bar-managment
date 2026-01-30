from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum

from accounting.services import get_account_by_code, post_sales_cash_accounts
from sales.models import SalesInvoice, SalesZPosting
from accounting.models import Ledger
from stock.models import WarehouseId
from pos.models import Pos
from artikli.models import Normativ
from configuration.models import CompanyProfile
from stock.services import post_stock_out


CASH_ACCOUNT_CODE = "10220"
REVENUE_ACCOUNT_CODE = "7603"
VAT_ACCOUNT_CODE = "2400"
PNP_ACCOUNT_CODE = "2481"


def _get_pnp_rate(ledger: Ledger | None) -> Decimal | None:
    if ledger and ledger.company_profile_id:
        profile = ledger.company_profile
    else:
        profile = CompanyProfile.objects.order_by("-id").first()
    if not profile or not profile.lgu_id:
        return None
    return Decimal(str(profile.lgu.pnp_rate))


def _compute_pnp_amount(qs) -> Decimal:
    invoice_ids = list(qs.values_list("id", flat=True))
    if not invoice_ids:
        return Decimal("0.00")

    ledger_id = qs.values_list("ledger_id", flat=True).first()
    ledger = Ledger.objects.filter(id=ledger_id).first() if ledger_id else None
    pnp_rate = _get_pnp_rate(ledger)

    from sales.models import SalesInvoiceItem
    pnp_items_qs = (
        SalesInvoiceItem.objects
        .filter(invoice_id__in=invoice_ids, artikl__pnp_category__isnull=False)
        .select_related("artikl__tax_group")
    )

    if not pnp_items_qs.exists():
        return Decimal("0.00")
    if pnp_rate is None:
        raise ValueError("Nedostaje PnP stopa (CompanyProfile.lgu).")

    total = Decimal("0.00")
    for item in pnp_items_qs:
        if not item.artikl or not item.artikl.tax_group_id:
            raise ValueError(f"Artikl {item.product_name} nema tax_group, a ima PnP kategoriju.")
        vat_rate = Decimal(str(item.artikl.tax_group.rate))
        gross = Decimal(str(item.amount))
        net = gross / (Decimal("1.00") + vat_rate)
        total += net * pnp_rate

    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def create_sales_z(
    *,
    issued_on,
    warehouse_id,
    pos_id,
) -> SalesZPosting:
    qs = SalesInvoice.objects.filter(
        issued_on=issued_on,
        warehouse_id=warehouse_id,
        pos_id=pos_id,
    )
    if not qs.exists():
        raise ValueError("Nema računa za zadani datum/lokaciju/POS.")

    totals = qs.aggregate(
        net=Sum("net_amount"),
        vat=Sum("vat_amount"),
        total=Sum("total_amount"),
    )

    net = totals.get("net") or Decimal("0.00")
    vat = totals.get("vat") or Decimal("0.00")
    total = totals.get("total") or Decimal("0.00")
    if total == Decimal("0.00"):
        raise ValueError("Ukupni iznos je 0.00, Z se ne kreira.")

    pnp_amount = _compute_pnp_amount(qs)
    cash_account = get_account_by_code(CASH_ACCOUNT_CODE)
    revenue_account = get_account_by_code(REVENUE_ACCOUNT_CODE, ledger=cash_account.ledger)
    vat_account = get_account_by_code(VAT_ACCOUNT_CODE, ledger=cash_account.ledger)
    pnp_account = get_account_by_code(PNP_ACCOUNT_CODE, ledger=cash_account.ledger) if pnp_amount > Decimal("0.00") else None

    with transaction.atomic():
        if SalesZPosting.objects.filter(
            issued_on=issued_on,
            warehouse_id=warehouse_id,
            pos_id=pos_id,
        ).exists():
            raise ValueError("Z za ovaj datum/lokaciju/POS je već kreiran.")

        ledger = qs.values_list("ledger_id", flat=True).first()
        ledger_obj = Ledger.objects.filter(id=ledger).first() if ledger else Ledger.objects.first()

        return SalesZPosting.objects.create(
            issued_on=issued_on,
            ledger=ledger_obj,
            warehouse=WarehouseId.objects.filter(id=warehouse_id).first(),
            pos=Pos.objects.filter(id=pos_id).first(),
            net_amount=net,
            vat_amount=vat,
            pnp_amount=pnp_amount,
            total_amount=total,
            cash_account=cash_account,
            revenue_account=revenue_account,
            vat_account=vat_account,
            pnp_account=pnp_account,
        )


def post_sales_z_posting(*, posting: SalesZPosting, posted_by=None) -> SalesZPosting:
    if posting.journal_entry_id:
        raise ValueError("Z je već proknjižen.")
    if not posting.cash_account_id or not posting.revenue_account_id:
        raise ValueError("Nedostaju konta za knjiženje (cash/prihod).")
    if posting.vat_amount != Decimal("0.00") and not posting.vat_account_id:
        raise ValueError("Nedostaje konto PDV obveze.")

    pos_label = posting.pos.external_pos_id if posting.pos_id else "?"
    entry = post_sales_cash_accounts(
        date=posting.issued_on,
        net=posting.net_amount,
        vat=posting.vat_amount,
        cash_account=posting.cash_account,
        revenue_account=posting.revenue_account,
        vat_output_account=posting.vat_account,
        pnp_amount=posting.pnp_amount,
        pnp_account=posting.pnp_account,
        description=f"Z dnevno {posting.issued_on} (POS {pos_label})",
        posted_by=posted_by,
    )
    posting.journal_entry = entry
    posting.posted_by = posted_by
    posting.save(update_fields=["journal_entry", "posted_by"])
    return posting


def build_stock_out_lines_for_invoice(invoice: SalesInvoice) -> tuple[list[dict], list[str]]:
    """
    Build stock-out lines for a sales invoice:
    - If artikl.is_stock_item -> direct deduction
    - Else if artikl has active Normativ -> deduct ingredients
    - Else -> skipped with reason
    """
    lines_by_artikl: dict[int, dict] = {}
    skipped: list[str] = []

    items = invoice.items.select_related("artikl").all()
    for item in items:
        artikl = item.artikl
        if not artikl:
            skipped.append(f"Stavka '{item.product_name}' nema artikl.")
            continue

        qty = Decimal(str(item.quantity))
        if qty <= 0:
            skipped.append(f"Artikl {artikl} ima kolicinu {qty}.")
            continue

        if artikl.is_stock_item:
            key = artikl.id
            line = lines_by_artikl.get(key)
            if not line:
                line = {"artikl": artikl, "quantity": Decimal("0.00")}
                lines_by_artikl[key] = line
            line["quantity"] += qty
            continue

        normativ = Normativ.objects.filter(product=artikl, is_active=True).first()
        if normativ:
            for nitem in normativ.items.select_related("ingredient").all():
                ing = nitem.ingredient
                ing_qty = Decimal(str(nitem.qty)) * qty
                if ing_qty <= 0:
                    continue
                key = ing.id
                line = lines_by_artikl.get(key)
                if not line:
                    line = {"artikl": ing, "quantity": Decimal("0.00")}
                    lines_by_artikl[key] = line
                line["quantity"] += ing_qty
        else:
            skipped.append(f"Artikl {artikl} nije skladisni i nema normativ.")

    return list(lines_by_artikl.values()), skipped


def build_stock_out_lines_for_items(items) -> tuple[list[dict], list[str]]:
    """
    Build stock-out lines for specific sales invoice items.
    Same rules as invoice-level, but only for provided items.
    """
    lines_by_artikl: dict[int, dict] = {}
    skipped: list[str] = []

    for item in items:
        artikl = item.artikl
        if not artikl:
            skipped.append(f"Stavka '{item.product_name}' nema artikl.")
            continue

        qty = Decimal(str(item.quantity))
        if qty <= 0:
            skipped.append(f"Artikl {artikl} ima kolicinu {qty}.")
            continue

        if artikl.is_stock_item:
            key = artikl.id
            line = lines_by_artikl.get(key)
            if not line:
                line = {"artikl": artikl, "quantity": Decimal("0.00")}
                lines_by_artikl[key] = line
            line["quantity"] += qty
            continue

        normativ = Normativ.objects.filter(product=artikl, is_active=True).first()
        if normativ:
            for nitem in normativ.items.select_related("ingredient").all():
                ing = nitem.ingredient
                ing_qty = Decimal(str(nitem.qty)) * qty
                if ing_qty <= 0:
                    continue
                key = ing.id
                line = lines_by_artikl.get(key)
                if not line:
                    line = {"artikl": ing, "quantity": Decimal("0.00")}
                    lines_by_artikl[key] = line
                line["quantity"] += ing_qty
        else:
            skipped.append(f"Artikl {artikl} nije skladisni i nema normativ.")

    return list(lines_by_artikl.values()), skipped


def post_sales_items_stock_out(*, invoice: SalesInvoice, items, user=None):
    if not invoice.warehouse_id:
        raise ValueError("Racun nema vezano skladiste (warehouse).")

    lines, skipped = build_stock_out_lines_for_items(items)
    if not lines:
        raise ValueError("Nema stavki za razduzenje.")

    move = post_stock_out(
        warehouse=invoice.warehouse,
        items=lines,
        move_date=invoice.issued_at,
        reference=f"POS racun {invoice.rm_number}",
        note="Robno razduzenje iz prodaje (stavke)",
        purpose="sale",
        auto_cogs=True,
        posted_by=user,
    )

    return move, skipped


def post_sales_invoice_stock_out(invoice: SalesInvoice, *, user=None):
    if not invoice.warehouse_id:
        raise ValueError("Racun nema vezano skladiste (warehouse).")

    lines, skipped = build_stock_out_lines_for_invoice(invoice)
    if not lines:
        raise ValueError("Nema stavki za razduzenje.")

    move = post_stock_out(
        warehouse=invoice.warehouse,
        items=lines,
        move_date=invoice.issued_at,
        reference=f"POS racun {invoice.rm_number}",
        note="Robno razduzenje iz prodaje",
        purpose="sale",
        auto_cogs=True,
        posted_by=user,
    )

    return move, skipped


def get_sales_z_summary(*, issued_on, warehouse_id, pos_id) -> dict:
    qs = SalesInvoice.objects.filter(
        issued_on=issued_on,
        warehouse_id=warehouse_id,
        pos_id=pos_id,
    )
    totals = qs.aggregate(
        net=Sum("net_amount"),
        vat=Sum("vat_amount"),
        total=Sum("total_amount"),
    )
    net = totals.get("net") or Decimal("0.00")
    vat = totals.get("vat") or Decimal("0.00")
    total = totals.get("total") or Decimal("0.00")
    pnp_amount = _compute_pnp_amount(qs)
    has_invoices = qs.exists()
    already_posted = SalesZPosting.objects.filter(
        issued_on=issued_on,
        warehouse_id=warehouse_id,
        pos_id=pos_id,
    ).exists()
    return {
        "issued_on": issued_on,
        "warehouse_id": warehouse_id,
        "pos_id": pos_id,
        "net_amount": net,
        "vat_amount": vat,
        "pnp_amount": pnp_amount,
        "total_amount": total,
        "has_invoices": has_invoices,
        "already_posted": already_posted,
    }
