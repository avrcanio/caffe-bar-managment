# TouchPOS -> Mozzart API (POS Racuni) - Tasks

Ovaj dokument je checklist/backlog sto treba napraviti u TouchPOS (Windows, WPF/XAML + C#) da se spoji na postojeci Django/DRF API i da iz TouchPOS-a mozes izdavati POS racune.

## 0) Preduvjeti (backend)

- Backend (Django) radi u `docker compose` servisu `web` i tipicno je dostupan na:
  - lokalno: `http://<server>:8003` (host) -> `:8000` (container)
- POS endpoints su pod `/api/pos/...` (vidi `app/pos/api.py` i `app/config/urls.py`).
- Token auth: `Authorization: Token <token>`

## 1) Konfiguracija u TouchPOS-u

1. Dodati postavke (app config):
   - `ApiBaseUrl` npr. `https://mozart.sibenik1983.hr` ili `http://<ip>:8003`
   - `DeviceId` (stabilan ID uredjaja; npr. GUID koji se jednom generira i spremi)
   - (opcionalno) default `PosId`, `WarehouseId`, `OfficeCode`, `DeviceCode`
2. Spremanje tokena nakon login-a:
   - token drzati u memoriji + (opcionalno) enkriptirano na disku (DPAPI)
3. HTTP client:
   - koristiti jedan `HttpClient` instance (singleton)
   - default header kada imas token:
     - `Authorization: Token ...`
   - timeouti: npr. 10-20s za create/fiscalize

## 2) Auth Flow (PIN login)

### Endpoint
- `POST {ApiBaseUrl}/api/pos/pin/login/`

### Request (preporuceno)
```json
{
  "username": "konobar1",
  "pin": "1234",
  "device_id": "POS-01"
}
```

### Response
```json
{ "token": "...", "user_id": 123 }
```

### Tasks (TouchPOS)
1. Login ekran (vec postoji): nakon unosa PIN-a pozvati endpoint i spremiti token.
2. `device_id` uvijek slati:
   - ako je POS profil vec registriran na drugi uredjaj, API vraca 403
   - prvi login moze "registrirati" profil na taj `device_id`
3. Nakon login-a: testirati `GET /api/me/` (opcionalno) radi provjere tokena.

## 3) Smjena/Blagajna (out-of-scope za ovaj zadatak)

Ovaj dio privremeno ne radimo u TouchPOS-u. Fokus je da logirani user moze izdati POS racun, a `warehouse` se automatski dodjeljuje prema POS uredjaju.

Napomena (backend):
- `POST /api/pos/receipts/` sad moze primiti `device_id` i sam pronaci `pos` i `warehouse` preko `PosDevice`.
- Obavezni "opening" je iza flaga `POS_REQUIRE_OPENING` (trenutno default `false`).

## 4) Izdavanje racuna (POS receipt)

### 4.1 Create receipt
- `POST {ApiBaseUrl}/api/pos/receipts/`

Request:
```json
{
  "device_id": "POS-01",
  "office_code": "POS1",
  "device_code": "1",
  "payment_type": "cash",
  "items": [
    { "artikl": 123, "quantity": "1", "unit_price": "2.50" },
    { "artikl": 124, "quantity": "2", "unit_price": "3.00" }
  ]
}
```

Response:
```json
{
  "receipt_id": 55,
  "receipt_number": 12,
  "issued_at": "2026-02-08T10:15:00Z",
  "total_amount": "8.50",
  "net_amount": "6.80",
  "vat_amount": "1.70",
  "currency": "EUR",
  "status": "issued"
}
```

Ako zelis explicitno override-at mapping, mozes i dalje poslati `pos_id` ili `warehouse_id` (rm_id), ali preporuka je da TouchPOS salje samo `device_id`.

### 4.2 Fiscalize receipt (ZKI/QR; JIR trenutno nije implementiran)
- `POST {ApiBaseUrl}/api/pos/receipts/{receipt_id}/fiscalize/`

Response:
```json
{ "receipt_id": 55, "status": "fiscalized", "zki": "...", "jir": "", "qr": "..." }
```

### 4.3 Print (PDF)
- `GET {ApiBaseUrl}/api/pos/receipts/{receipt_id}/print/`
- Response: `application/pdf`

### 4.4 Storno
- `POST {ApiBaseUrl}/api/pos/receipts/{receipt_id}/storno/`

### Tasks (TouchPOS)
1. Napraviti "cart" UI:
   - dodavanje artikla, promjena kolicine, cijene (unit_price)
2. Na "Naplati":
   - provjeri/opening flow (ako treba)
   - `create receipt`
   - (opcionalno) odmah `fiscalize receipt`
   - print (PDF download -> lokalni print pipeline)
3. Error handling:
   - 401/403: token istekao ili nije validan -> vrati na login
   - 423: opening required -> odvedi na opening ekran
   - 400: prikazi `detail`
4. Storno flow:
   - UI za odabir originalnog racuna (minimalno unos broja ili lista zadnjih N)
   - pozovi storno endpoint i isprintaj storno racun

## 5) Artikli (product catalog)

Za izdavanje racuna treba lista artikala i cijena.

Postojeci endpointi:
- `GET {ApiBaseUrl}/api/artikli/` (paging)
- `GET {ApiBaseUrl}/api/artikli/{rm_id}/` (detalj)

### Tasks (TouchPOS)
1. Napraviti sync/caching:
   - na startu aplikacije: povuci artikle (paging) i spremi lokalno (SQLite/JSON)
2. Mapirati `Artikl.id` (integer) koji POS API ocekuje u `items[].artikl`
3. UI kategorije/tražilica (minimalno search + favorites)

## 6) Minimalni End-to-End Test (manual)

1. Login (PIN) -> dobij token
2. `POST /api/pos/receipts/` s 1-2 stavke + `device_id`
3. `POST /api/pos/receipts/{id}/fiscalize/`
4. `GET /api/pos/receipts/{id}/print/` -> print

## 7) Preporucene dorade (za pouzdanost)

1. Idempotency:
   - trenutno nema idempotency key; ako TouchPOS retry-a `create receipt` nakon timeouta, moze doci do duplih racuna.
   - preporuka: uvesti `Idempotency-Key` ili `receipt_external_id` (UUID) i server-side dedup.
2. Offline:
   - queue racuna lokalno i sync kada mreza dodje (buduci korak).
3. Payments:
   - trenutno `payment_type` je samo `cash`; za kartice/mixed treba prosirenje modela/API-ja.

## 8) Referenca (backend kod)

- URL rute: `app/config/urls.py`
- POS API: `app/pos/api.py`
- POS modeli: `app/pos/models.py`
- POS services (broj racuna, stavke): `app/pos/services.py`
- Fiskal (ZKI/QR; JIR TBD): `app/pos/fiscal.py`
