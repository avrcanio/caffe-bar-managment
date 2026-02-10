# POS Sustav (Blagajna) - Blueprint

Ovaj dokument je razvojni blueprint za POS sustav u ovom repozitoriju (Django backend + postojeći Windows POS klijent "Blagajna" i/ili budući PWA/klijent). Cilj je da se razvoj vodi kroz jasne domenske granice, API ugovore i iterativne isporuke.

## 1) Trenutno Stanje U Repozitoriju

Backend je Django (DRF, TokenAuth/SessionAuth, Celery, Postgres). POS domena je primarno u `app/pos/*` i djelomicno u `app/sales/*`.

Postojece kljucne domenske komponente:

- Uredaji i autentikacija:
  - `pos.Pos`, `pos.PosDevice`, `pos.PosProfile` (PIN + device binding)
  - Endpointi: `POST /api/pos/pin/login/`, `POST /api/pos/pin/verify/`
- Racuni:
  - `pos.PosReceipt`, `pos.PosReceiptItem`
  - Endpointi: `POST /api/pos/receipts/`, `POST /api/pos/receipts/{id}/fiscalize/`, `POST /api/pos/receipts/{id}/storno/`, `GET /api/pos/receipts/{id}/print/`
- Smjena i blagajna:
  - `sales.ShiftTurnover`, `sales.ShiftTurnoverClose`, `sales.ShiftTurnoverExpense`, `sales.ShiftCashHandover`
  - Endpointi: `GET /api/pos/shift/turnover/`, `POST /api/pos/shift/close/`, `POST /api/pos/shift/expense/`, `GET /api/pos/shift/cash-expected/`, `POST /api/pos/shift/cash-handover/`
- Konfiguracija POS layouta:
  - `pos.PosScreen`, `pos.PosScreenItem`, `pos.PosMode`, `pos.PosModeScreen`
- Fiskalizacija:
  - `pos/fiscal.py` generira ZKI i QR payload; slanje prema Poreznoj (JIR) je trenutno `NotImplemented`.
  - `configuration.CompanyProfile` drzi podatke o fiskal certifikatu (P12) i lozinci.

Napomena: trenutno se zatvaranje smjene (`POST /api/pos/shift/close/`) racuna preko `sales.SalesInvoice` (uvoz iz Remaris-a) i flag-a `is_card`. To je vazna odluka: treba odluciti da li POS promet i "Remaris promet" trebaju dijeliti istu knjigu racuna/izvjestaje ili se izvjestavaju odvojeno.

## 2) Ciljevi I Granice (Scope)

Minimalni POS (MVP):

- Prijava operatera (PIN, vezan za uredaj).
- Otvaranje blagajne (preuzimanje) prije rada.
- Izdavanje racuna (stavke, porezne stope, ukupni iznosi).
- Fiskalizacija (ZKI + QR + kasnije JIR).
- Ispis racuna (PDF za test, kasnije native/ESC-POS).
- Storno/refund (storno racun vezan na original).
- Zatvaranje smjene + rashodi + primopredaja (opening/closing) + evidencija manjka/viska.

Izvan MVP-a (planirano):

- Kartice i split payments (cash + card + voucher + tips).
- Stolovi, narudzbe, kuhinja/bar printeri (KOT/BOT), statusi pripreme.
- Offline-first POS (queue + sync), conflict strategije.
- Integracija sa skladistem (stock out) i nabavom.
- Napredni popusti, kuponi, happy hour, cjenici po vremenu/mestu.

## 3) Arhitektura (Predlozeno)

### 3.1 Backend (Django/DRF)

Predlozena podjela po bounded-contextima:

- `pos`:
  - Autentikacija POS operatera (PIN), registracija uredaja
  - Racun: kreiranje, fiskalizacija, storno, print
  - POS UI konfiguracija (screen/mode layout)
- `sales`:
  - Smjena i blagajna (turnover/close/expenses/cash handover)
  - Konsolidacija prometa (ukljucujuci uvoz iz drugih sustava)
- `accounting`:
  - Automatizirane temeljnice za visak/manjak (vec postoji u cash handover flowu)

Tehnicke smjernice:

- Uvesti idempotency na POS write endpointima (npr. `Idempotency-Key` header) kako bi se klijent mogao sigurno retry-at u slucaju timeouta.
- Osigurati transakcijsku konzistenciju: kreiranje racuna + stavke + (fiskalizacija update) unutar jasnih transaction boundarya.
- Audit trail: zadrzati `auditlog` gdje ima smisla (racuni, storno, cash handover).

### 3.2 POS Klijent(i)

Trenutno postoji Windows MSIX "Blagajna" (vidi `frontend/src/app/download/page.tsx`). Blueprint treba tretirati POS klijent kao "thin client" koji:

- radi login preko `POST /api/pos/pin/login/`
- lokalno cache-a konfiguraciju artikala + POS layout (screen/mode)
- salje izdane racune na backend (ili radi offline queue)
- pokrece fiskalizaciju i print

Ako se radi PWA/Next POS, ciljati na:

- touch-friendly UI, full-screen, kiosk mode
- offline queue (IndexedDB) + background sync
- printer integracija (USB/Bluetooth preko native bridge-a ili companion service)

## 4) Domenski Model (Minimalni)

### 4.1 Racun (POS)

Entiteti:

- `PosReceipt`:
  - identitet: `(office_code, device_code, issued_on, receipt_number)` mora biti unique
  - statusi: `draft -> issued -> fiscalized` ili `error`, i `storno`
  - fiskal: `zki`, `jir`, `qr_payload`
