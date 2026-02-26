from datetime import time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from barion.models import ProductPopularitySnapshot
from sales.models import SalesInvoiceItem


def _is_weekend_night_timestamp(dt) -> bool:
    local_dt = timezone.localtime(dt)
    weekday = local_dt.weekday()  # Monday=0 ... Sunday=6
    local_time = local_dt.timetz().replace(tzinfo=None)
    start = time(20, 0, 0)
    end = time(2, 0, 0)
    if weekday == 4:  # Friday
        return local_time >= start
    if weekday == 5:  # Saturday
        return local_time < end or local_time >= start
    if weekday == 6:  # Sunday
        return local_time < end
    return False


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
        parser.add_argument(
            "--night-weeks",
            type=int,
            default=8,
            help="Rolling weekend window in weeks for night popularity (default: 8).",
        )

    def handle(self, *args, **options):
        days = max(int(options["days"]), 1)
        night_weeks = max(int(options["night_weeks"]), 1)
        dry_run = bool(options["dry_run"])
        since_date = timezone.localdate() - timedelta(days=days)
        since_night_dt = timezone.now() - timedelta(weeks=night_weeks)

        day_rows = list(
            SalesInvoiceItem.objects.filter(
                artikl_id__isnull=False,
                quantity__gt=Decimal("0"),
                invoice__issued_on__gte=since_date,
            )
            .values("artikl_id")
            .annotate(sold_qty=Sum("quantity"))
        )

        day_map = {
            row["artikl_id"]: Decimal(str(row["sold_qty"] or "0.0000")).quantize(Decimal("0.0001"))
            for row in day_rows
        }
        night_map = {}
        night_items = (
            SalesInvoiceItem.objects.filter(
                artikl_id__isnull=False,
                quantity__gt=Decimal("0"),
                invoice__issued_at__gte=since_night_dt,
            )
            .select_related("invoice")
            .only("artikl_id", "quantity", "invoice__issued_at")
        )
        for item in night_items:
            issued_at = item.invoice.issued_at if item.invoice_id else None
            if issued_at is None or not _is_weekend_night_timestamp(issued_at):
                continue
            qty = Decimal(str(item.quantity or "0.0000")).quantize(Decimal("0.0001"))
            night_map[item.artikl_id] = (night_map.get(item.artikl_id, Decimal("0.0000")) + qty).quantize(
                Decimal("0.0001")
            )

        artikl_ids = set(day_map.keys()) | set(night_map.keys())
        self.stdout.write(
            f"Rows to upsert: {len(artikl_ids)} (days={days}, night_weeks={night_weeks})"
        )
        top_night = sorted(night_map.items(), key=lambda x: x[1], reverse=True)[:20]
        for artikl_id, sold_qty in top_night:
            self.stdout.write(f"- night artikl={artikl_id} sold_qty={sold_qty}")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: snapshot not updated."))
            return

        with transaction.atomic():
            ProductPopularitySnapshot.objects.exclude(
                artikl_id__in=list(artikl_ids)
            ).delete()
            for artikl_id in artikl_ids:
                ProductPopularitySnapshot.objects.update_or_create(
                    artikl_id=artikl_id,
                    defaults={
                        "sold_qty_30d": day_map.get(artikl_id, Decimal("0.0000")),
                        "sold_qty_night_weekend": night_map.get(artikl_id, Decimal("0.0000")),
                        "window_days": days,
                    },
                )

        self.stdout.write(self.style.SUCCESS("Product popularity snapshot refreshed."))
