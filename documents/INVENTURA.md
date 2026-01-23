# Inventura (stock)

Ovaj dokument opisuje kako radi inventura, statusi, i admin action za automatsku međuskladišnicu na temelju razlike između inventure i stanja skladišta.

## Modeli

### `stock.Inventory`
- `warehouse` (FK -> `stock.WarehouseId`, mapira `rm_id`)
- `date`
- `status`:
  - `open` (Otvoreno): nema stavki ili su sve količine 0/null
  - `counted` (Brojano): postoji barem jedna stavka s količinom != 0
  - `closed` (Zatvoreno): nakon obrade inventure (međuskladišnica ili ispravna razlika)
- `created_by`

Status se automatski ažurira pri spremanju/brisanja stavki, osim ako je već `closed`.

### `stock.InventoryItem`
- `inventory` (FK)
- `artikl` (FK -> `artikli.Artikl`)
- `quantity`
- `unit`
- `note`

### `stock.WarehouseTransfer`
- koristi se za prijenos viška/manjka između skladišta
- `note` se popunjava s informacijom o inventuri

## Admin (Inventura)

U `Inventory` adminu:
- lista prikazuje `status`
- filteri: `status`, `warehouse`
- action: **Create međuskladišnica for inventory shortage**

## Logika actiona (manjak/višak)

Action radi za odabrane inventure i:
1) **Prvo synca stanje** s Remarisa za skladišta iz odabranih inventura.
   - koristi postojeći import iz Remarisa (`warehouseStockDS`)
   - ako sync ne uspije, action se prekida
2) Za svaku stavku inventure računa:
   - `diff = stock_qty - inventory_qty`
3) Kreira 0, 1 ili 2 transfera:
   - **Manjak (diff > 0)**: transfer **iz inventory skladišta -> warehouse_id=8**
   - **Višak (diff < 0)**: transfer **iz warehouse_id=8 -> inventory skladište**
4) Ako nema razlike, transfer se briše i inventura se označi `closed`.
5) U napomenu transfera upisuje:
   - `Inventura manjak: inventory_id=..., inventory_date=...`
   - `Inventura visak: inventory_id=..., inventory_date=...`

Napomena: `warehouse_id=8` mora postojati u `WarehouseId` (rm_id=8).

## Kako testirati

1) Kreiraj/odaberi inventuru s stavkama.
2) Pokreni action **Create međuskladišnica for inventory shortage**.
3) Provjeri:
   - da je stanje skladišta syncano (WarehouseStock ažuriran)
   - da su kreirane međuskladišnice za manjak/višak
   - da je `Inventory.status` postavljen na `closed`
