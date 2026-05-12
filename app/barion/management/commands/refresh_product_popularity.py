from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from barion.models import BarionCategorySettings, ProductPopularitySnapshot
from sales.models import SalesInvoiceItem


def _is_time_in_window(*, local_time, start, end) -> bool:
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end


def _is_timestamp_in_window(*, dt, start, end) -> bool:
    local_dt = timezone.localtime(dt)
    local_time = local_dt.timetz().replace(tzinfo=None)
    return _is_time_in_window(local_time=local_time, start=start, end=end)


class Command(BaseCommand):
    help = "Refresh Barion product popularity snapshot from sales quantities."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Override day lookback window in days. Default reads Barion settings.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute and print values without writing to database.",
        )
        parser.add_argument(
            "--night-weeks",
            type=int,
            default=None,
            help="Deprecated alias. If set, converts to night lookback days using weeks * 7.",
        )
        parser.add_argument(
            "--night-days",
            type=int,
            default=None,
            help="Override night lookback window in days. Default reads Barion settings.",
        )

    def handle(self, *args, **options):
        settings = BarionCategorySettings.get_solo()
        day_lookback_days = max(int(options["days"] or settings.day_lookback_days), 1)
        if options["night_days"] is not None:
            night_lookback_days = max(int(options["night_days"]), 1)
        elif options["night_weeks"] is not None:
            night_lookback_days = max(int(options["night_weeks"]) * 7, 1)
        else:
            night_lookback_days = max(int(settings.night_lookback_days), 1)
        dry_run = bool(options["dry_run"])
        since_day_date = timezone.localdate() - timedelta(days=day_lookback_days)
        since_night_dt = timezone.now() - timedelta(days=night_lookback_days)

        day_map = {}
        if settings.day_start == settings.day_end:
            self.stdout.write(self.style.WARNING("Day period has identical start/end; no day popularity will be counted."))
        else:
            day_items = (
                SalesInvoiceItem.objects.filter(
                    artikl_id__isnull=False,
                    quantity__gt=Decimal("0"),
                    invoice__issued_at__isnull=False,
                    invoice__issued_on__gte=since_day_date,
                )
                .select_related("invoice")
                .only("artikl_id", "quantity", "invoice__issued_at")
            )
            for item in day_items:
                issued_at = item.invoice.issued_at if item.invoice_id else None
                if issued_at is None or not _is_timestamp_in_window(
                    dt=issued_at,
                    start=settings.day_start,
                    end=settings.day_end,
                ):
                    continue
                qty = Decimal(str(item.quantity or "0.0000")).quantize(Decimal("0.0001"))
                day_map[item.artikl_id] = (day_map.get(item.artikl_id, Decimal("0.0000")) + qty).quantize(
                    Decimal("0.0001")
                )

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
            if issued_at is None or not _is_timestamp_in_window(
                dt=issued_at,
                start=settings.night_start,
                end=settings.night_end,
            ):
                continue
            qty = Decimal(str(item.quantity or "0.0000")).quantize(Decimal("0.0001"))
            night_map[item.artikl_id] = (night_map.get(item.artikl_id, Decimal("0.0000")) + qty).quantize(
                Decimal("0.0001")
            )

        artikl_ids = set(day_map.keys()) | set(night_map.keys())
        self.stdout.write(
            f"Rows to upsert: {len(artikl_ids)} (day_days={day_lookback_days}, night_days={night_lookback_days})"
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
                        "sold_qty_day": day_map.get(artikl_id, Decimal("0.0000")),
                        "sold_qty_night": night_map.get(artikl_id, Decimal("0.0000")),
                        "day_lookback_days": day_lookback_days,
                        "night_lookback_days": night_lookback_days,
                    },
                )

        self.stdout.write(self.style.SUCCESS("Product popularity snapshot refreshed."))
