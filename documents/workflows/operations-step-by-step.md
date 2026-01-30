# Operativni koraci

> Modul: Tijekovi rada
> Ovisi o: Računovodstvena jezgra, Zalihe
> Koriste ga: Operativa, Admin

## Sadržaj
- [0) Preduvjeti (jednom)](#0-preduvjeti-jednom)
- [1) Primka (ulaz robe)](#1-primka-ulaz-robe)
- [2) Kreiraj ulazni račun iz primki](#2-kreiraj-ulazni-racun-iz-primki)
- [3) Proknjiži ulazni račun (cash ili odgoda)](#3-proknjizi-ulazni-racun-cash-ili-odgoda)
- [4) Djelomična ili potpuna plaćanja (DEFERRED)](#4-djelomicna-ili-potpuna-placanja-deferred)
- [5) Prodaja (robno + financijsko)](#5-prodaja-robno-+-financijsko)
- [6) Transfer između skladišta](#6-transfer-izmedu-skladista)
- [7) Storno](#7-storno)
- [8) Reprezentacija (interno)](#8-reprezentacija-interno)


Ovo su praktični koraci koje koristiš svaki dan u adminu.

## 0) Preduvjeti (jednom)
- Ledger postoji (singleton).
- Kontni plan je uvezen (ako nije, uvezi).
- StockAccountingConfig je postavljen:
  - inventory_account, cogs_account
  - default_sale_warehouse
  - default_purchase_warehouse
  - default_replenish_from_warehouse (ako koristiš auto-replenish)
  - default_cash_account i default_deposit_account (ako želiš auto-popunjavanje)
- DocumentType postavljen (AR/AP/PDV/prihod/trošak konta).

## 1) Primka (ulaz robe)
1. Kreiraj Purchase Order (ako koristiš).
2. Kreiraj Primku (WarehouseInput) i unesi stavke.
3. U admin listi Primki odaberi primku i pokreni akciju **"Proknjiži primku u skladište"**.
4. Rezultat:
   - StockMove IN
   - StockMoveLine
   - StockLot (FIFO sloj)

## 2) Kreiraj ulazni račun iz primki
1. U listi Primki označi jednu ili više primki.
2. Pokreni akciju **"Kreiraj ulazni račun iz primki"**.
3. Ako su primke već vezane na račun, akcija će to blokirati.
4. Otvori kreirani SupplierInvoice preko linka u poruci.

## 3) Proknjiži ulazni račun (cash ili odgoda)
1. U SupplierInvoice provjeri:
   - document_type
   - cash_account / ap_account
   - deposit_account ako je deposit_total > 0
2. U listi SupplierInvoice označi račun i pokreni akciju **"Proknjiži ulazni račun"**.
3. Ako je CASH:
   - kreira se JournalEntry (trošak + pretporez + depozit + blagajna)
   - status ide na PAID
4. Ako je DEFERRED:
   - kreira se JournalEntry (trošak + pretporez + depozit + AP)
   - status ostaje UNPAID

## 4) Djelomična ili potpuna plaćanja (DEFERRED)
1. Otvori SupplierInvoice (change page).
2. Povećaj polje `paid_amount` za iznos koji je plaćen.
3. Klikni Save.
4. Sustav:
   - kreira payment JournalEntry (D AP / P cash_account)
   - postavlja status na PARTIAL ili PAID
   - zapisuje paid_at

## 5) Prodaja (robno + financijsko)
1. Osiguraj da postoji zaliha u default_sale_warehouse.
2. U servisu koristi `post_sale(...)` (nije admin akcija).
3. Sustav:
   - radi FIFO OUT
   - automatski radi COGS (ako SALE)
   - kreira sales JournalEntry (prihod + PDV + blagajna)

## 6) Transfer između skladišta
1. Koristi `post_stock_transfer(...)` ili `replenish_to_sale_warehouse(...)`.
2. FIFO vrijednost se prenosi (nema promjene cijene).

## 7) Storno
- Accounting: `JournalEntry.reverse()`.
- Stock: `reverse_stock_move(...)` (ovisno o tipu).

## 8) Reprezentacija (interno)
Reprezentacija se vodi kao **interni transfer** u Pomoćno skladište.

1. U `RepresentationItem` listi označi stavke.
2. Pokreni akciju **“Međuskladišnica za reprezentaciju → skladište Pomoćno (rm_id=8)”**.
3. Sustav:
   - radi **normativ expansion** (prodajni artikl → ingredient artikli)
   - spaja iste ingredient artikle u jednu stavku
   - kreira `WarehouseTransfer` u statusu DRAFT

Napomena: razduženje s Pomoćnog skladišta se razvija kasnije.

[← Back to index](../index.md)
