from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from artikli.models import Artikl, UnitOfMeasureData
from contacts.models import Supplier
from orders.models import PurchaseOrder, PurchaseOrderItem

FRUCTUS_SUPPLIER_ID = 14
PAYMENT_TYPE_GOTOVINA_ID = 3
KG_UOM_RM_ID = 1
ORDER_DATE = date(2026, 7, 13)
DOCUMENT_REF = "2744/PV1/1"

# Artikl code -> (quantity Kg, explicit price EUR/Kg) from Fructus otpremnica 2744/PV1/1
OTPREMNICA_LINES = [
    ("16769594", Decimal("14.300"), Decimal("1.00")),  # Lubenica #1313
    ("27809119", Decimal("2.100"), Decimal("1.60")),  # Dinja #1314
    ("98212780", Decimal("2.150"), Decimal("1.41")),  # Limun #1155
]


def _ordered_at():
    naive = datetime(ORDER_DATE.year, ORDER_DATE.month, ORDER_DATE.day, 12, 0, 0)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _line_signature(lines):
    """frozenset of (artikl_id, quantity) for matching an existing PO."""
    return frozenset((artikl.id, quantity) for artikl, quantity, _price in lines)


def _existing_matching_order(supplier, lines):
    """Return an existing Fructus PO on ORDER_DATE with the same artikl/qty set, else None.

    Another PO on the same day (e.g. #328) must not block creation — only a duplicate
    of this otpremnica line set is skipped.
    """
    expected = _line_signature(lines)
    candidates = PurchaseOrder.objects.filter(
        supplier=supplier,
        ordered_at__date=ORDER_DATE,
    ).prefetch_related("items")
    for order in candidates:
        actual = frozenset(
            (item.artikl_id, item.quantity) for item in order.items.all()
        )
        if actual == expected:
            return order
    return None


class Command(BaseCommand):
    help = (
        "Create confirmed Fructus purchase order from otpremnica "
        f"{DOCUMENT_REF} (Lubenica, Dinja, Limun). Second PO on 13.07. "
        "alongside existing #328; explicit invoice prices."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        supplier = Supplier.objects.filter(pk=FRUCTUS_SUPPLIER_ID).first()
        if not supplier:
            raise RuntimeError(f"Supplier id={FRUCTUS_SUPPLIER_ID} (Fructus) not found.")

        kg_uom = UnitOfMeasureData.objects.filter(rm_id=KG_UOM_RM_ID).first()
        if not kg_uom:
            raise RuntimeError(f"UnitOfMeasure Kg rm_id={KG_UOM_RM_ID} not found.")

        lines = []
        for code, quantity, price in OTPREMNICA_LINES:
            artikl = Artikl.objects.filter(code=code).first()
            if not artikl:
                raise RuntimeError(f"Artikl with code={code} not found.")
            lines.append((artikl, quantity, price))

        existing = _existing_matching_order(supplier, lines)
        if existing:
            self.stdout.write(
                self.style.WARNING(
                    f"SKIP purchase order already exists for {ORDER_DATE} "
                    f"with same items (id={existing.id}, ref={DOCUMENT_REF})"
                )
            )
            return

        ordered_at = _ordered_at()

        if dry_run:
            self.stdout.write(
                f"DRY-RUN create PO: supplier={supplier} ordered_at={ordered_at} "
                f"status=confirmed payment_type={PAYMENT_TYPE_GOTOVINA_ID} "
                f"ref={DOCUMENT_REF} items={len(lines)}"
            )
            total_net = Decimal("0")
            for artikl, quantity, price in lines:
                line_net = quantity * price
                total_net += line_net
                self.stdout.write(
                    f"  {artikl.code} {artikl.name!r} qty={quantity} price={price} "
                    f"line_net={line_net}"
                )
            self.stdout.write(
                f"  totals: net={total_net.quantize(Decimal('0.01'))} "
                f"(expected ≈ 20.70)"
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
            for artikl, quantity, price in lines:
                item = PurchaseOrderItem(
                    order=order,
                    artikl=artikl,
                    quantity=quantity,
                    unit_of_measure=kg_uom,
                    price=price,
                )
                item.save()

            order.recalculate_totals()

        self.stdout.write(
            self.style.SUCCESS(
                f"Created purchase order id={order.id} status={order.status} "
                f"ref={DOCUMENT_REF} items={order.items.count()} "
                f"total_net={order.total_net} total_gross={order.total_gross}"
            )
        )
