# Android Endpoint Mapping Sheet (Barion Payments/Split)

Ovaj dokument je Android-side mapiranje backend API ugovora za issueje:
- #36 Payment entry + full payment flow
- #37 Split wizard + remaining qty state
- #38 Split summary + per-part pay + close gating
- #42 Card tip UX
- #43 Viva confirm mapping

Source of truth: `app/config/urls.py`, `app/barion/api.py`, `app/barion/models.py`.

## 1) Base URL + Auth

Base URL (dev/test):
- `https://mozart.sibenik1983.hr`

Svi endpointi niže traže:

```http
Authorization: Token <TOKEN>
Content-Type: application/json
```

## 2) Endpoint Contract (Current Backend)

### 2.1 Prepare Settlement

- `POST /api/pos/checks/{checkId}/prepare-settlement/`
- Svrha: kreira/azurira settlement partove.
- Idempotency: isti payload daje isti rezultat (200), bez duplikata partova.

Request:

```json
{
  "parts": [
    { "method": "CARD", "amount": "20.00", "tip_amount": "2.00" },
    { "method": "CASH", "amount": "30.00" }
  ],
  "ready_for_issue": false
}
```

Response (200):

```json
{
  "check_id": 123,
  "settlement_status": "PREPARED",
  "payment_status": "UNPAID",
  "parts": [
    { "id": 1, "method": "CARD", "amount": "20.00", "tip_amount": "2.00", "total_charged": "22.00", "fiscal_amount": "22.00", "status": "PREPARED", "provider": "", "provider_ref": "" },
    { "id": 2, "method": "CASH", "amount": "30.00", "tip_amount": "0.00", "total_charged": "30.00", "fiscal_amount": "30.00", "status": "PREPARED", "provider": "", "provider_ref": "" }
  ],
  "totals": {
    "check_total": "50.00",
    "allocated_total": "50.00",
    "confirmed_total": "0.00",
    "remaining_total": "50.00"
  },
  "actions": {
    "can_confirm_card": true,
    "can_issue_receipt": false,
    "can_close_check": false
  }
}
```

Validacije:
- suma `parts[].amount` mora biti jednaka `check_total`
- `tip_amount` je dozvoljen samo za `CARD`
- za `CARD`, `tip_amount <= amount`

### 2.2 Settlement State (Polling/Sync)

- `GET /api/pos/checks/{checkId}/settlement-state/`
- Svrha: Android polling snapshot (single source of truth za UI stanje).

Response (200):

```json
{
  "check_id": 123,
  "check_status": "OPEN",
  "settlement_status": "CARD_CONFIRMED",
  "payment_status": "PARTIAL",
  "pos_receipt_id": null,
  "parts": [
    { "id": 1, "method": "CARD", "amount": "20.00", "tip_amount": "2.00", "total_charged": "22.00", "fiscal_amount": "22.00", "status": "PAID", "provider": "VIVA", "provider_ref": "VIVA-REF-001" },
    { "id": 2, "method": "CASH", "amount": "30.00", "tip_amount": "0.00", "total_charged": "30.00", "fiscal_amount": "30.00", "status": "PREPARED", "provider": "", "provider_ref": "" }
  ],
  "totals": {
    "check_total": "50.00",
    "allocated_total": "50.00",
    "confirmed_total": "20.00",
    "remaining_total": "30.00"
  },
  "actions": {
    "can_confirm_card": false,
    "can_issue_receipt": false,
    "can_close_check": false
  },
  "updated_at": "2026-02-24T14:30:00Z"
}
```

### 2.3 Pay Cash Part (Canonical)

- `POST /api/pos/checks/{checkId}/settlements/parts/{partId}/pay-cash/`
- Svrha: označava pojedini CASH part kao `PAID`.
- Request `amount` je optional guard (ako je poslan, mora odgovarati part amountu).

Request:

```json
{
  "amount": "30.00"
}
```

Response (200):

```json
{
  "check_id": 123,
  "part_id": 2,
  "action": "paid",
  "part_status": "PAID",
  "parts": [
    { "id": 1, "method": "CARD", "amount": "20.00", "tip_amount": "2.00", "total_charged": "22.00", "fiscal_amount": "22.00", "status": "PREPARED", "provider": "", "provider_ref": "" },
    { "id": 2, "method": "CASH", "amount": "30.00", "tip_amount": "0.00", "total_charged": "30.00", "fiscal_amount": "30.00", "status": "PAID", "provider": "", "provider_ref": "" }
  ],
  "totals": {
    "check_total": "50.00",
    "allocated_total": "50.00",
    "confirmed_total": "30.00",
    "remaining_total": "20.00"
  },
  "actions": {
    "can_confirm_card": true,
    "can_issue_receipt": false,
    "can_close_check": false
  }
}
```

Napomena: `action` može biti `paid` ili `already_paid`.

### 2.4 Confirm Card Part (Canonical)

- `POST /api/pos/checks/{checkId}/settlements/parts/{partId}/pay-card/confirm/`
- Svrha: potvrda/odbijanje pojedinog CARD parta nakon provider rezultata.
- Retry semantics:
  - `approved=false` -> part ide u `FAILED`
  - kasnije `approved=true` -> isti part može ići u `PAID`

Request:

```json
{
  "provider": "VIVA",
  "approved": true,
  "amount": "20.00",
  "tip_amount": "2.00",
  "external_txn_id": "TXN-ABC-001",
  "provider_ref": "VIVA-REF-001"
}
```

Response (200):

