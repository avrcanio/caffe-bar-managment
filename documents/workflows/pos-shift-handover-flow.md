# POS Flow — Primopredaja Smjene (Cash Control)

Ovaj dokument opisuje kompletan operativni flow za POS blagajnu: preuzimanje i zatvaranje smjene, provjera stanja gotovine i evidencija razlika.

## 1) Login

POS aplikacija radi login preko PIN-a. Nakon login-a obavezno slijedi provjera blagajne.

**POST** `/api/pos/pin/login/`
```json
{
  "username": "marin",
  "pin": "2304",
  "device_id": "DEVICE-UUID-123"
}
```

Response:
```json
{
  "token": "TOKEN",
  "user_id": 12
}
```

## 2) Provjera blagajne (obavezno nakon login-a)

**GET** `/api/pos/shift/cash-expected/?issued_on=YYYY-MM-DD&pos_id=1&warehouse_id=4`

Response:
```json
{
  "turnover_id": 12,
  "issued_on": "2026-02-01",
  "opening_amount": "150.00",
  "opening_source": "previous_closing",
  "cash_turnover": "0.00",
  "expenses_total": "0.00",
  "expected_amount": "150.00",
  "opening_required": true,
  "closing_required": true
}
```

Ako je `opening_required = true`, POS mora **blokirati sve funkcije** dok konobar ne unese stvarno stanje blagajne.

## 3) Preuzimanje smjene (OPENING)

Konobar unosi stvarno izbrojano stanje gotovine.

**POST** `/api/pos/shift/cash-handover/`
```json
{
  "issued_on": "2026-02-01",
  "pos_id": 1,
  "warehouse_id": 4,
  "kind": "OPENING",
  "counted_amount": "150.00",
  "note": ""
}
```

Ako je razlika ≠ 0, **note je obavezna**.

Response:
```json
{
  "id": 55,
  "kind": "OPENING",
  "expected_amount": "150.00",
  "counted_amount": "150.00",
  "difference_amount": "0.00",
  "note": ""
}
```

Nakon uspjeha, POS otkljucava prodaju.

## 4) Blokada prodaje bez OPENING

Ako konobar pokuša napraviti racun bez OPENING, backend vraca:

**POST** `/api/pos/receipts/`
```json
{
  "detail": "Preuzimanje blagajne je obavezno prije rada.",
  "opening_required": true,
  "turnover_id": 12
}
```

Status: **423 LOCKED**. POS mora prikazati ekran preuzimanja.

## 5) Evidencija rashoda (gotovina)

Rashodi se unose kao stavke, vezane uz shift.

**POST** `/api/pos/shift/expense/`
```json
{
  "issued_on": "2026-02-01",
  "pos_id": 1,
  "warehouse_id": 4,
  "amount": "20.00",
  "note": "Sitni troskovi"
}
```

## 6) Zatvaranje smjene (CLOSING)

Konobar prilikom zatvaranja unosi stvarno stanje gotovine.

**POST** `/api/pos/shift/cash-handover/`
```json
{
  "issued_on": "2026-02-01",
  "pos_id": 1,
  "warehouse_id": 4,
  "kind": "CLOSING",
  "counted_amount": "130.00",
  "note": "Manjak"
}
```

Ako postoji razlika, backend automatski kreira **JournalEntry**:
- **Manjak** → konto **4699** / kredit cash konto
- **Visak** → debit cash konto / kredit **7815**

Response:
```json
{
  "id": 56,
  "kind": "CLOSING",
  "expected_amount": "150.00",
  "counted_amount": "130.00",
  "difference_amount": "-20.00",
  "note": "Manjak",
  "journal_entry_id": 999
}
```

## 7) Kartice (oznacavanje)

Prije racunanja cash prometa, racune placene karticom treba oznaciti.

**GET** `/api/pos/invoices/payment-flags/?issued_on=YYYY-MM-DD&pos_id=1&user_id=12`

**PATCH** `/api/pos/invoices/payment-flags/`
```json
{
  "issued_on": "2026-02-01",
  "pos_id": 1,
  "user_id": 12,
  "invoice_ids": [123,124],
  "is_card": true
}
```

Cash promet = samo racuni gdje `is_card = false`.

## 8) Promet smjene (cash-only)

Kreiranje/refresh promjene smjene radi se pri zatvaranju ili po potrebi:

**POST** `/api/pos/shift/close/`
```json
{
  "issued_on": "2026-02-01",
  "pos_id": 1,
  "warehouse_id": 4,
  "cash_counted": "130.00",
  "note": "Manjak"
}
```

Note: `card_total` se racuna automatski iz `is_card` racuna.

---

## Sažetak pravila

- Bez OPENING nema prodaje.
- Kod razlike u blagajni je obavezna napomena.
- Razlike se automatski knjize u JournalEntry.
- Kartice se oznacavaju prije obračuna cash prometa.
