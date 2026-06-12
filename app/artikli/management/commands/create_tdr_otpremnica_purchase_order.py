from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from artikli.models import Artikl, UnitOfMeasureData
from contacts.models import Supplier
from orders.models import PurchaseOrder, PurchaseOrderItem, SupplierPriceItem, SupplierPriceList

TDR_SUPPLIER_ID = 5
PAYMENT_TYPE_GOTOVINA_ID = 3
KOMAD_UOM_RM_ID = 3
ORDER_DATE = date(2026, 6, 7)
PRICELIST_NAME = "Cigarete - novi artikli 2026-06"
TWIST_EAN = "38506284"
TWIST_PRICE = Decimal("3.76")

# EAN -> quantity (Komad) from TDR otpremnica 9198533701
OTPREMNICA_LINES = [
    ("59481164", Decimal("10")),
    ("59495642", Decimal("10")),
    ("38506529", Decimal("10")),
    ("38506420", Decimal("8")),
    ("59081067", Decimal("10")),
    ("59479024", Decimal("10")),
    ("38506000", Decimal("10")),
    ("3856008879493", Decimal("10")),
    ("38506284", Decimal("10")),
    ("59481744", Decimal("10")),
    ("3856008884831", Decimal("5")),
    ("3856008884862", Decimal("5")),
    ("3856008880758", Decimal("5")),
    ("3856008885012", Decimal("5")),
    ("3856008884923", Decimal("5")),
    ("3856008885074", Decimal("5")),
]


def _ordered_at():
    naive = datetime(ORDER_DATE.year, ORDER_DATE.month, ORDER_DATE.day, 12, 0, 0)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def ensure_twist_on_pricelist(*, supplier, komad_uom, dry_run, stdout, style):
    price_list = SupplierPriceList.objects.filter(
        supplier=supplier,
        name=PRICELIST_NAME,
        is_active=True,
    ).first()
    if not price_list:
        raise RuntimeError(
            f"Active pricelist {PRICELIST_NAME!r} not found for supplier {supplier}."
        )

    artikl = Artikl.objects.filter(code=TWIST_EAN).first()
    if not artikl:
        raise RuntimeError(f"Artikl with code={TWIST_EAN} not found.")

    if price_list.valid_from and price_list.valid_from > ORDER_DATE and not dry_run:
        price_list.valid_from = ORDER_DATE
        price_list.save(update_fields=["valid_from"])
        stdout.write(f"Adjusted pricelist id={price_list.id} valid_from to {ORDER_DATE}")

    if SupplierPriceItem.objects.filter(price_list=price_list, artikl=artikl).exists():
        stdout.write(f"Twist already on pricelist id={price_list.id}")
        return price_list

    if dry_run:
        stdout.write(
            f"DRY-RUN add Twist to pricelist id={price_list.id}: {TWIST_PRICE} EUR"
        )
        return price_list

    SupplierPriceItem.objects.create(
        price_list=price_list,
        artikl=artikl,
        unit_of_measure=komad_uom,
        price=TWIST_PRICE,
    )
    stdout.write(style.SUCCESS(f"Added Twist to pricelist id={price_list.id} at {TWIST_PRICE} EUR"))
    return price_list


class Command(BaseCommand):
    help = "Create confirmed TDR purchase order from otpremnica 9198533701 (Šank Gornji destination)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        supplier = Supplier.objects.filter(pk=TDR_SUPPLIER_ID).first()
        if not supplier:
            raise RuntimeError(f"Supplier id={TDR_SUPPLIER_ID} (TDR) not found.")

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

        ensure_twist_on_pricelist(
            supplier=supplier,
            komad_uom=komad_uom,
            dry_run=dry_run,
            stdout=self.stdout,
            style=self.style,
        )

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
