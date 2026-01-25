# Nabavni tijek rada

> Modul: Tijekovi rada
> Ovisi o: Računovodstvena jezgra, Zalihe
> Koriste ga: Operativa, Admin

## Sadržaj
- [Narudžbe dobavljaču](#narudzbe-dobavljacu)
- [Primke (WarehouseInput)](#primke-warehouseinput)
- [SupplierInvoice (Ulazni račun)](#supplierinvoice-ulazni-racun)
- [Admin: kreiraj račun iz primki](#admin-kreiraj-racun-iz-primki)
- [Knjiženje ulaznog računa](#knjizenje-ulaznog-racuna)
- [CASH](#cash)
- [DEFERRED](#deferred)
- [Testovi](#testovi)


## Narudžbe dobavljaču
Narudžbe (Purchase Orders) su opisane u posebnom modulu: `documents/workflows/purchase-orders.md`.

## Primke (WarehouseInput)
- Logistički dokument za zaprimanje robe.
- IN u skladište radi se kroz robni servis: `post_warehouse_input_to_stock()`.

## SupplierInvoice (Ulazni račun)
Model koji predstavlja financijski dokument dobavljača.

Polja (ključna):
- `supplier`
- `invoice_number`, `invoice_date`
- M2M `inputs` (više primki na jedan račun)
- totals: `total_net`, `total_vat`, `total_gross`, `deposit_total`
- konta: `document_type`, `cash_account`, `deposit_account`, `ap_account`
- `journal_entry`
- plaćanje: `payment_terms`, `payment_status`, `due_date`

## Admin: kreiraj račun iz primki
Akcija na primkama:
- provjerava isti dobavljač
- provjerava isti `invoice_code`
- blokira primke koje su već vezane na račun (M2M)
- računa totals iz stavki
- veže primke na `SupplierInvoice`
- auto postavlja `document_type` ako je isti na svim primkama
- auto povlači `cash_account` i `deposit_account` iz configa

## Knjiženje ulaznog računa
Jedna admin akcija “Proknjiži ulazni račun” koja radi po `payment_terms`:

## CASH
- knjiži: D trošak, D pretporez, D depozit, P blagajna
- postavlja status: `PAID` (+ `paid_cash=True`, `paid_at`)

## DEFERRED
- knjiži: D trošak, D pretporez, D depozit, P dobavljači (AP)
- postavlja status: `UNPAID`

Validacije:
- uvijek treba `document_type`
- CASH treba `cash_account`
- DEFERRED treba `ap_account` (fallback iz `document_type.ap_account`)
- depozit traži `deposit_account`

## Testovi
- admin akcije i validacije
- knjiženje CASH/DEFERRED

[← Back to index](../index.md)