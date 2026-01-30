# Pregled

## Sadržaj
- [Računovodstvena jezgra (app/accounting)](#racunovodstvena-jezgra-appaccounting)
- [Modeli](#modeli)
- [Pravila](#pravila)
- [Izvještaji](#izvjestaji)
- [Zalihe/FIFO (app/stock)](#zalihefifo-appstock)
- [Modeli](#modeli)
- [Servisi](#servisi)
- [Nabava (app/purchases)](#nabava-apppurchases)
- [SupplierInvoice](#supplierinvoice)
- [Dokumentacija sustava (računovodstvo + zalihe)](#dokumentacija-sustava-racunovodstvo-+-zalihe)
- [Opći koncept](#opci-koncept)
- [Glavni tokovi](#glavni-tokovi)
- [Računovodstvena jezgra](#racunovodstvena-jezgra)
- [PDV i povratna naknada](#pdv-i-povratna-naknada)
- [FIFO zalihe](#fifo-zalihe)
- [Rezervacije zaliha](#rezervacije-zaliha)
- [Računovodstvo zaliha (COGS)](#racunovodstvo-zaliha-cogs)
- [Nabavni tijek rada](#nabavni-tijek-rada)
- [Plaćanja dobavljača](#placanja-dobavljaca)
- [Prodajni tijek rada](#prodajni-tijek-rada)
- [Admin iskustvo](#admin-iskustvo)
- [Testiranje i performanse](#testiranje-i-performanse)
- [Budući rad](#buduci-rad)


Ovaj dokument sažima računovodstvenu jezgru, robni FIFO sloj i nabavni tok koji su trenutno implementirani.

## Računovodstvena jezgra (app/accounting)

## Modeli
- Ledger (singleton u bazi).
- Account (kontni plan) s type, normal_side, parent, is_postable.
- Period (zaključivi obračunski periodi).
- JournalEntry (DRAFT/POSTED/VOID) s pravilima zaključavanja.
- JournalItem (debit/credit stavke, jedna strana, postable-only konto).

## Pravila
- POSTED i VOID ne mogu mijenjati status/datum nakon save.
- POSTED ne može biti u zatvorenom Periodu.
- JournalItem save/delete je blokiran ako je entry POSTED ili VOID.
- Brisanje POSTED entryja/stavki je blokirano.
- Storno podržan kroz JournalEntry.reverse().
- VOID je dopušten samo za DRAFT.

## Izvještaji
- account_ledger(account, date_from, date_to)
- trial_balance(date_from, date_to, only_postable=True, only_nonzero=True)

### Blagajnički dnevnik

Blagajnički dnevnik je glavna evidencija gotovine u sustavu.
Prikazuje sva gotovinska kretanja (naplate, isplate, pologe na banku)
i koristi se u svakodnevnoj operativi za kontrolu blagajne po danima i smjenama.

## Zalihe/FIFO (app/stock)

## Modeli
- Warehouse
- StockLot (FIFO slojevi)
- StockMove (IN/OUT/TRANSFER)
- StockMoveLine
- StockAllocation (OUT → lot)
- StockReservation
- StockAccountingConfig (singleton)
- StockCostSnapshot (dnevni snapshot nabavne cijene)

## Servisi
- post_warehouse_input_to_stock
- post_stock_out
- post_stock_transfer
- post_cogs_for_stock_move
- post_sale
- reserve_stock / release_reservation

## Nabava (app/purchases)

## SupplierInvoice
- inputs (M2M WarehouseInput)
- payment_terms (CASH/DEFERRED)
- payment_status (UNPAID/PARTIAL/PAID)
- paid_amount / paid_at / payment_account

---

## Dokumentacija sustava (računovodstvo + zalihe)

Ovaj dio je prošireni pregled sustava (izvorno objedinjena dokumentacija).

## Opći koncept
- 1 firma = 1 baza
- Singleton konfiguracije (Ledger, StockAccountingConfig)
- Strogo odvojeno: računovodstvo i zalihe

## Glavni tokovi
- Nabava: Primka → Ulazni račun → Knjiženje (CASH/DEFERRED)
- Prodaja: POS račun → FIFO OUT → COGS → Prihod
- Plaćanja: odgoda → payment journal
- Z dnevno (POS): SalesInvoice → SalesZPosting → JournalEntry (vidi [Prodajni tijek rada](../workflows/sales-workflow.md))

## Računovodstvena jezgra
- Kontni plan, temeljnice, stavke, periodi, storno, zaštite

## PDV i povratna naknada
- TaxGroup.rate kao jedini izvor istine
- Deposit iz Artikl.deposit (ne ulazi u PDV osnovicu)

## FIFO zalihe
- StockLot, StockMove, StockMoveLine, StockAllocation
- IN/OUT/TRANSFER i reverse

## Rezervacije zaliha
- Rezervacije i dostupno stanje (stanje − rezervirano)

## Računovodstvo zaliha (COGS)
- COGS samo za SALE
- StockAccountingConfig

## Nabavni tijek rada
- Primka → SupplierInvoice → knjiženje

## Plaćanja dobavljača
- DEFERRED plaćanja kroz payment journal

## Prodajni tijek rada
- Prodaja: OUT → COGS → sales journal

## Admin iskustvo
- Admin akcije i UX poboljšanja
- Date picker filteri u prodaji (SalesInvoice / SalesInvoiceItem)
- “Latest cost” u WarehouseStock listi

## Testiranje i performanse
- Testovi i optimizacije

## Budući rad
- Planirani koraci

[← Back to index](../index.md)
