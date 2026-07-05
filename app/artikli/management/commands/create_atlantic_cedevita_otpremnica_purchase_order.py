from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from artikli.models import Artikl, UnitOfMeasureData
from contacts.models import Supplier
from orders.models import PurchaseOrder, PurchaseOrderItem

ATLANTIC_SUPPLIER_ID = 13
PAYMENT_TYPE_GOTOVINA_ID = 3
KOMAD_UOM_RM_ID = 3
ORDER_DATE = date(2026, 7, 1)

# EAN -> quantity (Komad) from Atlantic otpremnica A102TP746017443-R-1
OTPREMNICA_LINES = [
    ("3850322009154", Decimal("50")),
    ("3850322009406", Decimal("50")),
    ("3850322016343", Decimal("50")),
    ("3850322016978", Decimal("50")),
]


def _ordered_at():
    naive = datetime(ORDER_DATE.year, ORDER_DATE.month, ORDER_DATE.day, 12, 0, 0)
    return timezone.make_aware(naive, timezone.get_current_timezone())


class Command(BaseCommand):
    help = (
        "Create confirmed Atlantic Trade purchase order from otpremnica "
        "A102TP746017443-R-1 (Cedevita)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        supplier = Supplier.objects.filter(pk=ATLANTIC_SUPPLIER_ID).first()
        if not supplier:
            raise RuntimeError(f"Supplier id={ATLANTIC_SUPPLIER_ID} (Atlantic Trade) not found.")

        komad_uom = UnitOfMeasureData.objects.filter(rm_id=KOMAD_UOM_RM_ID).first()
        if not komad_uom:
            raise RuntimeError(f"UnitOfMeasure Komad rm_id={KOMAD_UOM_RM_ID} not found.")

        if PurchaseOrder.objects.filter(
            supplier=supplier,
            ordered_at__date=ORDER_DATE,
        ).exists():
            self.stdout.write(
                self.style.WARNING(f"SKIP purchase order already exists for {ORDER_DATE}")
            )
            return

        lines = []
        for ean, quantity in OTPREMNICA_LINES:
            artikl = Artikl.objects.filter(code=ean).first()
            if not artikl:
                raise RuntimeError(f"Artikl with code={ean} not found.")
            lines.append((artikl, quantity))

        ordered_at = _ordered_at()

        if dry_run:
            self.stdout.write(
                f"DRY-RUN create PO: supplier={supplier} ordered_at={ordered_at} "
                f"status=confirmed payment_type={PAYMENT_TYPE_GOTOVINA_ID} items={len(lines)}"
            )
            total_net = Decimal("0")
            for artikl, quantity in lines:
                probe_order = PurchaseOrder(
                    supplier=supplier,
                    ordered_at=ordered_at,
                    status=PurchaseOrder.STATUS_CONFIRMED,
                    payment_type_id=PAYMENT_TYPE_GOTOVINA_ID,
                )
                probe_item = PurchaseOrderItem(
                    order=probe_order,
                    artikl=artikl,
                    quantity=quantity,
                    unit_of_measure=komad_uom,
                    price=None,
                )
                price = probe_item._resolve_price()
                line_net = quantity * price
                total_net += line_net
                self.stdout.write(
                    f"  {artikl.code} {artikl.name!r} qty={quantity} price={price} "
                    f"line_net={line_net}"
                )
            total_gross = total_net * Decimal("1.25")
            self.stdout.write(
                f"  totals: net={total_net} gross={total_gross.quantize(Decimal('0.01'))}"
            )
            self.stdout.write(self.style.SUCCESS("Dry-run complete."))
            return

        with transaction.atomic():
            order = PurchaseOrder.objects.create(
                supplier=supplier,
                ordered_at=ordered_at,
                status=PurchaseOrder.STATUS_CONFIRMED,
                confirmed_at=ordered_at,
                payment_type_id=PAYMENT_TYPE_GOTOVINA_ID,
            )
            for artikl, quantity in lines:
                item = PurchaseOrderItem(
                    order=order,
                    artikl=artikl,
                    quantity=quantity,
                    unit_of_measure=komad_uom,
                    price=None,
                )
                item.save()

            order.recalculate_totals()

        self.stdout.write(
            self.style.SUCCESS(
                f"Created purchase order id={order.id} status={order.status} "
                f"items={order.items.count()} total_net={order.total_net} "
                f"total_gross={order.total_gross}"
            )
        )
