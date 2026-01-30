from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from artikli.models import Artikl
from stock.models import StockCostSnapshot, StockLot, WarehouseId


class Command(BaseCommand):
    help = "Recalculate stock cost snapshots for a warehouse and date."

    def add_arguments(self, parser):
        parser.add_argument("--date", required=True, help="Datum u formatu YYYY-MM-DD.")
        parser.add_argument("--warehouse", required=True, type=int, help="Warehouse rm_id.")

    def handle(self, *args, **options):
        date_str = options["date"]
        as_of_date = parse_date(date_str)
        if not as_of_date:
            raise CommandError("Neispravan datum. Ocekivano YYYY-MM-DD.")

        warehouse_rm_id = options["warehouse"]
        warehouse = WarehouseId.objects.filter(rm_id=warehouse_rm_id).first()
        if not warehouse:
            raise CommandError(f"Skladiste {warehouse_rm_id} ne postoji.")

        start_dt = timezone.make_aware(
            timezone.datetime.combine(as_of_date, timezone.datetime.min.time())
        )
        end_dt = timezone.make_aware(
            timezone.datetime.combine(as_of_date, timezone.datetime.max.time())
        )

        ingredients = (
            Artikl.objects.filter(
                used_in_normatives__isnull=False,
                stock_move_lines__warehouse=warehouse,
                stock_move_lines__move__date__gte=start_dt,
                stock_move_lines__move__date__lte=end_dt,
                stock_move_lines__move__move_type="out",
            )
            .distinct()
            .only("id", "rm_id", "code", "name")
        )

        created = 0
        updated = 0
        skipped = 0
        calculated_at = timezone.now()

        for ingredient in ingredients:
            lots = (
                StockLot.objects.filter(
                    warehouse=warehouse,
                    artikl=ingredient,
                    received_at__date__lte=as_of_date,
                )
                .only("qty_remaining", "unit_cost")
            )
            if not lots.exists():
                skipped += 1
                continue

            qty_on_hand = Decimal("0.0000")
            total_value = Decimal("0.0000")
            for lot in lots:
                if lot.qty_remaining:
                    qty_on_hand += lot.qty_remaining
                    total_value += lot.qty_remaining * lot.unit_cost

            if qty_on_hand <= 0:
                skipped += 1
                continue

            avg_cost = (total_value / qty_on_hand).quantize(Decimal("0.0000"))

            _, was_created = StockCostSnapshot.objects.update_or_create(
                warehouse=warehouse,
                artikl=ingredient,
                as_of_date=as_of_date,
                defaults={
                    "qty_on_hand": qty_on_hand,
                    "avg_cost": avg_cost,
                    "total_value": total_value.quantize(Decimal("0.0000")),
                    "calculated_at": calculated_at,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            "Recalc complete. created={created} updated={updated} skipped={skipped}".format(
                created=created, updated=updated, skipped=skipped
            )
        )