```json
{
  "check_id": 123,
  "part_id": 1,
  "action": "paid",
  "part_status": "PAID",
  "parts": [
    { "id": 1, "method": "CARD", "amount": "20.00", "tip_amount": "2.00", "total_charged": "22.00", "fiscal_amount": "22.00", "status": "PAID", "provider": "VIVA", "provider_ref": "VIVA-REF-001" },
    { "id": 2, "method": "CASH", "amount": "30.00", "tip_amount": "0.00", "total_charged": "30.00", "fiscal_amount": "30.00", "status": "PREPARED", "provider": "", "provider_ref": "" }
  ],
  "totals": {
    "check_total": "50.00",
    "allocated_total": "50.00",
    "confirmed_total": "20.00",
    "remaining_total": "30.00"
  },
  "actions": {
    "can_confirm_card": false,
    "can_issue_receipt": false,
    "can_close_check": false
  }
}
```

Napomena:
- `action` može biti `paid`, `failed`, `idempotent`
- ako je part već `PAID` s drugim `external_txn_id` -> `409`
- `provider` je trenutno optional, ali podržana vrijednost je `VIVA`

### 2.5 Confirm Card (Legacy Check-Level)

- `POST /api/pos/checks/{checkId}/pay-card/confirm/`
- Legacy endpoint: potvrđuje sve nepotvrđene `CARD` partove odjednom.
- Zadržan radi kompatibilnosti; novi Android flow treba koristiti part-level endpoint iz točke 2.4.

### 2.6 Final Issue Receipt

- `POST /api/pos/checks/{checkId}/issue-receipt/`
- Svrha: finalizacija i zatvaranje checka.
- Zaštićeno PIN step-up mehanizmom (`428` ako nije verificiran PIN).

Request:

```json
{
  "fiscalize": false,
  "payment_type": "cash"
}
```

Response (200):

```json
{
  "check_id": 123,
  "check_status": "CLOSED",
  "settlement_status": "COMPLETE",
  "payment_status": "PAID",
  "receipt_id": 555,
  "receipt_number": 101,
  "status": "issued",
  "total_amount": "50.00",
  "zki": "",
  "jir": "",
  "qr": "",
  "parts": [
    { "id": 1, "method": "CARD", "amount": "20.00", "tip_amount": "2.00", "total_charged": "22.00", "fiscal_amount": "22.00", "status": "PAID", "provider": "VIVA", "provider_ref": "VIVA-REF-001" },
    { "id": 2, "method": "CASH", "amount": "30.00", "tip_amount": "0.00", "total_charged": "30.00", "fiscal_amount": "30.00", "status": "PAID", "provider": "", "provider_ref": "" }
  ],
  "totals": {
    "check_total": "50.00",
    "allocated_total": "50.00",
    "confirmed_total": "50.00",
    "remaining_total": "0.00"
  },
  "actions": {
    "can_confirm_card": false,
    "can_issue_receipt": false,
    "can_close_check": false
  }
}
```

## 3) Statusi i značenja

- `check_status`: `OPEN | CLOSED`
- `payment_status`: `UNPAID | PARTIAL | PAID`
- `settlement_status`: `NONE | PREPARED | CARD_CONFIRMED | READY_FOR_ISSUE | COMPLETE`
- `part.status`: `PREPARED | PAID | FAILED`

Važno:
- `totals.confirmed_total` računa se po sumi `part.amount` za `PAID` partove (ne uključuje tip).
- `CARD` part računa `total_charged = amount + tip_amount` i `fiscal_amount = total_charged`.

## 4) Android DTO Mapping (Kotlin)

Predloženi DTO-i (string amount radi sigurnog decimal parsinga):

```kotlin
data class SettlementPartDto(
    val id: Long,
    val method: String,        // CASH | CARD
    val amount: String,
    val tip_amount: String,
    val total_charged: String,
    val fiscal_amount: String,
    val status: String,        // PREPARED | PAID | FAILED
    val provider: String,
    val provider_ref: String
)

data class SettlementTotalsDto(
    val check_total: String,
    val allocated_total: String,
    val confirmed_total: String,
    val remaining_total: String
)

data class SettlementActionsDto(
    val can_confirm_card: Boolean,
    val can_issue_receipt: Boolean,
    val can_close_check: Boolean
)

data class SettlementStateDto(
    val check_id: Long,
    val check_status: String,      // OPEN | CLOSED
    val settlement_status: String, // NONE | PREPARED | CARD_CONFIRMED | READY_FOR_ISSUE | COMPLETE
    val payment_status: String,    // UNPAID | PARTIAL | PAID
    val pos_receipt_id: Long?,
    val parts: List<SettlementPartDto>,
    val totals: SettlementTotalsDto,
    val actions: SettlementActionsDto,
    val updated_at: String
)
```

## 5) UI Rules (backend-driven)

- `Issue/Close` CTA:
  - enabled samo kad `actions.can_issue_receipt == true`
- Card confirm CTA:
  - enabled kad `actions.can_confirm_card == true`
- Split summary:
  - source of truth je `parts[] + totals + payment_status` iz backend snapshota
- Polling:
  - pozvati `GET settlement-state` nakon svakog write endpointa
  - periodično refresh (npr. 2-3s) dok je ekran otvoren

## 6) Error Handling Matrix

- `400`: payload validacija (npr. split suma, amount/tip mismatch)
- `404`: check/part ne postoji
- `409`: business konflikt (npr. wrong state, wrong method, legacy conflict)
- `428`: PIN verify required prije `issue-receipt`

Android preporuka:
- ne derivirati state lokalno nakon greške; odmah refresh preko `GET settlement-state`.
