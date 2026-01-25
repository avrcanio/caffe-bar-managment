# Brzi početak

## Sadržaj
- [1) Početno podešavanje (jednom)](#1-pocetno-podesavanje-jednom)
- [1.1 Ledger](#11-ledger)
- [1.2 Kontni plan](#12-kontni-plan)
- [1.3 StockAccountingConfig](#13-stockaccountingconfig)
- [2) Nabava: Primka → Ulazni račun → Knjiženje](#2-nabava-primka-→-ulazni-racun-→-knjizenje)
- [2.1 Kreiraj primku i unesi stavke](#21-kreiraj-primku-i-unesi-stavke)
- [2.2 Proknjiži primku u skladište (FIFO IN)](#22-proknjizi-primku-u-skladiste-fifo-in)
- [2.3 Kreiraj ulazni račun iz primki](#23-kreiraj-ulazni-racun-iz-primki)
- [2.4 Proknjiži ulazni račun](#24-proknjizi-ulazni-racun)
- [3) Plaćanje dobavljača (DEFERRED)](#3-placanje-dobavljaca-deferred)
- [3.1 Evidentiraj plaćanje](#31-evidentiraj-placanje)
- [4) Prodaja: FIFO OUT → COGS → Prihod (gotovina)](#4-prodaja-fifo-out-→-cogs-→-prihod-gotovina)
- [4.1 Prodaja (post_sale)](#41-prodaja-post_sale)
- [4.2 Auto-replenish (opcionalno)](#42-auto-replenish-opcionalno)
- [5) Replenish (planirano punjenje šanka)](#5-replenish-planirano-punjenje-sanka)
- [5.1 ReplenishRequestLine](#51-replenishrequestline)
- [6) Storno](#6-storno)
- [6.1 Storno temeljnice (računovodstvo)](#61-storno-temeljnice-racunovodstvo)
- [6.2 Storno robnog dokumenta (StockMove)](#62-storno-robnog-dokumenta-stockmove)
- [Najčešće greške (i rješenja)](#najcesce-greske-i-rjesenja)


Ovaj vodič je praktičan “klik po klik” za rad u Django adminu.

> Pretpostavka: 1 firma = 1 baza, konfiguracije su singletoni.

---

## 1) Početno podešavanje (jednom)

## 1.1 Ledger
- U adminu provjeri da postoji **točno jedan** `Ledger`.

## 1.2 Kontni plan
- Ako konta nisu uvezena, uvezi RRiF plan i postavi `DocumentType` mapiranja.

## 1.3 StockAccountingConfig
U adminu postavi:
- `inventory_account`
- `cogs_account`
- `default_cash_account` (ako želiš auto-popunu kod plaćanja)
- `default_deposit_account` (opcionalno, za depozit)
- `default_sale_warehouse` (npr. **Šank Gornji**)
- `default_purchase_warehouse` (npr. **Glavno**)
- `auto_replenish_on_sale` (po želji)
- `default_replenish_from_warehouse` (ako je auto_replenish uključen, tipično **Glavno**)

---

## 2) Nabava: Primka → Ulazni račun → Knjiženje

## 2.1 Kreiraj primku i unesi stavke
- Kreiraj `WarehouseInput` (primka)
- Unesi `WarehouseInputItem` stavke:
  - `artikl` mora imati `tax_group`
  - ako artikl ima povratnu naknadu: `artikl.deposit`

## 2.2 Proknjiži primku u skladište (FIFO IN)
- U listi primki označi primku
- Akcija: **“Proknjiži primku u skladište”**
- Rezultat:
  - kreira se `StockMove(IN)`
  - kreiraju se `StockLot` FIFO slojevi
  - primka dobije `stock_move`

## 2.3 Kreiraj ulazni račun iz primki
- U listi primki označi jednu ili više primki
- Akcija: **“Kreiraj ulazni račun iz primki”**
- Pravila:
  - sve primke moraju imati istog dobavljača
  - `invoice_code` mora biti isti (ako se koristi)
  - primke ne smiju već biti vezane na račun

## 2.4 Proknjiži ulazni račun
Otvori `SupplierInvoice` i provjeri:
- `document_type` (obavezno)
- `payment_terms`:
  - **CASH** (odmah) ili
  - **DEFERRED** (odgoda)
- konta:
  - CASH → `cash_account` (obavezno)
  - DEFERRED → `ap_account` (obavezno; fallback iz `DocumentType.ap_account`)
  - depozit > 0 → `deposit_account` (obavezno)

Zatim akcija: **“Proknjiži ulazni račun”**
- CASH → knjiži blagajnu/banku, status = PAID
- DEFERRED → knjiži dobavljača (AP), status = UNPAID

---

## 3) Plaćanje dobavljača (DEFERRED)

## 3.1 Evidentiraj plaćanje
Na `SupplierInvoice` (DEFERRED):
- povećaj `paid_amount` (prazno/0 → djelomično ili full)
- postavi `paid_at` (ako je prazno, uzima se današnji)
- postavi `payment_account` (ako je prazno, uzima se `default_cash_account`)
- klikni **Save**

Sustav:
- kreira payment `JournalEntry` (D AP / P cash)
- ažurira `payment_status`:
  - PARTIAL ili
  - PAID

---

## 4) Prodaja: FIFO OUT → COGS → Prihod (gotovina)

## 4.1 Prodaja (post_sale)
- `post_sale()` radi:
  - robno: FIFO OUT iz `default_sale_warehouse`
  - auto COGS (D COGS / P inventory)
  - financije: gotovinska prodaja (D cash / P revenue / P VAT)
  - audit: veže `sales_journal_entry` na `StockMove`

## 4.2 Auto-replenish (opcionalno)
Ako je uključeno `auto_replenish_on_sale`:
- kad fali robe na šanku, sustav radi transfer **Glavno → Šank** za potrebnu količinu.

---

## 5) Replenish (planirano punjenje šanka)

## 5.1 ReplenishRequestLine
- Unesi `ReplenishRequestLine` (artikl + qty)
- Admin akcija: **“Izvrši transfer (replenish)”**
- Radi transfer `default_replenish_from_warehouse` → `default_sale_warehouse`

---

## 6) Storno

## 6.1 Storno temeljnice (računovodstvo)
- Na `JournalEntry` koristi admin akciju **“Storniraj označene temeljnice”**

## 6.2 Storno robnog dokumenta (StockMove)
- `reverse_stock_move()` radi storno za IN/OUT/TRANSFER

---

## Najčešće greške (i rješenja)
- **Nema default skladišta** → postavi u `StockAccountingConfig`
- **Depozit postoji, ali nema deposit_account** → postavi `default_deposit_account` ili na računu
- **Primka već proknjižena** → primka ima `stock_move` (ne radi duplo)
- **Primke već vezane na račun** → sustav blokira kreiranje novog računa

[← Back to index](../index.md)