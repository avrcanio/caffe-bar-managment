from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import Artikl, UnitOfMeasureData
from contacts.models import Supplier
from orders.models import SupplierPriceItem, SupplierPriceList

ATLANTIC_SUPPLIER_ID = 13
KOMAD_UOM_RM_ID = 3
PRICELIST_NAME = "Cedevita"
PRICELIST_VALID_FROM = date(2026, 5, 1)

ATLANTIC_CEDEVITA_ITEMS = [
    ("3850322009154", Decimal("0.46")),  # Cedevita Limun 19 gr
    ("3850322009406", Decimal("0.46")),  # Cedevita Bazga Limun 19g
    ("3850322016343", Decimal("0.46")),  # Cedevita Ananas Mango 19gr
    ("3850322016978", Decimal("0.46")),  # Cedevita Limunska Trava 19gr
]


class Command(BaseCommand):
    help = "Create Atlantic Trade supplier pricelist for Cedevita artikli."

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

        existing_list = SupplierPriceList.objects.filter(
            supplier=supplier,
            name=PRICELIST_NAME,
        ).first()
        if existing_list:
            self._add_missing_to_list(
                price_list=existing_list,
                komad_uom=komad_uom,
                dry_run=dry_run,
            )
            return

        items_to_add = []
        skipped = 0
        for ean, price in ATLANTIC_CEDEVITA_ITEMS:
            artikl = Artikl.objects.filter(code=ean).first()
            if not artikl:
                raise RuntimeError(f"Artikl with code={ean} not found.")

            already_priced = SupplierPriceItem.objects.filter(
                price_list__supplier=supplier,
                price_list__is_active=True,
                artikl=artikl,
            ).exists()
            if already_priced:
                self.stdout.write(
                    f"SKIP artikl already on active Atlantic pricelist: {ean} ({artikl.name})"
                )
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

    def _add_missing_to_list(self, *, price_list, komad_uom, dry_run):
        added = 0
        skipped = 0
        for ean, price in ATLANTIC_CEDEVITA_ITEMS:
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
