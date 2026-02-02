# Fiskalizacija (EDUC MVP)

> Modul: Tehnički
> Ovisi o: Sales, POS, Configuration
> Koriste ga: POS, Admin

## Sadržaj
- [Konfiguracija](#konfiguracija)
- [Modeli](#modeli)
- [API](#api)
- [Admin](#admin)
- [Statusi](#statusi)
- [Napomene](#napomene)

## Konfiguracija
Environment varijable:
- `FISCAL_CERT_PATH`
- `FISCAL_CERT_PASS`
- `FISCAL_OFFICE_CODE`
- `FISCAL_DEVICE_CODE`
- (opcionalno) `FISCAL_OIB`
- (opcionalno) `FISCAL_SEND_ENABLED=false`

OIB se primarno uzima iz `CompanyProfile.oib`.

## Modeli
`FiscalReceipt` (OneToOne na `SalesInvoice`):
- `status`, `zki`, `jir`
- `xml_request`, `xml_response`
- `qr_payload`, `error_message`

`PosReceipt` i `PosReceiptItem`:
- gotovinski POS račun
- PDV stopa po stavci (`vat_rate`)
- totals na razini računa

## API
**POST** `/api/pos/receipts/` kreira POS račun:
```json
{
  "items": [
    { "artikl": 1171, "quantity": 1, "unit_price": 2.60 }
  ],
  "pos_id": 1,
  "warehouse_id": 4
}
```

**POST** `/api/pos/fiscalize-invoice/`

**POST** `/api/pos/receipts/{id}/fiscalize/`

**POST** `/api/pos/receipts/{id}/storno/`

**GET** `/api/pos/receipts/{id}/print/` (PDF)

Body:
```json
{ "invoice_id": 123 }
```

Odgovor:
```json
{
  "invoice_id": 123,
  "status": "pending",
  "zki": "...",
  "jir": "",
  "qr": "..."
}
```

## Admin
U `SalesInvoice` listi postoji akcija **“Fiskaliziraj odabrane racune”**.
`FiscalReceipt` je vidljiv u adminu kao zaseban model.

## Statusi
- `draft` – inicijalno stanje
- `pending` – ZKI izračunat (EDUC/PROD slanje još nije aktivno)
- `success` – JIR zaprimljen (TODO)
- `error` – greška pri fiskalizaciji

## Napomene
Trenutno se radi **MVP**: ZKI + QR payload.
Slanje XML‑a u Poreznu (JIR) je **TODO** i uključuje XML potpis.

[← Back to index](../index.md)
