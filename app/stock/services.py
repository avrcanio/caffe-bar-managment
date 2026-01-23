import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from artikli.models import Artikl
from artikli.remaris_connector import RemarisConnector
from orders.models import WarehouseInput
from stock.models import StockAllocation, StockLot, StockMove, StockMoveLine, WarehouseId, WarehouseStock

logger = logging.getLogger(__name__)
FOURPLACES = Decimal("0.0001")


def refresh_warehouse_stock_for_product_code(product_code: str) -> None:
    if not product_code:
        return

    connector = RemarisConnector()
    connector.login()

    warehouse_ids = list(WarehouseId.objects.values_list("rm_id", flat=True))
    if not warehouse_ids:
        return

    product = Artikl.objects.filter(code=product_code).first()

    with transaction.atomic():
        for warehouse_id in warehouse_ids:
            payload = {
                "dataSource": "warehouseStockDS",
                "operationType": "fetch",
                "startRow": 0,
                "endRow": 10001,
                "textMatchStyle": "exact",
                "componentId": "warehouseStockGrid",
                "oldValues": None,
                "data": {
                    "warehouseId": warehouse_id,
                    "allBaseGroups": True,
                    "showFilter": 20,
                    "request": "?_3403.578121292664",
                },
            }

            response = connector.post_json(
                "WarehouseStock/GetGridData?isc_dataFormat=json",
                payload,
                referer_path="/WarehouseStock",
            )

            data = response.get("response", {}).get("data", [])
            for item in data:
                if item.get("productCode", "") != product_code:
                    continue

                wh_id = item.get("id")
                if wh_id is None:
                    continue

                defaults = {
                    "warehouse_id_id": warehouse_id,
                    "product": product,
                    "product_name": item.get("productName", ""),
                    "product_code": product_code,
                    "unit": item.get("unit", ""),
                    "quantity": item.get("quantity", 0),
                    "base_group_name": item.get("baseGroupName", ""),
                    "active": bool(item.get("active", False)),
                }
                WarehouseStock.objects.update_or_create(wh_id=wh_id, defaults=defaults)

    logger.info("Warehouse stock refreshed for product_code=%s", product_code)


def _as_aware_datetime(value):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.combine(value, datetime.min.time())
    if timezone.is_aware(dt):
        return dt
    return timezone.make_aware(dt, timezone.get_current_timezone())


def _q4(value: Decimal) -> Decimal:
    return value.quantize(FOURPLACES, rounding=ROUND_HALF_UP)


@transaction.atomic
def post_warehouse_input_to_stock(*, warehouse_input: WarehouseInput, warehouse=None) -> StockMove:
    if warehouse_input.stock_move_id:
        raise ValidationError("Ova primka je vec proknjizena u skladiste.")

    warehouse = warehouse or warehouse_input.warehouse
    if not warehouse:
        raise ValidationError("Primka nema skladiste.")

    items = list(warehouse_input.items.all())
    if not items:
        raise ValidationError("Primka nema stavki.")

    move = StockMove.objects.create(
        move_type=StockMove.MoveType.IN,
        date=_as_aware_datetime(warehouse_input.date),
        reference=f"Primka #{warehouse_input.id}",
    )

    for it in items:
        qty = Decimal(str(it.quantity))
        if qty <= 0:
            raise ValidationError("Kolicina mora biti > 0.")

        unit_cost_raw = (
            it.buying_price
            if it.buying_price is not None
            else it.price_on_stock_card
            if it.price_on_stock_card is not None
            else it.price
        )
        if unit_cost_raw is None:
            raise ValidationError("Nabavna cijena nije postavljena na stavci.")

        unit_cost = Decimal(str(unit_cost_raw))
        if unit_cost <= 0:
            raise ValidationError("Nabavna cijena mora biti > 0.")

        line = StockMoveLine.objects.create(
            move=move,
            warehouse=warehouse,
            artikl=it.artikl,
            quantity=qty,
            unit_cost=unit_cost,
            source_item=it,
        )

        StockLot.objects.create(
            warehouse=warehouse,
            artikl=it.artikl,
            received_at=_as_aware_datetime(warehouse_input.date),
            unit_cost=unit_cost,
            qty_in=qty,
            qty_remaining=qty,
            source_item=it,
        )

    warehouse_input.stock_move = move
    warehouse_input.save(update_fields=["stock_move"])
    return move


@transaction.atomic
def post_stock_out(
    *,
    warehouse,
    items,
    move_date=None,
    reference: str = "",
    note: str = "",
) -> StockMove:
    if not warehouse:
        raise ValidationError("Skladiste je obavezno.")
    if not items:
        raise ValidationError("Nema stavki za izlaz.")

    move_date = move_date or timezone.now()
    move = StockMove.objects.create(
        move_type=StockMove.MoveType.OUT,
        date=_as_aware_datetime(move_date),
        reference=reference or "Izlaz iz skladista",
        note=note,
    )

    for item in items:
        artikl = item.get("artikl")
        qty_raw = item.get("quantity")
        if not artikl or qty_raw is None:
            raise ValidationError("Stavka mora imati artikl i kolicinu.")

        qty = Decimal(str(qty_raw))
        if qty <= 0:
            raise ValidationError("Kolicina mora biti > 0.")

        lots = list(
            StockLot.objects.select_for_update()
            .filter(warehouse=warehouse, artikl=artikl, qty_remaining__gt=0)
            .order_by("received_at", "id")
        )
        available = sum((lot.qty_remaining for lot in lots), Decimal("0.00"))
        if available < qty:
            raise ValidationError("Nema dovoljno zalihe za FIFO izlaz.")

        move_line = StockMoveLine.objects.create(
            move=move,
            warehouse=warehouse,
            artikl=artikl,
            quantity=qty,
            unit_cost=None,
        )

        remaining = qty
        total_cost = Decimal("0.00")

        for lot in lots:
            if remaining <= 0:
                break
            take = min(remaining, lot.qty_remaining)
            lot.qty_remaining = _q4(lot.qty_remaining - take)
            lot.save(update_fields=["qty_remaining"])

            StockAllocation.objects.create(
                move_line=move_line,
                lot=lot,
                qty=_q4(take),
                unit_cost=lot.unit_cost,
            )

            total_cost += _q4(take) * lot.unit_cost
            remaining -= take

        if remaining > 0:
            raise ValidationError("FIFO alokacija nije pokrila cijelu kolicinu.")

        avg_cost = _q4(total_cost / qty) if qty else Decimal("0.0000")
        move_line.unit_cost = avg_cost
        move_line.save(update_fields=["unit_cost"])

    return move
