from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from artikli.models import Artikl
from stock.models import StockLot, StockMoveLine, WarehouseId, WarehouseStock
from stock.services import post_stock_in, refresh_internal_warehouse_stock


def _parse_date(value: str) -> date:
    value = (value or "").strip()
    if not value:
        raise CommandError("Missing --date.")

    # Accept ISO-8601 (YYYY-MM-DD) and common local format (DD.MM.YYYY).
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass

    parts = [p for p in value.replace("/", ".").split(".") if p]
    if len(parts) != 3:
        raise CommandError("Invalid --date. Use YYYY-MM-DD or DD.MM.YYYY.")
    dd, mm, yyyy = parts
    try:
        return date(int(yyyy), int(mm), int(dd))
    except ValueError as e:
        raise CommandError(f"Invalid --date: {e}") from e


@dataclass(frozen=True)
class _Target:
    warehouse: WarehouseId
    artikl: Artikl


def _resolve_target(*, warehouse_rm_id: int | None, artikl_rm_id: int | None, artikl_code: str | None, wh_stock_id: int | None) -> _Target:
    if wh_stock_id is not None:
        ws = WarehouseStock.objects.select_related("warehouse_id", "product").filter(wh_id=wh_stock_id).first()
        if not ws:
            raise CommandError(f"WarehouseStock with wh_id={wh_stock_id} not found.")
        if not ws.warehouse_id_id:
            raise CommandError(f"WarehouseStock wh_id={wh_stock_id} has no warehouse_id set.")
        if not ws.product_id:
            raise CommandError(f"WarehouseStock wh_id={wh_stock_id} has no product set.")
        warehouse = WarehouseId.objects.filter(rm_id=ws.warehouse_id_id).first()
        artikl = Artikl.objects.filter(rm_id=ws.product_id).first()
        if not warehouse or not artikl:
            raise CommandError(f"WarehouseStock wh_id={wh_stock_id} points to missing warehouse/artikl.")
        return _Target(warehouse=warehouse, artikl=artikl)

    if warehouse_rm_id is None:
        raise CommandError("Missing --warehouse-rm-id (or use --warehouse-stock-wh-id).")

    warehouse = WarehouseId.objects.filter(rm_id=warehouse_rm_id).first()
    if not warehouse:
        raise CommandError(f"WarehouseId rm_id={warehouse_rm_id} not found.")

    artikl = None
    if artikl_rm_id is not None:
        artikl = Artikl.objects.filter(rm_id=artikl_rm_id).first()
    elif artikl_code:
        artikl = Artikl.objects.filter(code=artikl_code).first()
    else:
        raise CommandError("Missing --artikl-rm-id or --artikl-code (or use --warehouse-stock-wh-id).")

    if not artikl:
        raise CommandError("Artikl not found for given identifier.")

    return _Target(warehouse=warehouse, artikl=artikl)


class Command(BaseCommand):
    help = "Create an opening-stock IN move (and FIFO lot) for a warehouse+artikl at a given date, then refresh internal stock."

    def add_arguments(self, parser):
        parser.add_argument("--warehouse-rm-id", type=int, default=None, help="Warehouse rm_id (e.g. 4).")
        parser.add_argument("--artikl-rm-id", type=int, default=None, help="Artikl rm_id.")
        parser.add_argument("--artikl-code", type=str, default=None, help="Artikl code (e.g. barcode/PLU).")
        parser.add_argument(
            "--warehouse-stock-wh-id",
            type=int,
            default=None,
            help="WarehouseStock.wh_id (Remaris row id). If provided, warehouse and artikl are derived from that row.",
        )
        parser.add_argument("--qty", type=str, required=True, help="Quantity to add (e.g. 2 or 2.0000).")
        parser.add_argument("--unit-cost", type=str, required=True, help="Unit cost (e.g. 41.22).")
        parser.add_argument("--date", type=str, required=True, help="Date (YYYY-MM-DD or DD.MM.YYYY).")
        parser.add_argument("--reference", type=str, default="Pocetno stanje", help="StockMove.reference.")
        parser.add_argument("--note", type=str, default="Opening balance", help="StockMove.note.")

    def handle(self, *args, **options):
        qty = Decimal(str(options["qty"]))
        if qty <= 0:
            raise CommandError("--qty must be > 0.")

        unit_cost = Decimal(str(options["unit_cost"]))
        if unit_cost <= 0:
            raise CommandError("--unit-cost must be > 0.")

        as_of = _parse_date(options["date"])
        reference = (options.get("reference") or "").strip() or "Pocetno stanje"
        note = (options.get("note") or "").strip()

        target = _resolve_target(
            warehouse_rm_id=options.get("warehouse_rm_id"),
            artikl_rm_id=options.get("artikl_rm_id"),
            artikl_code=options.get("artikl_code"),
            wh_stock_id=options.get("warehouse_stock_wh_id"),
        )

        # Idempotency: prevent accidental duplicates for same (warehouse, artikl, date, reference).
        existing = (
            StockMoveLine.objects.select_related("move")
            .filter(
                warehouse_id=target.warehouse.rm_id,
                artikl_id=target.artikl.rm_id,
                move__date__date=as_of,
                move__reference=reference,
                move__move_type="in",
            )
            .order_by("id")
            .first()
        )
        if existing:
            if existing.quantity == qty and (existing.unit_cost or Decimal("0")) == unit_cost:
                self.stdout.write(
                    f"Already exists: move_id={existing.move_id} warehouse={target.warehouse.rm_id} artikl={target.artikl.rm_id}"
                )
            else:
                raise CommandError(
                    "Opening-stock move already exists for this warehouse+artikl+date+reference, but values differ. "
                    f"existing qty={existing.quantity} unit_cost={existing.unit_cost} vs requested qty={qty} unit_cost={unit_cost}."
                )
        else:
            move = post_stock_in(
                warehouse=target.warehouse,
                items=[{"artikl": target.artikl, "quantity": qty, "unit_cost": unit_cost}],
                move_date=as_of,
                reference=reference,
                note=note,
            )
            self.stdout.write(f"Created: move_id={move.id} warehouse={target.warehouse.rm_id} artikl={target.artikl.rm_id}")

        refresh_internal_warehouse_stock(
            warehouse_ids=[target.warehouse.rm_id],
            artikl_ids=[target.artikl.rm_id],
        )

        on_hand = (
            StockLot.objects.filter(warehouse_id=target.warehouse.rm_id, artikl_id=target.artikl.rm_id)
            .aggregate(total=Sum("qty_remaining", default=Decimal("0.0000")))
            .get("total")
            or Decimal("0.0000")
        )
        self.stdout.write(f"On-hand now: {on_hand}")

