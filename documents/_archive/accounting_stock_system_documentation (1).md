# Dokumentacija sustava (Accounting + Stock)

Ova dokumentacija opisuje **cijeli sustav** razvijen kroz ovaj chat: računovodstvo, robno poslovanje (FIFO), nabavu, prodaju, plaćanja i admin workflowe.

> Napomena: Dokument je strukturiran tako da se lako može **razdvojiti u više `.md` datoteka** (svaki glavni naslov = jedan file).

---

## 01_architecture_overview.md

### Opći koncept
- **1 firma = 1 baza**
- Singleton konfiguracije (Ledger, StockAccountingConfig)
- Strogo odvojeno:
  - **Accounting** (temeljnice, konta, plaćanja)
  - **Stock** (FIFO lotovi, kretanja, rezervacije)

### Glavni tokovi
- Nabava: Primka → Ulazni račun → Knjiženje (CASH/DEFERRED)
- Prodaja: POS račun → FIFO OUT → COGS → Prihod
- Plaćanja: Odgoda → Payment journal

---

## 02_accounting_core.md

### Kontni plan
- Model `Account`
- Hijerarhija (parent/child)
- `is_postable` zabrana knjiženja na grupna konta

### Temeljnice
- `JournalEntry`
- Statusi: DRAFT / POSTED / VOID
- Tvrda pravila:
  - POSTED se ne briše
  - POSTED/VOID se ne može mijenjati
  - Zaključani periodi

### Stavke
- `JournalItem`
- Jedna strana (D ili P)
- Zabrana izmjena ako je entry POSTED/VOID

### Periodi
- `Period`
- Zaključavanje po datumu

### Storno
- `JournalEntry.reverse()`
- Jedno storno po temeljnici
- Admin akcija “Storniraj”

---

## 03_tax_and_deposit.md

### PDV (TaxGroup)
- Jedini izvor istine: `TaxGroup.rate` (0.0500 / 0.1300 / 0.2500)
- Stavke koriste `Artikl.tax_group`

### Povratna naknada (Deposit)
- `Artikl.deposit`
- Automatski izračun: `amount * quantity`
- Ne ulazi u PDV osnovicu
- Knjiži se na `deposit_account`

---

## 04_stock_fifo.md

### FIFO modeli
- `StockLot` – FIFO sloj (qty_in / qty_remaining / unit_cost)
- `StockMove` – IN / OUT / TRANSFER
- `StockMoveLine`
- `StockAllocation` – veza OUT → lot

### IN (primka)
- `post_warehouse_input_to_stock()`
- Svaka stavka = novi lot
- Zaštita od duplog knjiženja

### OUT (FIFO)
- Troši najstarije lotove
- Sprema alokacije
- Računa FIFO cost

### TRANSFER
- FIFO OUT iz A
- FIFO IN u B po istim cijenama

### STORNO robnog dokumenta
- `reverse_stock_move()`
- Radi za IN / OUT / TRANSFER

---

## 05_stock_reservations.md

### Rezervacije
- `StockReservation`
- Dostupno = stanje − rezervirano

### Pravila
- Rezervacija blokira OUT
- OUT iz rezervacije automatski release-a rezervaciju

---

## 06_stock_accounting.md

### COGS
- Samo za `purpose = SALE`
- `post_cogs_for_stock_move()`
- D COGS / P Inventory

### StockAccountingConfig (singleton)
- inventory_account
- cogs_account
- default_sale_warehouse
- default_purchase_warehouse
- default_replenish_from_warehouse
- default_cash_account
- default_deposit_account

---

## 07_purchase_workflow.md

### Primke (WarehouseInput)
- Logistički dokument
- Ne knjiži financije samostalno

### SupplierInvoice (ulazni račun)
- M2M s primkama
- CASH / DEFERRED
- total_net / total_vat / total_gross / deposit_total

### Admin akcije
- Kreiraj ulazni račun iz primki
- Proknjiži ulazni račun (CASH/DEFERRED)

### Validacije
- Isti dobavljač
- Isti invoice_code
- Primke ne smiju već biti vezane

---

## 08_supplier_payments.md

### Plaćanja dobavljača
- `paid_amount`, `paid_at`, `payment_account`
- Partial / Full plaćanja

### Knjiženje plaćanja
- D AP / P Cash
- Automatsko ažuriranje statusa

### Admin ponašanje
- Plaćanje kroz change form
- CASH skip
- Jasne poruke (PARTIAL / PAID)

---

## 09_sales_workflow.md

### Prodaja (gotovina)
- `post_sale()`
- FIFO OUT
- Auto COGS
- Financijska prodaja

### Auto-replenish
- Ako fali na šanku → transfer iz Glavnog

---

## 10_admin_ux.md

### Admin akcije
- Knjiženje primke
- Kreiranje računa
- Replenish Glavno → Šank

### UI poboljšanja
- Toggle CASH / DEFERRED
- Dinamičko sakrivanje polja
- Badge ADD / EDIT
- Boje po payment_terms

---

## 11_testing.md

### Test strategija
- Svaki servis ima test
- FIFO edge-caseovi
- Partial payments
- Admin akcije testirane

### Performanse
- select_for_update + only()
- DB agregacije za COGS

---

## 12_future_work.md

### Sljedeći logični koraci
- Bankovni izvodi (CSV / CAMT)
- PaymentOrder (nalozi za plaćanje)
- POS import (storno računi)
- Inventura
- Analitika marže

---

**Kraj dokumentacije**

