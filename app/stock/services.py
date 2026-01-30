import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.db.models import DecimalField, F, Sum
from django.db.models.expressions import ExpressionWrapper

from artikli.models import Artikl
from accounting.services import _next_entry_number, get_single_ledger, post_sales_cash
from accounting.models import JournalEntry, JournalItem
from configuration.models import DocumentType
from artikli.remaris_connector import RemarisConnector
from orders.models import WarehouseInput
from stock.models import (
    StockAllocation,
    StockAccountingConfig,
    StockLot,
    StockMove,
    StockMoveLine,
    StockReservation,
    WarehouseId,
    WarehouseStock,
)

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
        cfg = get_stock_accounting_config()
        if not cfg.default_purchase_warehouse_id:
            raise ValidationError(
                "Nije postavljeno default skladiste za primke (StockAccountingConfig.default_purchase_warehouse)."
            )
        warehouse = cfg.default_purchase_warehouse
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
    reservation: StockReservation | None = None,
    purpose: str = "",
    auto_cogs: bool = True,
    cogs_account=None,
    inventory_account=None,
    posted_by=None,
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
        purpose=purpose or "",
    )

    for item in items:
        artikl = item.get("artikl")
        qty_raw = item.get("quantity")
        if not artikl or qty_raw is None:
            raise ValidationError("Stavka mora imati artikl i kolicinu.")

        qty = Decimal(str(qty_raw))
        if qty <= 0:
            raise ValidationError("Kolicina mora biti > 0.")

        on_hand = (
            StockLot.objects.select_for_update()
            .filter(warehouse=warehouse, artikl=artikl)
            .aggregate(total=Sum("qty_remaining", default=Decimal("0.00")))
        )["total"] or Decimal("0.00")
        reserved_qs = StockReservation.objects.select_for_update().filter(
            warehouse=warehouse, artikl=artikl, released_at__isnull=True
        )
        if reservation:
            reserved_qs = reserved_qs.exclude(id=reservation.id)
        reserved = (
            reserved_qs.aggregate(total=Sum("quantity", default=Decimal("0.00")))["total"]
            or Decimal("0.00")
        )
        available = on_hand - reserved
        if available < qty:
            raise ValidationError("Nema dovoljno dostupne zalihe (stanje - rezervirano).")

        if reservation:
            if reservation.released_at:
                raise ValidationError("Rezervacija je vec otpustena.")
            if reservation.warehouse_id != warehouse.rm_id or reservation.artikl_id != artikl.rm_id:
                raise ValidationError("Rezervacija ne odgovara skladistu ili artiklu.")
            if reservation.quantity < qty:
                raise ValidationError("Rezervacija nema dovoljnu kolicinu.")

        lots = list(
            StockLot.objects.select_for_update()
            .filter(warehouse=warehouse, artikl=artikl, qty_remaining__gt=0)
            .only("id", "qty_remaining", "unit_cost", "received_at")
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

        if reservation:
            release_reservation(reservation=reservation)

    if auto_cogs and move.purpose == StockMove.Purpose.SALE:
        if not cogs_account or not inventory_account:
            cfg = get_stock_accounting_config()
            cogs_account = cogs_account or cfg.cogs_account
            inventory_account = inventory_account or cfg.inventory_account
        post_cogs_for_stock_move(
            move=move,
            cogs_account=cogs_account,
            inventory_account=inventory_account,
            posted_by=posted_by,
        )

    return move


@transaction.atomic
def post_stock_transfer(
    *,
    from_warehouse,
    to_warehouse,
    items,
    move_date=None,
    reference: str = "",
    note: str = "",
) -> StockMove:
    if not from_warehouse or not to_warehouse:
        raise ValidationError("Oba skladista su obavezna.")
    if from_warehouse == to_warehouse:
        raise ValidationError("Skladista moraju biti razlicita.")
    if not items:
        raise ValidationError("Nema stavki za transfer.")

    move_date = move_date or timezone.now()
    move = StockMove.objects.create(
        move_type=StockMove.MoveType.TRANSFER,
        date=_as_aware_datetime(move_date),
        reference=reference or "Transfer skladista",
        note=note,
        from_warehouse=from_warehouse,
        to_warehouse=to_warehouse,
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
            .filter(warehouse=from_warehouse, artikl=artikl, qty_remaining__gt=0)
            .only("id", "qty_remaining", "unit_cost", "received_at")
            .order_by("received_at", "id")
        )
        available = sum((lot.qty_remaining for lot in lots), Decimal("0.00"))
        if available < qty:
            raise ValidationError("Nema dovoljno zalihe za FIFO transfer.")

        out_line = StockMoveLine.objects.create(
            move=move,
            warehouse=from_warehouse,
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

            allocation = StockAllocation.objects.create(
                move_line=out_line,
                lot=lot,
                qty=_q4(take),
                unit_cost=lot.unit_cost,
            )

            StockLot.objects.create(
                warehouse=to_warehouse,
                artikl=artikl,
                received_at=_as_aware_datetime(move_date),
                unit_cost=allocation.unit_cost,
                qty_in=allocation.qty,
                qty_remaining=allocation.qty,
            )

            total_cost += _q4(take) * lot.unit_cost
            remaining -= take

        if remaining > 0:
            raise ValidationError("FIFO alokacija nije pokrila cijelu kolicinu.")

        avg_cost = _q4(total_cost / qty) if qty else Decimal("0.0000")
        out_line.unit_cost = avg_cost
        out_line.save(update_fields=["unit_cost"])

    return move


@transaction.atomic
def post_stock_in_from_allocations(
    *,
    move: StockMove,
    warehouse,
    move_date=None,
    reference: str = "",
    note: str = "",
) -> StockMove:
    if move.move_type != StockMove.MoveType.OUT:
        raise ValidationError("Ocekivan je OUT move za povrat ulaza.")

    allocations = list(
        StockAllocation.objects.filter(move_line__move=move).select_related("lot", "move_line")
    )
    if not allocations:
        raise ValidationError("Nema FIFO alokacija za OUT kretanje.")

    move_date = move_date or timezone.now()
    reversal = StockMove.objects.create(
        move_type=StockMove.MoveType.IN,
        date=_as_aware_datetime(move_date),
        reference=reference or f"Storno izlaza #{move.id}",
        note=note,
        to_warehouse=warehouse,
    )

    by_line = {}
    for alloc in allocations:
        by_line.setdefault(alloc.move_line_id, []).append(alloc)

    for line in move.lines.select_related("artikl"):
        line_allocs = by_line.get(line.id, [])
        if not line_allocs:
            continue
        total_qty = sum((a.qty for a in line_allocs), Decimal("0.00"))
        move_line = StockMoveLine.objects.create(
            move=reversal,
            warehouse=warehouse,
            artikl=line.artikl,
            quantity=total_qty,
            unit_cost=None,
        )

        total_cost = Decimal("0.00")
        for alloc in line_allocs:
            StockLot.objects.create(
                warehouse=warehouse,
                artikl=line.artikl,
                received_at=_as_aware_datetime(move_date),
                unit_cost=alloc.unit_cost,
                qty_in=alloc.qty,
                qty_remaining=alloc.qty,
            )
            total_cost += alloc.qty * alloc.unit_cost

        if total_qty > 0:
            move_line.unit_cost = _q4(total_cost / total_qty)
            move_line.save(update_fields=["unit_cost"])

    return reversal


@transaction.atomic
def reverse_stock_move(*, move: StockMove, move_date=None, reference: str = "", note: str = "") -> StockMove:
    if move.reversed_move_id:
        raise ValidationError("Ne mozes stornirati storno kretanje.")
    if hasattr(move, "reversal"):
        raise ValidationError("Ovo kretanje je vec stornirano.")

    has_lines = move.lines.exists()
    if not has_lines:
        raise ValidationError("Kretanje nema stavki.")

    move_date = move_date or timezone.now()

    if move.move_type == StockMove.MoveType.TRANSFER:
        items = []
        for line in move.lines.select_related("artikl"):
            items.append(
                {
                    "artikl": line.artikl,
                    "quantity": line.quantity,
                }
            )
        reversal = post_stock_transfer(
            from_warehouse=move.to_warehouse,
            to_warehouse=move.from_warehouse,
            items=items,
            move_date=move_date,
            reference=reference or f"Storno transfera #{move.id}",
            note=note,
        )
    elif move.move_type == StockMove.MoveType.OUT:
        if not move.from_warehouse:
            raise ValidationError("OUT kretanje nema from_warehouse.")
        items = []
        for line in move.lines.select_related("artikl"):
            items.append(
                {
                    "artikl": line.artikl,
                    "quantity": line.quantity,
                }
            )
        reversal = post_stock_in_from_allocations(
            move=move,
            warehouse=move.from_warehouse,
            move_date=move_date,
            reference=reference or f"Storno izlaza #{move.id}",
            note=note,
            items=items,
        )
    elif move.move_type == StockMove.MoveType.IN:
        if not move.to_warehouse and not move.from_warehouse:
            warehouse = move.lines.first().warehouse if move.lines.exists() else None
        else:
            warehouse = move.to_warehouse or move.from_warehouse
        if not warehouse:
            raise ValidationError("IN kretanje nema skladiste.")
        items = []
        for line in move.lines.select_related("artikl"):
            items.append(
                {
                    "artikl": line.artikl,
                    "quantity": line.quantity,
                }
            )
        reversal = post_stock_out(
            warehouse=warehouse,
            items=items,
            move_date=move_date,
            reference=reference or f"Storno ulaza #{move.id}",
            note=note,
        )
    else:
        raise ValidationError("Nepodrzan tip kretanja za storno.")

    move.reversed_move = reversal
    move.save(update_fields=["reversed_move"])
    return reversal


@transaction.atomic
def post_cogs_for_stock_move(*, move: StockMove, cogs_account, inventory_account, posted_by=None) -> JournalEntry:
    if move.move_type != StockMove.MoveType.OUT:
        raise ValidationError("Financijsko knjizenje COGS moguce je samo za OUT kretanja.")
    if move.journal_entry_id:
        raise ValidationError("Ovo skladisno kretanje je vec financijski proknjizeno.")
    if not cogs_account or not cogs_account.is_postable:
        raise ValidationError("COGS konto mora biti postable.")
    if not inventory_account or not inventory_account.is_postable:
        raise ValidationError("Inventory konto mora biti postable.")

    allocations = StockAllocation.objects.filter(move_line__move=move)
    if not allocations.exists():
        raise ValidationError("Nema FIFO alokacija za ovaj izlaz.")

    total_cost = (
        allocations.aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("qty") * F("unit_cost"),
                    output_field=DecimalField(max_digits=18, decimal_places=2),
                )
            )
        )["total"]
        or Decimal("0.00")
    )

    if total_cost <= 0:
        raise ValidationError("Ukupni FIFO trosak mora biti > 0.")

    ledger = get_single_ledger()
    description = f"COGS {move.reference}".strip() if move.reference else f"COGS izlaz #{move.id}"
    entry = JournalEntry.objects.create(
        ledger=ledger,
        number=_next_entry_number(ledger),
        date=move.date.date(),
        description=description,
        status=JournalEntry.Status.DRAFT,
    )

    JournalItem.objects.create(
        entry=entry,
        account=cogs_account,
        debit=total_cost,
        credit=Decimal("0.00"),
        description="COGS",
    )
    JournalItem.objects.create(
        entry=entry,
        account=inventory_account,
        debit=Decimal("0.00"),
        credit=total_cost,
        description="Zaliha robe",
    )

    entry.post(user=posted_by)
    move.journal_entry = entry
    move.save(update_fields=["journal_entry"])
    return entry


