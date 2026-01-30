# Admin iskustvo

> Modul: Admin
> Ovisi o: Računovodstvo, Zalihe, Nabava
> Koriste ga: Operativa

## Sadržaj
- [Admin — računovodstvo](#admin-racunovodstvo)
- [Admin — zalihe](#admin-zalihe)
- [Admin — nabava](#admin-nabava)
- [UI za SupplierInvoice](#ui-za-supplierinvoice)


Ovaj dio opisuje admin akcije i UI poboljšanja.

## Admin — računovodstvo
- Autocomplete za konta
- Akcija “Storniraj označene temeljnice”
- Linkovi original ↔ storno
- Uklonjen `delete_selected` gdje stvara konfuziju

## Admin — zalihe
- StockMove prikaz s inline stavkama
- StockLot list view
- StockAllocation list view
- Admin akcije:
  - “Proknjiži primku u skladište”
  - “Replenish Glavno → Šank”
- `WarehouseStock` lista prikazuje “latest cost” (zadnji `StockCostSnapshot`)
- `StockCostSnapshot` admin prikaz (dnevni snapshoti po skladištu)

## Admin — nabava
- Kreiraj `SupplierInvoice` iz primki
- Proknjiži ulazni račun (CASH/DEFERRED)
- Plaćanja kroz change form (Save)

## UI za SupplierInvoice
- JS toggle sakriva/prikazuje polja ovisno o `payment_terms`
  - CASH → cash_account
  - DEFERRED → ap_account
  - depozit > 0 → deposit_account
- Reset polja samo na add formi
- Pomoćne poruke i badge ADD/EDIT
- Boje help_text ovisno o tipu

## Admin — prodaja
- `SalesInvoice` i `SalesInvoiceItem` imaju date-picker filtere (issued_at)
- `SalesInvoiceItem`:
  - akcija “Robno razduži (stavke)”
  - True/False filter za “robno”
  - link na `StockMove`

[← Back to index](../index.md)
