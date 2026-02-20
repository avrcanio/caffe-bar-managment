# Inventura

> Modul: Zalihe
> Ovisi o: —
> Koriste ga: Operativa, Admin

## Sadržaj
- [Modeli](#modeli)
- [`stock.Inventory`](#stockinventory)
- [`stock.InventoryItem`](#stockinventoryitem)
- [`stock.WarehouseTransfer`](#stockwarehousetransfer)
- [Admin (inventura)](#admin-inventura)
- [Logika actiona (manjak/višak)](#logika-actiona-manjakvisak)
- [Povezano: međuskladišnica iz primki](#povezano-međuskladišnica-iz-primki)
- [Kako testirati](#kako-testirati)


Ovaj dokument opisuje postojeću (legacy) inventuru, statuse i admin action za automatsku međuskladišnicu na temelju razlike između inventure i stanja skladišta.

Odluka o tome kako se inventura spaja s novim FIFO slojevima i robnim kretanjima još nije donesena.

## Modeli

## `stock.Inventory`
- `warehouse` (FK -> `stock.WarehouseId`, mapira `rm_id`)
- `date`
- `name` (opcionalno): naziv inventure (prikazuje se u admin list view)
- `note` (opcionalno): napomena uz inventuru
- `opens_at` / `closes_at` (opcionalno): vremenski prozor kada je public inventura dostupna
- `status`:
  - `open` (Otvoreno): nema niti jedne stavke s upisanom količinom (sve su `quantity = NULL`)
  - `counted` (Brojano): postoji barem jedna stavka s `quantity != NULL` (napomena: `0` je valjana prebrojana vrijednost)
  - `closed` (Zatvoreno): nakon obrade inventure (manjak/višak) ili ručnog zatvaranja
- `public_token_digest`, `public_token_created_at`:
  - koristi se za public brojanje preko tokena; u bazi je digest (sha256), a token se prikazuje samo prilikom generiranja
- `submitted_at`, `submitted_by_name`, `submitted_ip`, `submitted_user_agent`:
  - nakon submit-a s public sučelja inventura se smatra “predanom” (read-only za public UI)
- `created_by` (admin/API kreiranje)
- `counted_by` (korisnik koji je brojao; prikazuje se u public prikazu)

Status se automatski ažurira pri spremanju/brisanja stavki, osim ako je već `closed`.
Automatika: `Inventory.update_status_from_items()` postavlja `open/counted` na temelju toga postoji li barem jedna stavka s `quantity != NULL`.

## `stock.InventoryItem`
- `inventory` (FK)
- `artikl` (FK -> `artikli.Artikl`)
- `quantity` (decimal, 4 decimale; `NULL` znači “nije prebrojano”)
- `unit` (FK -> `artikli.UnitOfMeasureData`; auto-fill iz `artikl.detail.unit_of_measure` ako nije postavljeno)
- `note`

## `stock.WarehouseTransfer`
- koristi se za prijenos viška/manjka između skladišta
- `note` se popunjava s informacijom o inventuri
- bitno za slanje u Remaris: za action **Send međuskladišnicu to Remaris** moraju biti postavljena oba skladišta (`from_warehouse` i `to_warehouse`)
- statusi: `draft`, `sent`, `posted_internal`, `failed`

## Admin (inventura)

U `Inventory` adminu (`app/stock/admin.py`):
- lista prikazuje: `id`, `warehouse`, `date`, `status`, `created_by`
- filteri: `status`, `warehouse`
- inline stavke: `artikl`, `quantity`, `unit`, `note`
- read-only info: public link status + submit info (`submitted_*`)
- actions:
  - **Create međuskladišnica for inventory shortage**
  - **Generiraj public link (/inventory/<token>)**
  - **Otkljucaj (ispravak brojanja) + regeneriraj public link**
  - **Ukloni public link**
  - **Kreiraj novu inventuru iz odabrane (kopiraj stavke bez kolicina)**

Napomena: ako se u adminu inventura eksplicitno prebaci u `open`, a već je bila “predana” (`submitted_at`), admin će je otključati i regenerirati public link.

### Public inventura (token)
- Link koji admin ispiše je oblika: `/inventory/<token>` (frontend ruta).
- API koji frontend koristi:
  - `GET /api/inventories/public/<token>/` (prikaz inventure i stavki)
  - `POST /api/inventories/public/<token>/submit/` (predaja inventure)
- Pravila:
  - `opens_at/closes_at` ograničavaju pristup (403 prije/poslije prozora)
  - submit mora poslati **sve** stavke inventure; `quantity` je obavezna i mora biti `>= 0`
  - nakon submit-a: `submitted_at` se postavlja, i public prikaz postaje read-only

## Logika actiona (manjak/višak)

Action radi za odabrane inventure i:
1) Provjeri da postoji target skladište `warehouse_id=8` (rm_id=8).
2) **Prvo synca stanje** s Remarisa za skladišta iz odabranih inventura.
   - koristi import iz Remarisa (`warehouseStockDS`) za odabrana skladišta
   - ako sync ne uspije, action se prekida
3) Za svaku stavku inventure računa:
   - `stock_qty` = `WarehouseStock.internal_quantity` (FIFO interno stanje; ne koristi se uvezeni `WarehouseStock.quantity`)
   - `diff = stock_qty - inventory_qty`
4) Kreira korekcije:
   - **Manjak (diff > 0)**: kreira jednu `WarehouseTransfer` (**inventory skladište -> warehouse_id=8**) i stavke s količinom `diff`
   - **Višak (diff < 0)**: kreira jedan interni **ulaz** (`StockMove` IN + `StockMoveLine` + novi `StockLot`) u inventory skladište s količinom `abs(diff)`
     - nabavna cijena za višak se računa kao prosječna cijena postojećih FIFO lotova za taj artikl u skladištu (weighted avg po `qty_remaining`)
5) Nakon obrade, inventura se označi `closed` (i onda je action više ne dira).
6) U napomene/referencu upisuje:
   - `Inventura manjak: inventory_id=..., inventory_date=...`
   - `Inventura visak: inventory_id=..., inventory_date=...`

Napomena: `warehouse_id=8` mora postojati u `WarehouseId` (rm_id=8).
Napomena: za točan izračun potrebno je da je interno stanje (`WarehouseStock.internal_quantity`) ažurno (npr. preko admin akcija **Refresh internal stock** / **Refresh internal stock (all)** na `WarehouseStock`).

Ako inventura nema nijednu prebrojanu stavku (sve `quantity=NULL`), action neće kreirati ništa (i neće je automatski zatvoriti).

## Povezano: međuskladišnica iz primki

U `orders.WarehouseInput` adminu (`app/orders/admin.py`) postoji action:
- **Kreiraj međuskladišnicu iz primki**

Logika:
- za svaku odabranu primku kreira `WarehouseTransfer` s `from_warehouse=<warehouse_input.warehouse>` i `to_warehouse=NULL`
- kreira `WarehouseTransferItem` stavke iz stavki primke

Napomena: takva međuskladišnica se ne može poslati u Remaris dok se ručno ne postavi `to_warehouse` (jer `Send međuskladišnicu to Remaris` preskače transfere bez oba skladišta).

## Kako testirati

1) Kreiraj/odaberi inventuru s stavkama.
2) Pokreni action **Create međuskladišnica for inventory shortage**.
3) Provjeri:
   - da je stanje skladišta syncano (WarehouseStock ažuriran)
   - da je za manjak kreirana međuskladišnica (WarehouseTransfer), a za višak interni ulaz (StockMove IN)
   - da je `Inventory.status` postavljen na `closed`

[← Back to index](../index.md)