@transaction.atomic
def reserve_stock(*, warehouse, artikl, quantity: Decimal, source_type: str = "", source_id=None) -> StockReservation:
    if not warehouse or not artikl:
        raise ValidationError("Skladiste i artikl su obavezni.")

    qty = Decimal(str(quantity))
    if qty <= 0:
        raise ValidationError("Kolicina mora biti > 0.")

    on_hand = (
        StockLot.objects.select_for_update()
        .filter(warehouse=warehouse, artikl=artikl)
        .aggregate(total=Sum("qty_remaining", default=Decimal("0.00")))
    )["total"] or Decimal("0.00")

    reserved = (
        StockReservation.objects.select_for_update()
        .filter(warehouse=warehouse, artikl=artikl, released_at__isnull=True)
        .aggregate(total=Sum("quantity", default=Decimal("0.00")))
    )["total"] or Decimal("0.00")

    available = on_hand - reserved
    if available < qty:
        raise ValidationError("Nema dovoljno dostupne zalihe za rezervaciju.")

    return StockReservation.objects.create(
        warehouse=warehouse,
        artikl=artikl,
        quantity=qty,
        source_type=source_type or "",
        source_id=source_id,
    )


def get_available_stock(*, warehouse, artikl) -> Decimal:
    on_hand = (
        StockLot.objects.filter(warehouse=warehouse, artikl=artikl)
        .aggregate(total=Sum("qty_remaining", default=Decimal("0.00")))
    )["total"] or Decimal("0.00")
    reserved = (
        StockReservation.objects.filter(warehouse=warehouse, artikl=artikl, released_at__isnull=True)
        .aggregate(total=Sum("quantity", default=Decimal("0.00")))
    )["total"] or Decimal("0.00")
    return on_hand - reserved


