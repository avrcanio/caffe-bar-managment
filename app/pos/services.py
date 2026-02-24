from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from artikli.models import Artikl
from pos.models import PosReceipt, PosReceiptItem


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _compute_item_amounts(quantity: Decimal, unit_price: Decimal, vat_rate: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    total = quantity * unit_price
    if vat_rate and vat_rate > 0:
        divisor = Decimal("1.0") + vat_rate
        net = total / divisor
    else:
        net = total
    vat = total - net
    return _quantize_money(net), _quantize_money(vat), _quantize_money(total)


def _next_receipt_number(*, office_code: str, device_code: str, issued_on):
    last = (
        PosReceipt.objects.filter(
            office_code=office_code,
            device_code=device_code,
            issued_on=issued_on,
        )
        .order_by("-receipt_number")
        .first()
    )
    return (last.receipt_number + 1) if last else 1


@transaction.atomic
def create_pos_receipt(
    *,
    office_code: str,
    device_code: str,
    payment_type: str,
    items: list[dict],
    operator=None,
    pos=None,
    warehouse=None,
    issued_at=None,
) -> PosReceipt:
    if not items:
        raise ValueError("Stavke računa su obavezne.")

    issued_at = issued_at or timezone.now()
    issued_on = timezone.localdate(issued_at)
    receipt_number = _next_receipt_number(
        office_code=office_code,
        device_code=device_code,
        issued_on=issued_on,
    )

    receipt = PosReceipt.objects.create(
        pos=pos,
        warehouse=warehouse,
        operator=operator,
        receipt_number=receipt_number,
        issued_on=issued_on,
        issued_at=issued_at,
        office_code=office_code,
        device_code=device_code,
        payment_type=payment_type,
        status=PosReceipt.Status.ISSUED,
    )

    total_net = Decimal("0.00")
    total_vat = Decimal("0.00")
    total_gross = Decimal("0.00")

    for row in items:
        artikl = row.get("artikl")
        if not isinstance(artikl, int):
            raise ValueError("Artikl mora biti integer ID.")
        artikl = Artikl.objects.get(id=artikl)

        quantity = Decimal(str(row.get("quantity", "0")))
        unit_price = Decimal(str(row.get("unit_price", "0")))
        if quantity == 0 or unit_price < 0:
            raise ValueError("Neispravna količina ili cijena.")

        vat_rate = artikl.tax_group.rate if artikl.tax_group_id else Decimal("0.0000")
        net, vat, total = _compute_item_amounts(quantity, unit_price, vat_rate)

        PosReceiptItem.objects.create(
            receipt=receipt,
            artikl=artikl,
            product_name=artikl.name,
            quantity=quantity,
            unit_price=unit_price,
            vat_rate=vat_rate,
            net_amount=net,
            vat_amount=vat,
            total_amount=total,
        )

        total_net += net
        total_vat += vat
        total_gross += total

    receipt.net_amount = _quantize_money(total_net)
    receipt.vat_amount = _quantize_money(total_vat)
    receipt.total_amount = _quantize_money(total_gross)
    receipt.save(update_fields=["net_amount", "vat_amount", "total_amount", "updated_at"])

    return receipt


@transaction.atomic
def create_pos_storno(*, original: PosReceipt, operator=None) -> PosReceipt:
    if original.storno_receipt:
        raise ValueError("Storno već postoji za ovaj račun.")
    if original.status == PosReceipt.Status.STORNO:
        raise ValueError("Ne može se stornirati storno račun.")

    receipt = PosReceipt.objects.create(
        pos=original.pos,
        warehouse=original.warehouse,
        operator=operator,
        receipt_number=_next_receipt_number(
            office_code=original.office_code,
            device_code=original.device_code,
            issued_on=original.issued_on,
        ),
        issued_on=original.issued_on,
        issued_at=timezone.now(),
        office_code=original.office_code,
        device_code=original.device_code,
        payment_type=original.payment_type,
        status=PosReceipt.Status.STORNO,
        currency=original.currency,
        storno_of=original,
    )

    total_net = Decimal("0.00")
    total_vat = Decimal("0.00")
    total_gross = Decimal("0.00")

    for item in original.items.all():
        PosReceiptItem.objects.create(
            receipt=receipt,
            artikl=item.artikl,
            product_name=item.product_name,
            quantity=-item.quantity,
            unit_price=item.unit_price,
            vat_rate=item.vat_rate,
            net_amount=-item.net_amount,
            vat_amount=-item.vat_amount,
            total_amount=-item.total_amount,
        )
        total_net += -item.net_amount
        total_vat += -item.vat_amount
        total_gross += -item.total_amount

    receipt.net_amount = _quantize_money(total_net)
    receipt.vat_amount = _quantize_money(total_vat)
    receipt.total_amount = _quantize_money(total_gross)
    receipt.save(update_fields=["net_amount", "vat_amount", "total_amount", "updated_at"])

    return receipt