- `PosReceiptItem`:
  - artikl, qty, unit_price, vat_rate, net/vat/total

Pravila:

- Receipt number treba biti generiran server-side, per office/device/day (vec postoji u `pos/services.py`).
- Fiskalizacija treba biti idempotentna: ako `zki/jir` vec postoje, endpoint treba vratiti postojece vrijednosti bez nuspojava.
- Storno moze postojati najvise jednom po originalu (vec enforced one-to-one `storno_of`).

### 4.2 Smjena/Blagajna

Entiteti u `sales`:

- `ShiftTurnover`: agregat (user + date + warehouse + pos)
- `ShiftCashHandover`: opening/closing, expected/count/diff + note + automatska temeljnica za diff
- `ShiftTurnoverClose`: cash_counted + card_total + note + rashodi
- `ShiftTurnoverExpense`: rashod u sklopu close-a

Pravila:

- Preuzimanje blagajne (opening) je preduvjet za izdavanje racuna (vec enforced u `PosReceiptCreateView`).
- Predaja (closing) ima "expected_amount" = opening + cash_turnover - expenses.
- Ako postoji diff, napomena je obavezna i generira se temeljnica (vec postoji).

## 5) API Blueprint (Kontrakti)

Ovo su minimalni endpointi koje POS klijent treba:

- Auth:
  - `POST /api/pos/pin/login/` -> `{ token, user_id }`
  - (opcionalno) `POST /api/pos/pin/verify/` -> `{ ok: true }`
- Konfiguracija:
  - `GET /api/artikli/` (filteri + paging po potrebi)
  - (planirano) `GET /api/pos/screens/`, `GET /api/pos/modes/` ili jedan "bootstrap" endpoint
- Smjena:
  - `GET /api/pos/shift/cash-expected/`
  - `POST /api/pos/shift/cash-handover/` (opening/closing)
  - `POST /api/pos/shift/expense/`
  - `GET /api/pos/shift/turnover/`
- Racun:
  - `POST /api/pos/receipts/` (kreira racun)
  - `POST /api/pos/receipts/{id}/fiscalize/`
  - `GET /api/pos/receipts/{id}/print/`
  - `POST /api/pos/receipts/{id}/storno/`

Predlozena poboljsanja:

- Standardizirati error format: `{ detail, code, meta }`
- Dodati `receipt_external_id` (UUID iz klijenta) za offline sync i anti-dup.
- Dodati `payment_type` prosirenje: `cash`, `card`, `mixed`, `voucher`, uz payment breakdown tablicu (buduci model).

## 6) Fiskalizacija (HR)

Trenutno:

- ZKI: generiran i spremljen na racun
- QR payload: generiran iz receipt podataka
- JIR: nije implementiran

Blueprint za implementaciju JIR:

- U `pos/fiscal.py` implementirati SOAP/XML slanje prema Poreznoj (signxml + cert iz `CompanyProfile`).
- Uvesti retry strategiju + "outbox" tablicu za neuspjele fiskalizacije (da racun ne ostane izgubljen).
- Dodati statusnu masinu: `issued -> fiscalized` ili `issued -> error` s detaljem, s mogucnoscu ponovne fiskalizacije.
- Integrirati environment switch: demo/test vs produkcija endpointi.

## 7) Operacije, Sigurnost, Observability

- Tokeni: POS klijent koristi TokenAuth (`Authorization: Token <key>`).
- Device binding: `PosProfile.is_registered` + `registered_device_id` (vec postoji); definirati proces "reset/unregister" u adminu.
- Rate limiting: vec postoji `django-axes` za login; POS PIN login je AllowAny i treba paziti na brute force (razmotriti axes integraciju i tu).
- Logovi: dodati strukturirane logove za receipt create/fiscalize/storno + cash handover.
- Timezone: backend koristi `UTC`; POS UI treba prikaz u lokalnom vremenu (Europe/Zagreb) i slati ISO datume.

## 8) Roadmap (Iteracije)

Iteracija 1 (MVP stabilizacija):

- Stabilni API ugovori za POS klijent (request/response + error codes).
- Receipt create + print + storno end-to-end.
- Shift opening/expected/closing end-to-end.
- Tests: unit tests za receipt numbering i storno, smoke test za shift flows.

Iteracija 2 (Fiskalizacija JIR):

- Implementirati slanje u Poreznu + outbox + retry.
- Admin alati: re-fiscalize, pregled errora.

Iteracija 3 (Offline i pouzdanost):

- Idempotency + client-side queue + conflict policy.
- "Bootstrap sync" endpoint (artikli + screen/mode + pos config).

Iteracija 4 (Napredne funkcije):

- Payment breakdown (kartice/mixed), tips.
- Stolovi/narudzbe i kuhinja/bar printeri.
- Stock out (integracija sa `stock`).

## 9) Otvorena Pitanja (Da se zakljucaju prije sirenja)

- Jedinstveni "source of truth" za promet: da li `SalesInvoice` i `PosReceipt` konvergiraju u jedan model, ili se drze odvojeno uz zajednicki reporting sloj?
- Kako POS klijent dobiva listu artikala i POS layout: direktno iz API-ja ili iz posebnog "snapshot" endpointa?
- Politika numeracije racuna: da li office/device dolazi iz POS konfiguracije ili requesta (trenutno je kombinacija)?

