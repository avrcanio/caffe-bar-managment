from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from artikli.models import Artikl, DrinkCategory
from sales.models import SalesInvoiceItem


class Command(BaseCommand):
    help = (
        "Postavlja sort_order za DrinkCategory na zadanom MPTT levelu prema ukupno prodanoj količini artikala "
        "(od najveće prema najmanjoj), bez dupliranja iste ciljne kategorije."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Broj dana unatrag za obračun prodaje (default: 30).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Samo ispisuje promjene bez upisa u bazu.",
        )
        parser.add_argument(
            "--target-level",
            type=int,
            default=2,
            help="MPTT level kategorije koja se sortira (default: 2).",
        )

    def _resolve_target_category(
        self,
        category: DrinkCategory | None,
        target_level: int,
    ) -> DrinkCategory | None:
        if not category:
            return None
        path = list(category.get_ancestors(include_self=True))
        if not path:
            return None
        for node in path:
            if node.level == target_level:
                return node
        # Ako grana nema target level, uzmi najdublji dostupni čvor.
        return path[-1]

    def handle(self, *args, **options):
        days = max(int(options["days"]), 1)
        dry_run = bool(options["dry_run"])
        target_level = max(int(options["target_level"]), 0)
        since_date = timezone.localdate() - timedelta(days=days)

        sales_rows = list(
            SalesInvoiceItem.objects.filter(
                artikl_id__isnull=False,
                quantity__gt=Decimal("0"),
                invoice__issued_on__gte=since_date,
            )
            .values("artikl_id")
            .annotate(total_qty=Sum("quantity"))
            .order_by("-total_qty")
        )

        artikli_by_id = Artikl.objects.select_related("drink_category").in_bulk(
            [row["artikl_id"] for row in sales_rows]
        )

        seen_target_ids = set()
        ordered_target = []
        for row in sales_rows:
            artikl = artikli_by_id.get(row["artikl_id"])
            target_category = self._resolve_target_category(
                getattr(artikl, "drink_category", None),
                target_level=target_level,
            )
            if not target_category or target_category.id in seen_target_ids:
                continue
            seen_target_ids.add(target_category.id)
            ordered_target.append(target_category)

        updates = []
        for index, category in enumerate(ordered_target, start=1):
            if category.sort_order != index:
                category.sort_order = index
                updates.append(category)

        self.stdout.write(
            self.style.NOTICE(
                f"Pronađeno kategorija iz prodaje: {len(ordered_target)} "
                f"(period: zadnjih {days} dana, target_level={target_level})."
            )
        )
        for index, category in enumerate(ordered_target[:20], start=1):
            self.stdout.write(f"- {category.id} | {category.name} | sort_order->{index}")

        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: bez upisa. Promjena: {len(updates)}"))
            return

        if updates:
            with transaction.atomic():
                DrinkCategory.objects.bulk_update(updates, ["sort_order"])
        self.stdout.write(self.style.SUCCESS(f"Ažuriran sort_order za {len(updates)} kategorija."))
