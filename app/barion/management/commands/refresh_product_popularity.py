from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from barion.models import ProductPopularitySnapshot
from sales.models import SalesInvoiceItem


class Command(BaseCommand):
    help = "Refresh Barion product popularity snapshot from sales quantities."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Rolling window in days (default: 30).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute and print values without writing to database.",
        )

    def handle(self, *args, **options):
        days = max(int(options["days"]), 1)
        dry_run = bool(options["dry_run"])
        since_date = timezone.localdate() - timedelta(days=days)

        rows = list(
            SalesInvoiceItem.objects.filter(
                artikl_id__isnull=False,
                quantity__gt=Decimal("0"),
                invoice__issued_on__gte=since_date,
            )
            .values("artikl_id")
            .annotate(sold_qty=Sum("quantity"))
        )

        self.stdout.write(f"Rows to upsert: {len(rows)} (days={days})")
        for row in sorted(rows, key=lambda x: x["sold_qty"], reverse=True)[:20]:
            self.stdout.write(f"- artikl={row['artikl_id']} sold_qty={row['sold_qty']}")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: snapshot not updated."))
            return

        with transaction.atomic():
            ProductPopularitySnapshot.objects.exclude(
                artikl_id__in=[row["artikl_id"] for row in rows]
            ).delete()
            for row in rows:
                ProductPopularitySnapshot.objects.update_or_create(
                    artikl_id=row["artikl_id"],
                    defaults={
                        "sold_qty_30d": row["sold_qty"],
                        "window_days": days,
                    },
                )

        self.stdout.write(self.style.SUCCESS("Product popularity snapshot refreshed."))
