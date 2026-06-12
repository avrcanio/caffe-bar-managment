from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from artikli.models import Artikl, UnitOfMeasureData
from contacts.models import Supplier
from orders.models import PurchaseOrder, PurchaseOrderItem

KOKTEL_SUPPLIER_ID = 3
PAYMENT_TYPE_TRANSAKCIJSKI_ID = 8
KOMAD_UOM_RM_ID = 3
ORDER_DATE = date(2026, 6, 11)
MADRI_CODE = "8600105005867"
MADRI_PRICE = Decimal("1.10")

# EAN -> (quantity Komad, explicit price or None) from otpremnica 7238-V1-2
OTPREMNICA_LINES = [
    ("9002515427182", Decimal("12"), None),
    ("38501708", Decimal("48"), None),
    (MADRI_CODE, Decimal("40"), MADRI_PRICE),
    ("9002515427168", Decimal("12"), None),
    ("3850131481011", Decimal("24"), None),
]


def _ordered_at():
    naive = datetime(ORDER_DATE.year, ORDER_DATE.month, ORDER_DATE.day, 12, 0, 0)
    return timezone.make_aware(naive, timezone.get_current_timezone())


class Command(BaseCommand):
    help = (
        "Create confirmed KOKTEL purchase order from otpremnica 7238-V1-2 "
        "(Šank Gornji destination)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        supplier = Supplier.objects.filter(pk=KOKTEL_SUPPLIER_ID).first()
        if not supplier:
            raise RuntimeError(f"Supplier id={KOKTEL_SUPPLIER_ID} (KOKTEL) not found.")

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
        for code, quantity, explicit_price in OTPREMNICA_LINES:
            artikl = Artikl.objects.filter(code=code).first()
            if not artikl:
                raise RuntimeError(f"Artikl with code={code} not found.")
            lines.append((artikl, quantity, explicit_price))

        ordered_at = _ordered_at()

        if dry_run:
            self.stdout.write(
                f"DRY-RUN create PO: supplier={supplier} ordered_at={ordered_at} "
                f"status=confirmed payment_type={PAYMENT_TYPE_TRANSAKCIJSKI_ID} "
                f"items={len(lines)}"
            )
            for artikl, quantity, explicit_price in lines:
                probe_order = PurchaseOrder(
                    supplier=supplier,
                    ordered_at=ordered_at,
                    status=PurchaseOrder.STATUS_CONFIRMED,
                    payment_type_id=PAYMENT_TYPE_TRANSAKCIJSKI_ID,
                )
                probe_item = PurchaseOrderItem(
                    order=probe_order,
                    artikl=artikl,
                    quantity=quantity,
                    unit_of_measure=komad_uom,
                    price=explicit_price,
                )
                price = explicit_price or probe_item._resolve_price()
                self.stdout.write(
                    f"  {artikl.code} {artikl.name!r} qty={quantity} price={price}"
                )
            self.stdout.write(self.style.SUCCESS("Dry-run complete."))
            return

        with transaction.atomic():
            order = PurchaseOrder.objects.create(
                supplier=supplier,
                ordered_at=ordered_at,
                status=PurchaseOrder.STATUS_CONFIRMED,
                confirmed_at=ordered_at,
                payment_type_id=PAYMENT_TYPE_TRANSAKCIJSKI_ID,
            )
            for artikl, quantity, explicit_price in lines:
                item = PurchaseOrderItem(
                    order=order,
                    artikl=artikl,
                    quantity=quantity,
                    unit_of_measure=komad_uom,
                    price=explicit_price,
                )
                item.save()

            order.recalculate_totals()

        self.stdout.write(
            self.style.SUCCESS(
                f"Created purchase order id={order.id} status={order.status} "
                f"items={order.items.count()} total_net={order.total_net} "
                f"total_gross={order.total_gross} total_deposit={order.total_deposit}"
            )
        )
