from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import Artikl, Category, UnitOfMeasureData
from contacts.models import Supplier
from orders.models import SupplierPriceItem, SupplierPriceList
from sales.models import SalesPriceItem, SalesPriceList

KOKTEL_SUPPLIER_ID = 3
KOKTEL_MAIN_PRICELIST_ID = 1
GAZIRANI_SOKOVI_CATEGORY_ID = 9
SALES_PRICELIST_ID = 4
KOMAD_UOM_RM_ID = 3

PRICELIST_NAME = "Gazirani sokovi"
PRICELIST_VALID_FROM = date(2026, 6, 21)

SPRITE_CODE = "54031807"
SPRITE_SUPPLIER_PRICE = Decimal("1.02")
SPRITE_SALES_PRICE = Decimal("3.00")

THOMAS_HENRY_CODE = "4251760800065"
THOMAS_HENRY_SUPPLIER_PRICE = Decimal("1.62")
THOMAS_HENRY_SALES_PRICE = Decimal("4.70")


class Command(BaseCommand):
    help = (
        "Create KOKTEL supplier pricelist 'Gazirani sokovi', move existing items from pl=1, "
        "add Sprite and Thomas Henry, and set sales prices on 'Sokovi gazirani'."
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

        category = Category.objects.filter(pk=GAZIRANI_SOKOVI_CATEGORY_ID).first()
        if not category:
            raise RuntimeError(
                f"Category id={GAZIRANI_SOKOVI_CATEGORY_ID} (Gazirani sokovi) not found."
            )

        komad_uom = UnitOfMeasureData.objects.filter(rm_id=KOMAD_UOM_RM_ID).first()
        if not komad_uom:
            raise RuntimeError(f"Required UOM missing: Komad rm_id={KOMAD_UOM_RM_ID}.")

        main_pricelist = SupplierPriceList.objects.filter(
            pk=KOKTEL_MAIN_PRICELIST_ID,
            supplier=supplier,
        ).first()
        if not main_pricelist:
            raise RuntimeError(
                f"KOKTEL main pricelist id={KOKTEL_MAIN_PRICELIST_ID} not found."
            )

        sales_pricelist = SalesPriceList.objects.filter(pk=SALES_PRICELIST_ID).first()
        if not sales_pricelist:
            raise RuntimeError(f"Sales pricelist id={SALES_PRICELIST_ID} not found.")

        sprite = Artikl.objects.filter(code=SPRITE_CODE).first()
        if not sprite:
            raise RuntimeError(f"Artikl with code={SPRITE_CODE} (Sprite) not found.")

        thomas_henry = Artikl.objects.filter(code=THOMAS_HENRY_CODE).first()
        if not thomas_henry:
            raise RuntimeError(
                f"Artikl with code={THOMAS_HENRY_CODE} (Thomas Henry) not found."
            )

        existing_items = list(
            SupplierPriceItem.objects.filter(
                price_list=main_pricelist,
                artikl__category=category,
            )
            .select_related("artikl", "unit_of_measure")
            .order_by("artikl__name")
        )

        if SupplierPriceList.objects.filter(
            supplier=supplier,
            name=PRICELIST_NAME,
            is_active=True,
        ).exists():
            raise RuntimeError(
                f"Active KOKTEL pricelist named {PRICELIST_NAME!r} already exists."
            )

        def run():
            moved = 0
            added = 0
            removed = 0
            sales_updated = 0

            if dry_run:
                self.stdout.write(
                    f"DRY-RUN create pricelist: supplier={supplier.name} "
                    f"name={PRICELIST_NAME!r} valid_from={PRICELIST_VALID_FROM}"
                )
            else:
                price_list = SupplierPriceList.objects.create(
                    supplier=supplier,
                    name=PRICELIST_NAME,
                    valid_from=PRICELIST_VALID_FROM,
                    valid_to=None,
                    currency="EUR",
                    is_active=True,
                )
                self.stdout.write(f"CREATED pricelist id={price_list.id} name={PRICELIST_NAME!r}")

            for item in existing_items:
                uom = item.unit_of_measure or komad_uom
                if dry_run:
                    self.stdout.write(
                        f"DRY-RUN move: {item.artikl.name} price={item.price} EUR "
                        f"from pl={main_pricelist.id} -> new pricelist"
                    )
                else:
                    SupplierPriceItem.objects.create(
                        price_list=price_list,
                        artikl=item.artikl,
                        unit_of_measure=uom,
                        price=item.price,
                    )
                    item.delete()
                    self.stdout.write(
                        f"MOVED {item.artikl.name} price={item.price} EUR "
                        f"(removed from pl={main_pricelist.id})"
                    )
                moved += 1
                removed += 1

            new_items = [
                (sprite, SPRITE_SUPPLIER_PRICE),
                (thomas_henry, THOMAS_HENRY_SUPPLIER_PRICE),
            ]
            for artikl, price in new_items:
                if dry_run:
                    self.stdout.write(
                        f"DRY-RUN add supplier item: {artikl.name} price={price} EUR (Komad)"
                    )
                else:
                    SupplierPriceItem.objects.create(
                        price_list=price_list,
                        artikl=artikl,
                        unit_of_measure=komad_uom,
                        price=price,
                    )
                    self.stdout.write(f"ADDED supplier item: {artikl.name} price={price} EUR")
                added += 1

            sales_updates = [
                (sprite, SPRITE_SALES_PRICE),
                (thomas_henry, THOMAS_HENRY_SALES_PRICE),
            ]
            for artikl, price in sales_updates:
                if dry_run:
                    self.stdout.write(
                        f"DRY-RUN sales price: {artikl.name} -> {price} EUR "
                        f"on pricelist id={sales_pricelist.id} ({sales_pricelist.name})"
                    )
                else:
                    SalesPriceItem.objects.update_or_create(
                        price_list=sales_pricelist,
                        artikl=artikl,
                        defaults={
                            "unit_price_gross": price,
                            "is_active": True,
                        },
                    )
                    self.stdout.write(
                        f"SET sales price: {artikl.name} -> {price} EUR "
                        f"on pricelist id={sales_pricelist.id}"
                    )
                sales_updated += 1

            label = "Dry-run complete" if dry_run else "Complete"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{label}. moved={moved} added={added} removed={removed} "
                    f"sales_updated={sales_updated}"
                )
            )

        if dry_run:
            run()
        else:
            with transaction.atomic():
                run()
