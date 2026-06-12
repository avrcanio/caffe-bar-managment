from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import Artikl, Category
from sales.models import SalesPriceItem, SalesPriceList

REGULAR_PRICE_LIST_ID = 10
KONCERT_LIST_NAME = "Cigarete Koncert"
REMARIS_REGULAR = 10
REMARIS_KONCERT = 9
KONCERT_MULTIPLIER = Decimal("1.10")
CIGARETE_CATEGORY_ID = 155

# artikl_id -> regular gross price (EUR) from menu photos
REGULAR_ITEMS_BY_ARTIKL_ID = {
    1296: Decimal("5.50"),  # Dunhill Opus Enigma Black
    1297: Decimal("5.20"),  # Dunhill Signature Black
    430: Decimal("4.90"),  # LUCKIE RESIZED BLUE
    1298: Decimal("4.90"),  # Lucky Strike Amber
    233: Decimal("4.70"),  # Lucky Strike Twist
    1300: Decimal("4.50"),  # Neo Sticks Tobacco Bright
    1299: Decimal("4.20"),  # Lucky Strike Rounded Tobacco
    324: Decimal("7.70"),  # VUSE GO
}

# Generic VELO POS items (Remaris product.json codes)
VELO_ARTIKLS = [
    ("232323", "VELO INTENSE", Decimal("4.50")),
    ("3412312", "VELO CLASSIC", Decimal("4.50")),
    ("41323216124", "VELO SMOOTH", Decimal("3.60")),
]


