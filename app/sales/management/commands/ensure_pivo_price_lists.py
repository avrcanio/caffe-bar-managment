from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from sales.models import SalesPriceItem, SalesPriceList

KONCERT_PRICE_LIST_ID = 9
REMARIS_REGULAR_PRICE_LIST_ID = 10
REMARIS_KONCERT_PRICE_LIST_ID = 9

# Regular (redovni POS) cijene piva — izvorno na PL 9 prije Koncert cjenika.
REGULAR_BEER_PRICES = {
    "8714800003995": Decimal("3.20"),  # Bavaria bezalkoholno
    "3850131290002": Decimal("3.00"),  # Becks
    "75032814": Decimal("5.50"),  # Corona
    "4072700003649": Decimal("5.50"),  # Franziskaner
    "8600105005867": Decimal("4.50"),  # Madri
    "38501708": Decimal("3.40"),  # Ožujsko
    "3850131481011": Decimal("3.80"),  # Stella
}


class Command(BaseCommand):
    help = (
        "Ensure separate Mozart price lists: Pivo (regular, Remaris 10) "
        "and Pivo Koncert (Remaris 9)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        koncert_list = SalesPriceList.objects.filter(pk=KONCERT_PRICE_LIST_ID).first()
        if not koncert_list:
            raise RuntimeError(f"Koncert price list id={KONCERT_PRICE_LIST_ID} not found.")

        regular_list = SalesPriceList.objects.filter(
            name="Pivo",
            remaris_price_list_id=REMARIS_REGULAR_PRICE_LIST_ID,
        ).exclude(pk=koncert_list.pk).first()

        def run():
            nonlocal regular_list

            if koncert_list.name != "Pivo Koncert":
                if dry_run:
                    self.stdout.write(
                        f"DRY-RUN rename PL {koncert_list.id}: "
                        f"{koncert_list.name!r} -> 'Pivo Koncert'"
                    )
                else:
                    koncert_list.name = "Pivo Koncert"
                    koncert_list.remaris_price_list_id = REMARIS_KONCERT_PRICE_LIST_ID
                    koncert_list.remaris_sync_transfer_pos = False
                    koncert_list.save(
                        update_fields=[
                            "name",
                            "remaris_price_list_id",
                            "remaris_sync_transfer_pos",
                        ]
                    )
                    self.stdout.write(f"Updated Koncert list id={koncert_list.id}")

            if not regular_list:
                if dry_run:
                    self.stdout.write(
                        "DRY-RUN create SalesPriceList name='Pivo' remaris_id=10"
                    )
                    regular_list = koncert_list
                else:
                    regular_list = SalesPriceList.objects.create(
                        name="Pivo",
                        is_active=True,
                        is_default=False,
                        valid_from=koncert_list.valid_from or timezone.now(),
                        valid_to=None,
                        warehouse=koncert_list.warehouse,
                        pos=koncert_list.pos,
                        remaris_price_list_id=REMARIS_REGULAR_PRICE_LIST_ID,
                        remaris_sync_transfer_pos=True,
                    )
                    self.stdout.write(f"Created regular Pivo list id={regular_list.id}")

            koncert_items = list(
                koncert_list.items.select_related("artikl").order_by("artikl__name")
            )
            if not koncert_items:
                raise RuntimeError(f"Koncert list id={koncert_list.id} has no items.")

            created = 0
            updated = 0
            for koncert_item in koncert_items:
                code = koncert_item.artikl.code or ""
                regular_price = REGULAR_BEER_PRICES.get(code)
                if regular_price is None:
                    regular_price = koncert_item.unit_price_gross
                    self.stdout.write(
                        self.style.WARNING(
                            f"No regular price map for {code}; using koncert price {regular_price}"
                        )
                    )

                if dry_run and regular_list is koncert_list:
                    self.stdout.write(
                        f"DRY-RUN item {code} {koncert_item.artikl.name!r} -> {regular_price} EUR"
                    )
                    created += 1
                    continue

                existing = SalesPriceItem.objects.filter(
                    price_list=regular_list,
                    artikl=koncert_item.artikl,
                ).first()
                if existing:
                    if existing.unit_price_gross != regular_price:
                        if dry_run:
                            self.stdout.write(
                                f"DRY-RUN update {code}: {existing.unit_price_gross} -> {regular_price}"
                            )
                        else:
                            existing.unit_price_gross = regular_price
                            existing.is_active = True
                            existing.save(update_fields=["unit_price_gross", "is_active"])
                        updated += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        f"DRY-RUN create item {code} {koncert_item.artikl.name!r} -> {regular_price}"
                    )
                    created += 1
                    continue

                SalesPriceItem.objects.create(
                    price_list=regular_list,
                    artikl=koncert_item.artikl,
                    unit_price_gross=regular_price,
                    is_active=True,
                )
                created += 1

            label = "Dry-run complete" if dry_run else "Complete"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{label}. regular_list_id={getattr(regular_list, 'id', None)} "
                    f"created={created} updated={updated} koncert_list_id={koncert_list.id}"
                )
            )

        if dry_run:
            run()
        else:
            with transaction.atomic():
                run()
