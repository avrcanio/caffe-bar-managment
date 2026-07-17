from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import Artikl, UnitOfMeasureData
from contacts.models import Supplier
from orders.models import SupplierPriceItem, SupplierPriceList

FRUCTUS_SUPPLIER_ID = 14
KG_UOM_RM_ID = 1
PRICELIST_NAME = "Voće"
PRICELIST_VALID_FROM = date(2026, 7, 1)

# Artikl code -> price (EUR, Kg) from Fructus otpremnica 2744/PV1/1
FRUCTUS_VOCE_ITEMS = [
    ("16769594", Decimal("1.00")),  # Lubenica #1313
    ("27809119", Decimal("1.60")),  # Dinja #1314
]


class Command(BaseCommand):
    help = "Create Fructus supplier pricelist for Voće (Lubenica, Dinja) from otpremnica 2744."

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

        existing_list = SupplierPriceList.objects.filter(
            supplier=supplier,
            name=PRICELIST_NAME,
        ).first()
        if existing_list:
            self._add_missing_to_list(
                price_list=existing_list,
                kg_uom=kg_uom,
                dry_run=dry_run,
            )
            return

        items_to_add = []
        skipped = 0
        for code, price in FRUCTUS_VOCE_ITEMS:
            artikl = Artikl.objects.filter(code=code).first()
            if not artikl:
                raise RuntimeError(f"Artikl with code={code} not found.")

            already_priced = SupplierPriceItem.objects.filter(
                price_list__supplier=supplier,
                price_list__is_active=True,
                artikl=artikl,
            ).exists()
            if already_priced:
                self.stdout.write(
                    f"SKIP artikl already on active Fructus pricelist: {code} ({artikl.name})"
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
                self.stdout.write(f"  {artikl.code} {artikl.name!r} -> {price} EUR (Kg)")
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
                        unit_of_measure=kg_uom,
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

    def _add_missing_to_list(self, *, price_list, kg_uom, dry_run):
        added = 0
        skipped = 0
        for code, price in FRUCTUS_VOCE_ITEMS:
            artikl = Artikl.objects.filter(code=code).first()
            if not artikl:
                raise RuntimeError(f"Artikl with code={code} not found.")
            if SupplierPriceItem.objects.filter(price_list=price_list, artikl=artikl).exists():
                self.stdout.write(f"SKIP already on list {price_list.id}: {code} ({artikl.name})")
                skipped += 1
                continue
            if dry_run:
                self.stdout.write(
                    f"DRY-RUN add to list {price_list.id}: {artikl.name!r} -> {price} EUR (Kg)"
                )
                added += 1
                continue
            SupplierPriceItem.objects.create(
                price_list=price_list,
                artikl=artikl,
                unit_of_measure=kg_uom,
                price=price,
            )
            self.stdout.write(f"ADDED to list {price_list.id}: {artikl.name!r} -> {price} EUR")
            added += 1
        label = "Dry-run" if dry_run else "Update"
        self.stdout.write(self.style.SUCCESS(f"{label} complete. added={added} skipped={skipped}"))
