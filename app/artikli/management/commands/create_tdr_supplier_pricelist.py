from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import Artikl, UnitOfMeasureData
from contacts.models import Supplier
from orders.models import SupplierPriceItem, SupplierPriceList

TDR_SUPPLIER_ID = 5
KOMAD_UOM_RM_ID = 3
PRICELIST_NAME = "Cigarete - novi artikli 2026-06"
PRICELIST_VALID_FROM = date(2026, 6, 8)

# EAN -> price (EUR, Komad) per brand-tier heuristic from cjenik id=18
TWIST_EAN = "38506284"
TWIST_PRICE = Decimal("3.76")

TDR_PRICELIST_ITEMS = [
    ("38506529", Decimal("4.13")),  # Dunhill Opus Enigma Black
    ("38506420", Decimal("4.13")),  # Dunhill Signature Black
    ("59479024", Decimal("3.76")),  # Lucky Strike Amber
    ("3856008879493", Decimal("3.76")),  # Lucky Strike Rounded Tobacco
    ("59481744", Decimal("4.13")),  # Neo Sticks Tobacco Bright
    ("3856008884831", Decimal("3.61")),  # Velo Cherry Ice 6mg
    ("3856008884862", Decimal("3.61")),  # Velo Cherry Ice 10mg
    ("3856008880758", Decimal("3.61")),  # Velo Freezing Peppermint 17 mg
    ("3856008885012", Decimal("3.61")),  # Velo Smooth Peppermint 6mg
    ("3856008884923", Decimal("3.61")),  # Velo Smooth Peppermint 8mg
    ("3856008885074", Decimal("3.61")),  # Velo Peppermint Storm 17 mg
]


class Command(BaseCommand):
    help = "Create TDR supplier pricelist for 11 new cigarette artikli (brand-tier prices)."

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

        existing_list = SupplierPriceList.objects.filter(
            supplier=supplier,
            name=PRICELIST_NAME,
        ).first()
        if existing_list:
            self._add_missing_to_list(
                price_list=existing_list,
                komad_uom=komad_uom,
                dry_run=dry_run,
                extra_items=[(TWIST_EAN, TWIST_PRICE)],
            )
            return

        items_to_add = []
        skipped = 0
        for ean, price in TDR_PRICELIST_ITEMS:
            artikl = Artikl.objects.filter(code=ean).first()
            if not artikl:
                raise RuntimeError(f"Artikl with code={ean} not found.")

            already_priced = SupplierPriceItem.objects.filter(
                price_list__supplier=supplier,
                price_list__is_active=True,
                artikl=artikl,
            ).exists()
            if already_priced:
                self.stdout.write(f"SKIP artikl already on active TDR pricelist: {ean} ({artikl.name})")
                skipped += 1
                continue

            items_to_add.append((artikl, price))

        if not items_to_add:
            self.stdout.write(self.style.WARNING("Nothing to create. All items skipped."))
            return

        if dry_run:
            self.stdout.write(
                f"DRY-RUN create pricelist: supplier={supplier} name={PRICELIST_NAME!r} "
                f"valid_from={PRICELIST_VALID_FROM} items={len(items_to_add)}"
            )
            for artikl, price in items_to_add:
                self.stdout.write(f"  {artikl.code} {artikl.name!r} -> {price} EUR (Komad)")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry-run complete. would_create_list=1 would_create_items={len(items_to_add)} skipped={skipped}"
                )
            )
            return

        with transaction.atomic():
            price_list = SupplierPriceList.objects.create(
                supplier=supplier,
                name=PRICELIST_NAME,
                valid_from=PRICELIST_VALID_FROM,
                valid_to=None,
                currency="EUR",
                is_active=True,
            )
            SupplierPriceItem.objects.bulk_create(
                [
                    SupplierPriceItem(
                        price_list=price_list,
                        artikl=artikl,
                        unit_of_measure=komad_uom,
                        price=price,
                    )
                    for artikl, price in items_to_add
                ]
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Created pricelist id={price_list.id} name={PRICELIST_NAME!r} "
                f"items={len(items_to_add)} skipped={skipped}"
            )
        )
        for artikl, price in items_to_add:
            self.stdout.write(f"  {artikl.code} {artikl.name!r} -> {price} EUR")

    def _add_missing_to_list(self, *, price_list, komad_uom, dry_run, extra_items):
        added = 0
        skipped = 0
        for ean, price in extra_items:
            artikl = Artikl.objects.filter(code=ean).first()
            if not artikl:
                raise RuntimeError(f"Artikl with code={ean} not found.")
            if SupplierPriceItem.objects.filter(price_list=price_list, artikl=artikl).exists():
                self.stdout.write(f"SKIP already on list {price_list.id}: {ean} ({artikl.name})")
                skipped += 1
                continue
            if dry_run:
                self.stdout.write(
                    f"DRY-RUN add to list {price_list.id}: {artikl.name!r} -> {price} EUR"
                )
                added += 1
                continue
            SupplierPriceItem.objects.create(
                price_list=price_list,
                artikl=artikl,
                unit_of_measure=komad_uom,
                price=price,
            )
            self.stdout.write(f"ADDED to list {price_list.id}: {artikl.name!r} -> {price} EUR")
            added += 1
        label = "Dry-run" if dry_run else "Update"
        self.stdout.write(self.style.SUCCESS(f"{label} complete. added={added} skipped={skipped}"))
