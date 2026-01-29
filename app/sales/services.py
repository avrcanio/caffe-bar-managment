from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from accounting.services import get_account_by_code, post_sales_cash_accounts
from sales.models import SalesInvoice, SalesZPosting


CASH_ACCOUNT_CODE = "10220"
REVENUE_ACCOUNT_CODE = "7603"
VAT_ACCOUNT_CODE = "2400"


def create_sales_z(
    *,
    issued_on,
    location_id,
    pos_id,
) -> SalesZPosting:
    qs = SalesInvoice.objects.filter(
        issued_on=issued_on,
        location_id=location_id,
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

    cash_account = get_account_by_code(CASH_ACCOUNT_CODE)
    revenue_account = get_account_by_code(REVENUE_ACCOUNT_CODE, ledger=cash_account.ledger)
    vat_account = get_account_by_code(VAT_ACCOUNT_CODE, ledger=cash_account.ledger)

    with transaction.atomic():
        if SalesZPosting.objects.filter(
            issued_on=issued_on,
            location_id=location_id,
            pos_id=pos_id,
        ).exists():
            raise ValueError("Z za ovaj datum/lokaciju/POS je već kreiran.")

        return SalesZPosting.objects.create(
            issued_on=issued_on,
            location_id=location_id,
            pos_id=pos_id,
            net_amount=net,
            vat_amount=vat,
            total_amount=total,
            cash_account=cash_account,
            revenue_account=revenue_account,
            vat_account=vat_account,
        )


def post_sales_z_posting(*, posting: SalesZPosting, posted_by=None) -> SalesZPosting:
    if posting.journal_entry_id:
        raise ValueError("Z je već proknjižen.")
    if not posting.cash_account_id or not posting.revenue_account_id:
        raise ValueError("Nedostaju konta za knjiženje (cash/prihod).")
    if posting.vat_amount != Decimal("0.00") and not posting.vat_account_id:
        raise ValueError("Nedostaje konto PDV obveze.")

    entry = post_sales_cash_accounts(
        date=posting.issued_on,
        net=posting.net_amount,
        vat=posting.vat_amount,
        cash_account=posting.cash_account,
        revenue_account=posting.revenue_account,
        vat_output_account=posting.vat_account,
        description=f"Z dnevno {posting.issued_on} (POS {posting.pos_id})",
        posted_by=posted_by,
    )
    posting.journal_entry = entry
    posting.posted_by = posted_by
    posting.save(update_fields=["journal_entry", "posted_by"])
    return posting


def get_sales_z_summary(*, issued_on, location_id, pos_id) -> dict:
    qs = SalesInvoice.objects.filter(
        issued_on=issued_on,
        location_id=location_id,
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
    has_invoices = qs.exists()
    already_posted = SalesZPosting.objects.filter(
        issued_on=issued_on,
        location_id=location_id,
        pos_id=pos_id,
    ).exists()
    return {
        "issued_on": issued_on,
        "location_id": location_id,
        "pos_id": pos_id,
        "net_amount": net,
        "vat_amount": vat,
        "total_amount": total,
        "has_invoices": has_invoices,
        "already_posted": already_posted,
    }
