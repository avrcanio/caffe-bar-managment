# Quick start (admin)

## 1) Osnovna konfiguracija (jednom)
1. Kreiraj Ledger (jedini u bazi).
2. Uvezi kontni plan (Accounts).
3. Kreiraj DocumentType i postavi konta (AR/AP/PDV/prihod/trošak).
4. Kreiraj skladišta (WarehouseId).
5. Postavi StockAccountingConfig:
   - inventory_account, cogs_account
   - default_sale_warehouse
   - default_purchase_warehouse
   - default_cash_account / default_deposit_account (po potrebi)

## 2) Primka → zaliha
1. Kreiraj Primku (WarehouseInput) i stavke.
2. U listi Primki pokreni akciju **Proknjiži primku u skladište**.
3. Provjeri da su nastali StockMove i StockLot.

## 3) Primka → ulazni račun
1. U listi Primki označi primke.
2. Pokreni akciju **Kreiraj ulazni račun iz primki**.
3. Otvori kreirani SupplierInvoice (link u poruci).

## 4) Knjiženje ulaznog računa
1. Provjeri document_type + cash/ap account + deposit_account.
2. U listi SupplierInvoice pokreni akciju **Proknjiži ulazni račun**.

## 5) Djelomična plaćanja (DEFERRED)
1. Otvori SupplierInvoice.
2. Povećaj `paid_amount`.
3. Save → sustav kreira payment journal.

## 6) Prodaja (servis)
Koristi servis `post_sale(...)` iz koda (robno + financije).

