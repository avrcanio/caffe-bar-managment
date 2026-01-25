# Plaćanja dobavljača

> Modul: Tijekovi rada
> Ovisi o: Računovodstvena jezgra, Zalihe
> Koriste ga: Operativa, Admin

## Sadržaj
- [Polja na SupplierInvoice](#polja-na-supplierinvoice)
- [Servis](#servis)
- [Admin ponašanje](#admin-ponasanje)
- [Buduće](#buduce)


Ovaj dio pokriva zatvaranje obveza za račune s odgodom plaćanja.

## Polja na SupplierInvoice
- `payment_terms`: CASH / DEFERRED
- `payment_status`: UNPAID / PARTIAL / PAID
- `due_date`
- `paid_amount`
- `paid_at`
- `payment_account` (konto s kojeg je plaćeno)
- `ap_account` (dobavljači)

## Servis
`post_supplier_invoice_payment(invoice, amount, paid_at, payment_account)`:
- radi samo za `payment_terms=DEFERRED`
- knjiži:
  - D `ap_account`
  - P `payment_account`
**Ne ažurira** `paid_amount`, `paid_at` i `payment_status` — to radi admin change forma.

## Admin ponašanje
- Partial plaćanje i evidentiranje plaćanja ide kroz change form (Save):
  - ako povećaš `paid_amount` → automatski se kreira payment journal
  - smanjivanje `paid_amount` je blokirano
- Ako `payment_account` nije postavljen, admin pokušava `StockAccountingConfig.default_cash_account`.
- CASH računi se preskaču (ne trebaju plaćanje)
- Poruke:
  - “Djelomično plaćeno: X / Y”
  - “Potpuno zatvoreno (PAID)”

## Buduće
- Nalozi za plaćanje (PaymentOrder)
- Uvoz i knjiženje bankovnih izvoda
Odluka još nije donesena.

[← Back to index](../index.md)