class Command(BaseCommand):
    help = (
        "Ensure Cigarete sales price list (PL 10) has menu prices and "
        "Cigarete Koncert copy with +10% (Remaris 9)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        regular_list = SalesPriceList.objects.filter(pk=REGULAR_PRICE_LIST_ID).first()
        if not regular_list:
            raise RuntimeError(f"Regular price list id={REGULAR_PRICE_LIST_ID} not found.")

        category = Category.objects.filter(pk=CIGARETE_CATEGORY_ID).first()

        def upsert_price_item(price_list, artikl, price):
            existing = SalesPriceItem.objects.filter(
                price_list=price_list,
                artikl=artikl,
            ).first()
            if existing:
                if existing.unit_price_gross != price or not existing.is_active:
                    if dry_run:
                        self.stdout.write(
                            f"DRY-RUN update PL{price_list.id} "
                            f"{artikl.code} {artikl.name!r}: "
                            f"{existing.unit_price_gross} -> {price}"
                        )
                        return "updated"
                    existing.unit_price_gross = price
                    existing.is_active = True
                    existing.save(update_fields=["unit_price_gross", "is_active"])
                    return "updated"
                return "unchanged"

            if dry_run:
                self.stdout.write(
                    f"DRY-RUN create PL{price_list.id} "
                    f"{artikl.code} {artikl.name!r} -> {price}"
                )
                return "created"

            SalesPriceItem.objects.create(
                price_list=price_list,
                artikl=artikl,
                unit_price_gross=price,
                is_active=True,
            )
            return "created"

        def ensure_velo_artikls():
            created = 0
            artikls = {}
            for code, name, _price in VELO_ARTIKLS:
                artikl = Artikl.objects.filter(code=code).first()
                if artikl:
                    artikls[code] = artikl
                    continue

                if dry_run:
                    self.stdout.write(f"DRY-RUN create artikl code={code} name={name!r}")
                    artikls[code] = Artikl(code=code, name=name)
                    created += 1
                    continue

                artikl = Artikl.objects.create(
                    name=name,
                    code=code,
                    category=category,
                    is_sellable=True,
                    is_stock_item=False,
                )
                artikls[code] = artikl
                created += 1
                self.stdout.write(f"Created artikl id={artikl.id} code={code} name={name!r}")

            return artikls, created

        def ensure_koncert_list():
            koncert_list = SalesPriceList.objects.filter(name=KONCERT_LIST_NAME).first()
            if koncert_list:
                if (
                    koncert_list.remaris_price_list_id != REMARIS_KONCERT
                    or koncert_list.remaris_sync_transfer_pos
                ):
                    if dry_run:
                        self.stdout.write(
                            f"DRY-RUN update {KONCERT_LIST_NAME!r} id={koncert_list.id}: "
                            f"remaris={REMARIS_KONCERT}, sync_transfer=False"
                        )
                    else:
                        koncert_list.remaris_price_list_id = REMARIS_KONCERT
                        koncert_list.remaris_sync_transfer_pos = False
                        koncert_list.save(
                            update_fields=[
                                "remaris_price_list_id",
                                "remaris_sync_transfer_pos",
                            ]
                        )
                        self.stdout.write(f"Updated koncert list id={koncert_list.id}")
                return koncert_list

            if dry_run:
                self.stdout.write(
                    f"DRY-RUN create SalesPriceList name={KONCERT_LIST_NAME!r} "
                    f"remaris_id={REMARIS_KONCERT}"
                )
                return None

            koncert_list = SalesPriceList.objects.create(
                name=KONCERT_LIST_NAME,
                is_active=True,
                is_default=False,
                valid_from=regular_list.valid_from,
                valid_to=None,
                warehouse=regular_list.warehouse,
                pos=regular_list.pos,
                remaris_price_list_id=REMARIS_KONCERT,
                remaris_sync_transfer_pos=False,
            )
            self.stdout.write(f"Created koncert list id={koncert_list.id}")
            return koncert_list

        def run():
            velo_artikls, velo_created = ensure_velo_artikls()

            regular_created = 0
            regular_updated = 0
            for artikl_id, price in REGULAR_ITEMS_BY_ARTIKL_ID.items():
                artikl = Artikl.objects.filter(pk=artikl_id).first()
                if not artikl:
                    raise RuntimeError(f"Artikl id={artikl_id} not found.")
                result = upsert_price_item(regular_list, artikl, price)
                if result == "created":
                    regular_created += 1
                elif result == "updated":
                    regular_updated += 1

            for code, _name, price in VELO_ARTIKLS:
                artikl = velo_artikls.get(code)
                if artikl is None or not artikl.pk:
                    if dry_run:
                        regular_created += 1
                        continue
                    artikl = Artikl.objects.filter(code=code).first()
                if not artikl:
                    raise RuntimeError(f"VELO artikl code={code} missing after ensure.")
                result = upsert_price_item(regular_list, artikl, price)
                if result == "created":
                    regular_created += 1
                elif result == "updated":
                    regular_updated += 1

            koncert_list = ensure_koncert_list()

            koncert_created = 0
            koncert_updated = 0
            regular_items = list(
                regular_list.items.select_related("artikl").order_by("artikl__name")
            )
            if not regular_items and not dry_run:
                raise RuntimeError(f"Regular list id={regular_list.id} has no items.")

            for item in regular_items:
                koncert_price = (item.unit_price_gross * KONCERT_MULTIPLIER).quantize(
                    Decimal("0.01")
                )
                if dry_run and koncert_list is None:
                    self.stdout.write(
                        f"DRY-RUN koncert {item.artikl.code} {item.artikl.name!r} "
                        f"{item.unit_price_gross} -> {koncert_price}"
                    )
                    koncert_created += 1
                    continue

                result = upsert_price_item(koncert_list, item.artikl, koncert_price)
                if result == "created":
                    koncert_created += 1
                elif result == "updated":
                    koncert_updated += 1

            label = "Dry-run complete" if dry_run else "Complete"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{label}. regular_list_id={regular_list.id} "
                    f"regular_items={len(regular_items)} "
                    f"regular_created={regular_created} regular_updated={regular_updated} "
                    f"velo_artikls_created={velo_created} "
                    f"koncert_list_id={getattr(koncert_list, 'id', None)} "
                    f"koncert_created={koncert_created} koncert_updated={koncert_updated}"
                )
            )

        if dry_run:
            run()
        else:
            with transaction.atomic():
                run()