@transaction.atomic
def refresh_internal_warehouse_stock(*, warehouse_ids: list[int] | None = None, artikl_ids: list[int] | None = None) -> None:
    lots = StockLot.objects.all()
    if warehouse_ids:
        lots = lots.filter(warehouse_id__in=warehouse_ids)
    if artikl_ids:
        lots = lots.filter(artikl_id__in=artikl_ids)

    aggregates = (
        lots
        .values("warehouse_id", "artikl_id")
        .annotate(
            qty=Sum("qty_remaining", default=Decimal("0.0000")),
            value=Sum(
                ExpressionWrapper(
                    F("qty_remaining") * F("unit_cost"),
                    output_field=DecimalField(max_digits=18, decimal_places=4),
                ),
                default=Decimal("0.0000"),
            ),
        )
    )

    now = timezone.now()
    for row in aggregates:
        wh_id = row["warehouse_id"]
        artikl_id = row["artikl_id"]
        qty = row["qty"] or Decimal("0.0000")
        value = row["value"] or Decimal("0.0000")
        avg_cost = (value / qty) if qty else Decimal("0.0000")

        stock_row = (
            WarehouseStock.objects
            .filter(warehouse_id_id=wh_id, product_id=artikl_id, wh_id__isnull=False)
            .first()
        )
        fallback_row = None
        if not stock_row:
            fallback_row = WarehouseStock.objects.filter(
                warehouse_id_id=wh_id,
                product_id=artikl_id,
                wh_id__isnull=True,
            ).first()
            stock_row = fallback_row
        if not stock_row:
            artikl = Artikl.objects.filter(rm_id=artikl_id).first()
            stock_row = WarehouseStock.objects.create(
                warehouse_id_id=wh_id,
                product_id=artikl_id,
                product_name=getattr(artikl, "name", "") or "",
                product_code=getattr(artikl, "code", "") or "",
                unit="",
                quantity=Decimal("0.0000"),
                base_group_name="",
                active=True,
            )

        stock_row.internal_quantity = qty
        stock_row.internal_avg_cost = avg_cost
        stock_row.internal_updated_at = now
        stock_row.save(update_fields=["internal_quantity", "internal_avg_cost", "internal_updated_at"])
        if stock_row.wh_id and fallback_row and fallback_row.id != stock_row.id:
            fallback_row.delete()


