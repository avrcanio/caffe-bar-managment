from __future__ import annotations

from datetime import timezone as dt_timezone

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from sales.models import SalesInvoice


def _reinterpret_as_local_clock_time(dt):
    """
    SalesInvoice.issued_at is stored UTC in DB (USE_TZ=True).
    Historical Remaris imports sometimes saved local clock time as if it was UTC.

    This function treats the existing *clock time* as local (settings.TIME_ZONE),
    then converts it back to proper UTC for storage.
    """
    if not dt:
        return dt
    if timezone.is_aware(dt):
        # Drop tzinfo so 01:50+00 becomes naive 01:50, then interpret as local.
        dt = dt.replace(tzinfo=None)
    # Make aware in local TZ, then normalize to UTC.
    local = timezone.make_aware(dt, timezone.get_current_timezone())
    return local.astimezone(dt_timezone.utc)


class Command(BaseCommand):
    help = "Fix SalesInvoice.issued_at by reinterpreting stored clock-time as local time and storing correct UTC."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply changes. Without this flag, runs a dry-run only.",
        )
        parser.add_argument(
            "--issued-on-from",
            type=str,
            default=None,
            help="Optional filter: SalesInvoice.issued_on >= YYYY-MM-DD",
        )
        parser.add_argument(
            "--issued-on-to",
            type=str,
            default=None,
            help="Optional filter: SalesInvoice.issued_on <= YYYY-MM-DD",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional limit for testing.",
        )

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        issued_on_from = options.get("issued_on_from")
        issued_on_to = options.get("issued_on_to")
        limit = options.get("limit")

        qs = SalesInvoice.objects.all().order_by("id").only("id", "rm_number", "issued_on", "issued_at")
        if issued_on_from:
            qs = qs.filter(issued_on__gte=issued_on_from)
        if issued_on_to:
            qs = qs.filter(issued_on__lte=issued_on_to)
        if limit:
            qs = qs[:limit]

        total = qs.count()
        changed = 0
        unchanged = 0

        # Track shifts so we can spot weirdness (e.g. DST).
        shifts = {}

        updates: list[SalesInvoice] = []
        for inv in qs.iterator(chunk_size=2000):
            old = inv.issued_at
            new = _reinterpret_as_local_clock_time(old)
            if new != old:
                changed += 1
                delta = (new - old).total_seconds()
                shifts[delta] = shifts.get(delta, 0) + 1
                if apply:
                    inv.issued_at = new
                    updates.append(inv)
            else:
                unchanged += 1

            if apply and len(updates) >= 2000:
                SalesInvoice.objects.bulk_update(updates, ["issued_at"], batch_size=2000)
                updates = []

        if apply and updates:
            SalesInvoice.objects.bulk_update(updates, ["issued_at"], batch_size=2000)

        # Final stats
        self.stdout.write(f"Total checked: {total}")
        self.stdout.write(f"Would change: {changed}")
        self.stdout.write(f"Unchanged: {unchanged}")
        self.stdout.write("Shift seconds -> count: " + str(dict(sorted(shifts.items(), key=lambda x: x[0]))))
        self.stdout.write("APPLIED" if apply else "DRY-RUN (no changes applied)")

