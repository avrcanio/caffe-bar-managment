from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import Artikl, ArtiklPackagingLevel, Category, UnitOfMeasureData
from configuration.models import ConsumptionTaxCategory
from contacts.models import Supplier
from orders.models import SupplierPriceItem, SupplierPriceList

KOKTEL_SUPPLIER_ID = 3
SVIJETLO_PIVO_CATEGORY_ID = 66
PNP_BEER_ID = 2
KOMAD_UOM_RM_ID = 3
GAJBA_UOM_RM_ID = 8
GAJBA_CONTAINS_PREVIOUS = Decimal("20")

ARTIKL_CODE = "8600105005867"
ARTIKL_NAME = "Madrí Excepcional pivo 0,4 l"
PRICE = Decimal("1.10")
PRICELIST_VALID_FROM = date(2026, 6, 12)
PRICELIST_NAME = "Madrí 0,4 l"


class Command(BaseCommand):
    help = "Create Madrí Excepcional artikl (Komad->20/Gajba) and KOKTEL supplier pricelist item."

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

        category = Category.objects.filter(pk=SVIJETLO_PIVO_CATEGORY_ID).first()
        if not category:
            raise RuntimeError(
                f"Category id={SVIJETLO_PIVO_CATEGORY_ID} (Svijetlo pivo) not found."
            )

        pnp_category = ConsumptionTaxCategory.objects.filter(pk=PNP_BEER_ID).first()
        if not pnp_category:
            raise RuntimeError(f"PnP category id={PNP_BEER_ID} (Pivo) not found.")

        komad_uom = UnitOfMeasureData.objects.filter(rm_id=KOMAD_UOM_RM_ID).first()
        gajba_uom = UnitOfMeasureData.objects.filter(rm_id=GAJBA_UOM_RM_ID).first()
        if not komad_uom or not gajba_uom:
            raise RuntimeError(
                f"Required UOM missing: Komad rm_id={KOMAD_UOM_RM_ID}, "
                f"Gajba rm_id={GAJBA_UOM_RM_ID}."
            )

        def run():
            artikl_created = False
            price_created = False

            artikl = Artikl.objects.filter(code=ARTIKL_CODE).first()
            if artikl:
                self.stdout.write(f"SKIP artikl already exists: {ARTIKL_CODE} ({artikl.name})")
            elif dry_run:
                self.stdout.write(
                    f"DRY-RUN create artikl: name={ARTIKL_NAME!r} code={ARTIKL_CODE} "
                    f"category=Svijetlo pivo packaging=komad->20/gajba"
                )
                artikl_created = True
            else:
                artikl = Artikl.objects.create(
                    name=ARTIKL_NAME,
                    code=ARTIKL_CODE,
                    category=category,
                    pnp_category=pnp_category,
                    is_sellable=True,
                    is_stock_item=True,
                    rm_id=None,
                )
                ArtiklPackagingLevel.objects.create(
                    artikl=artikl,
                    unit_of_measure=komad_uom,
                    sort_order=0,
                    contains_previous=None,
                )
                ArtiklPackagingLevel.objects.create(
                    artikl=artikl,
                    unit_of_measure=gajba_uom,
                    sort_order=1,
                    contains_previous=GAJBA_CONTAINS_PREVIOUS,
                )
                self.stdout.write(
                    f"CREATED artikl id={artikl.id} name={ARTIKL_NAME!r} code={ARTIKL_CODE} "
                    f"path={artikl.packaging_path_summary()}"
                )
                artikl_created = True

            price_filter = {
                "price_list__supplier": supplier,
                "price_list__is_active": True,
            }
            if artikl:
                price_filter["artikl"] = artikl
            else:
                price_filter["artikl__code"] = ARTIKL_CODE

            if SupplierPriceItem.objects.filter(**price_filter).exists():
                self.stdout.write(f"SKIP price already on active KOKTEL pricelist: {ARTIKL_CODE}")
            elif dry_run:
                self.stdout.write(
                    f"DRY-RUN create pricelist: supplier={supplier.name} "
                    f"valid_from={PRICELIST_VALID_FROM} price={PRICE} EUR (Komad)"
                )
            else:
                if not artikl:
                    raise RuntimeError("Artikl missing after create step.")

                price_list = SupplierPriceList.objects.create(
                    supplier=supplier,
                    name=PRICELIST_NAME,
                    valid_from=PRICELIST_VALID_FROM,
                    valid_to=None,
                    currency="EUR",
                    is_active=True,
                )
                SupplierPriceItem.objects.create(
                    price_list=price_list,
                    artikl=artikl,
                    unit_of_measure=komad_uom,
                    price=PRICE,
                )
                self.stdout.write(
                    f"CREATED pricelist id={price_list.id} item price={PRICE} EUR (Komad)"
                )
                price_created = True

            label = "Dry-run complete" if dry_run else "Complete"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{label}. artikl_created={artikl_created} price_created={price_created}"
                )
            )

        if dry_run:
            run()
        else:
            with transaction.atomic():
                run()
