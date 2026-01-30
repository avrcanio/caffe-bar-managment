# POS PIN autentikacija

> Modul: Tehnički
> Ovisi o: POS app, Auth
> Koriste ga: POS klijent, Admin

## Sadržaj
- [Model](#model)
- [API](#api)
- [Admin](#admin)

## Model
`PosProfile`:
- `user` (FK na auth.User)
- `pin_hash` (hashed PIN)
- metode `set_pin(...)` i `check_pin(...)`

## API
**POST** `/api/pos/pin/verify/`

Payload:
```json
{ "pin": "1234" }
```

Odgovor:
- `{"ok": true}` ako PIN odgovara
- `{"ok": false}` ako PIN nije valjan

Napomena: endpoint zahtijeva autentikaciju korisnika.

## Admin
U adminu se PIN postavlja kroz `PosProfile` formu:
- unos 4–6 znamenki
- prikaz statusa (postavljen / nije postavljen)

[← Back to index](../index.md)
