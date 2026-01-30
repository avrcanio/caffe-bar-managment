# FIFO zalihe

> Modul: Zalihe
> Ovisi o: —
> Koriste ga: Nabavni tijek rada, Prodajni tijek rada

## Sadržaj
- [Modeli](#modeli)
- [StockLot (FIFO sloj)](#stocklot-fifo-sloj)
- [StockMove](#stockmove)
- [StockMoveLine](#stockmoveline)
- [StockAllocation](#stockallocation)
- [Nabavna cijena (snapshot)](#nabavna-cijena-snapshot)
- [Servisi](#servisi)
- [IN: Primka → lotovi](#in-primka-→-lotovi)
- [OUT: FIFO alokacija](#out-fifo-alokacija)
- [TRANSFER](#transfer)
- [Storno robnog dokumenta](#storno-robnog-dokumenta)
- [Testovi](#testovi)


Ovaj dio opisuje robni modul: FIFO slojevi, kretanja, alokacije i storno. Veza prema COGS je opisana u modulu **Računovodstvo zaliha (COGS)**.

## Modeli

## StockLot (FIFO sloj)
- `warehouse`
- `artikl`
- `received_at`
- `unit_cost`
- `qty_in`
- `qty_remaining`
- Audit link na `StockMoveLine` (iz koje je nastao)

## StockMove
Tipovi:
- IN
- OUT
- TRANSFER

Dodatno:
- `purpose` (SALE / CONSUMPTION / WASTE / ADJUSTMENT)
- `from_warehouse` / `to_warehouse` za transfer
- `reversed_move` za storno
- `journal_entry` (COGS)
- `sales_journal_entry` (prihod)

## StockMoveLine
- povezana s `StockMove`
- `artikl`, `quantity`
- za IN ima `unit_cost`
- `source_item` FK na `WarehouseInputItem` (audit)

## StockAllocation
Veza OUT → lot:
- `move_line`
- `lot`
- `qty`
- `unit_cost`

## Nabavna cijena (snapshot)
Za dnevni pregled nabavne cijene po skladištu koristi se `StockCostSnapshot`:
- `warehouse`, `artikl`, `as_of_date`
- `qty_on_hand`, `avg_cost`, `total_value`

Snapshot se računa komandno:
```
python manage.py recalc_stock_costs --date=YYYY-MM-DD --warehouse=<rm_id>
```

Pravila:
- računa se **po skladištu**
- uključuje **samo artikle koji imaju izlaz (OUT) taj dan**
- koristi FIFO lotove do `as_of_date`

UI:
- u `WarehouseStock` listi se prikazuje “latest cost” (zadnji snapshot)
- snapshoti su dostupni u adminu (`StockCostSnapshot`)

## Servisi

## IN: Primka → lotovi
`post_warehouse_input_to_stock()`:
- kreira `StockMove(IN)`
- kreira `StockMoveLine` za svaku stavku primke
- kreira `StockLot` (qty_in = qty_remaining)
- zaštita: `WarehouseInput.stock_move` OneToOne blokira dupli IN

## OUT: FIFO alokacija
`post_stock_out(...)`:
- računa dostupno (stanje − rezervirano)
- troši lotove po FIFO (najstariji `received_at`)
- ažurira `qty_remaining`
- kreira `StockAllocation`

## TRANSFER
`post_stock_transfer(...)`:
- FIFO OUT iz `from_warehouse`
- kreira lotove u `to_warehouse` po istim alokacijama i `unit_cost`

## Storno robnog dokumenta
`reverse_stock_move()`:
- radi za IN / OUT / TRANSFER
- `reversed_move` OneToOne sprječava dupli storno
- za OUT storno koristi `post_stock_in_from_allocations()`

## Testovi
Pokriveno:
- IN kreira lotove
- OUT radi FIFO alokacije + insufficient stock
- TRANSFER kreira lotove u cilju i smanjuje izvor
- reverse radi i vraća stanje

[← Back to index](../index.md)