@transaction.atomic
def release_reservation(*, reservation: StockReservation) -> StockReservation:
    if reservation.released_at:
        return reservation
    reservation.released_at = timezone.now()
    reservation.save(update_fields=["released_at"])
    return reservation


def get_stock_accounting_config() -> StockAccountingConfig:
    cfg = StockAccountingConfig.objects.first()
    if not cfg:
        raise ValidationError(
            "Nedostaje StockAccountingConfig. Postavi inventory_account i cogs_account u adminu."
        )
    return cfg


@transaction.atomic
def post_sale(
    *,
    warehouse=None,
    lines,
    date,
    document_type: DocumentType,
    cash_account,
    net: Decimal,
    vat: Decimal,
) -> tuple[StockMove, JournalEntry]:
    cfg = get_stock_accounting_config()
    if not warehouse:
        if not cfg.default_sale_warehouse_id:
            raise ValidationError(
                "Nije postavljeno default skladiste za prodaju (StockAccountingConfig.default_sale_warehouse)."
            )
        warehouse = cfg.default_sale_warehouse
    if not warehouse:
        raise ValidationError("Nedostaje skladiste za prodaju.")

    if cfg.auto_replenish_on_sale:
        if not cfg.default_replenish_from_warehouse_id:
            raise ValidationError(
                "Nije postavljeno skladiste za automatsku dopunu (StockAccountingConfig.default_replenish_from_warehouse)."
            )
        for line in lines:
            artikl = line.get("artikl")
            qty_raw = line.get("quantity")
            if not artikl or qty_raw is None:
                raise ValidationError("Stavka mora imati artikl i kolicinu.")
            qty = Decimal(str(qty_raw))
            available = get_available_stock(warehouse=warehouse, artikl=artikl)
            if available >= qty:
                continue
            missing = qty - available
            replenish_available = get_available_stock(
                warehouse=cfg.default_replenish_from_warehouse,
                artikl=artikl,
            )
            if replenish_available < missing:
                raise ValidationError("Nema dovoljno na zalihi ni u Glavno skladistu.")
            post_stock_transfer(
                from_warehouse=cfg.default_replenish_from_warehouse,
                to_warehouse=warehouse,
                items=[{"artikl": artikl, "quantity": missing}],
                move_date=date,
                reference=f"Auto dopuna za prodaju ({artikl})",
            )
    move = post_stock_out(
        warehouse=warehouse,
        items=lines,
        move_date=date,
        purpose=StockMove.Purpose.SALE,
        auto_cogs=True,
    )

    if move.sales_journal_entry_id:
        raise ValidationError("Prodaja je vec financijski proknjizena.")

    entry = post_sales_cash(
        document_type=document_type,
        date=date,
        net=net,
        vat=vat,
        cash_account=cash_account,
        description=f"Prodaja (move {move.id})",
    )

    move.sales_journal_entry = entry
    move.save(update_fields=["sales_journal_entry"])

    return move, entry


@transaction.atomic
def replenish_to_sale_warehouse(*, lines):
    cfg = get_stock_accounting_config()
    if not cfg.default_sale_warehouse_id:
        raise ValidationError("Nedostaje default_sale_warehouse u konfiguraciji.")
    if not cfg.default_replenish_from_warehouse_id:
        raise ValidationError("Nedostaje default_replenish_from_warehouse u konfiguraciji.")

    return post_stock_transfer(
        from_warehouse=cfg.default_replenish_from_warehouse,
        to_warehouse=cfg.default_sale_warehouse,
        items=lines,
        move_date=timezone.now(),
        reference="Replenish Glavno -> Sank",
    )
