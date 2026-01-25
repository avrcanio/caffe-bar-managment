# Narudžbe dobavljaču (Purchase Orders)

> Modul: Nabava
> Ovisi o: Konfiguracija (PaymentType), Artikli, Dobavljači
> Koriste ga: Tijekovi rada (nabava), Admin, Frontend

Modul “Narudžbe” pokriva kreiranje, uređivanje i slanje narudžbi dobavljaču te praćenje statusa i stavki.
Uključuje izračune iznosa i generiranje PDF-a za slanje e‑mailom.
Ne obuhvaća knjiženje u računovodstvo niti robno knjiženje u skladištu.

## Sadržaj
- [Svrha i opseg](#svrha-i-opseg)
- [UI tok](#ui-tok)
- [Statusi](#statusi)
- [Podatkovni model](#podatkovni-model)
- [API / Backend (Django: /app/orders)](#api-backend-django-apporders)
- [Frontend (Next.js: /frontend/src/app/purchase-orders)](#frontend-nextjs-frontendsrcapppurchase-orders)
- [DTO / Contract](#dto-contract)
- [Pravila i validacije](#pravila-i-validacije)
- [Rubni slučajevi](#rubni-slucajevi)
- [Otvorena pitanja / TODO](#otvorena-pitanja-todo)


## Svrha i opseg
Modul “Narudžbe” služi za kreiranje i slanje narudžbi dobavljaču, upravljanje stavkama i praćenje statusa narudžbe.
U modul spadaju izračuni iznosa, generiranje PDF-a i slanje e‑mailom.
U modul **ne spada** knjiženje (accounting) ni robno knjiženje (stock) — to rade posebni moduli.

## UI tok
- Lista narudžbi (pregled, filteri, statusi)
- Kreiranje nove narudžbe
- Pregled detalja narudžbe
- Uređivanje narudžbe i stavki

Lokacija FE koda:
- `frontend/src/app/purchase-orders/page.tsx` (lista)
- `frontend/src/app/purchase-orders/new/page.tsx` (kreiranje)
- `frontend/src/app/purchase-orders/[id]/page.tsx` (detalj)
- `frontend/src/app/purchase-orders/[id]/edit/page.tsx` (uređivanje)

## Statusi
Statusi u modelu:
- `created` → Kreirana
- `sent` → Poslana
- `confirmed` → Potvrđena
- `received` → Zaprimljena
- `canceled` → Otkazana

## Podatkovni model
Glavni entiteti:
- `orders.PurchaseOrder`
  - `supplier` (FK)
  - `ordered_at`
  - `status`
  - `total_net`, `total_gross`, `total_deposit`
  - `payment_type` (FK na `configuration.PaymentType`)
  - `primka_created` (bool)
- `orders.PurchaseOrderItem`
  - `order` (FK)
  - `artikl` (FK)
  - `quantity`
  - `unit_of_measure`
  - `price`

## API / Backend (Django: /app/orders)
Glavne komponente:
- `models.py` (PurchaseOrder, PurchaseOrderItem)
- `api.py` (serializers + API views)
- `views.py` (potvrda narudžbe)
- `pdf.py` (generiranje PDF-a)

API endpointi:
- `GET/POST /api/purchase-orders/` (lista + kreiranje)
- `GET/PATCH /api/purchase-orders/<id>/` (detalj + izmjena)
- `POST /api/purchase-orders/<id>/send/` (slanje narudžbe emailom)
- `GET/POST /api/purchase-orders/<id>/items/` (stavke narudžbe)
- `GET/PATCH/DELETE /api/purchase-order-items/<id>/` (pojedinačna stavka)
- `GET /api/suppliers/<id>/artikli/` (artikli dobavljača)
- `GET /orders/confirm/<token>/` (potvrda narudžbe preko linka)

## Frontend (Next.js: /frontend/src/app/purchase-orders)
Stranice:
- lista narudžbi
- kreiranje nove
- detalj narudžbe
- uređivanje

## DTO / Contract
**Header (PurchaseOrder):**
- obavezno: `supplier`
- opcionalno: `status` (default: `created`), `ordered_at` (default: now), `payment_type`
- izračunato: `total_net`, `total_gross`, `total_deposit`, `primka_created`

**Items (PurchaseOrderItem):**
- obavezno: `artikl`, `quantity`, `unit_of_measure`
- opcionalno: `price`

**Status enum:** `created | sent | confirmed | received | canceled`

## Pravila i validacije
- `price` se automatski pokušava povući iz aktivnog cjenika dobavljača.
- Ukupni iznosi (`total_*`) se preračunavaju nakon spremanja stavki.
- Slanje narudžbe radi samo ako dobavljač ima `orders_email`.
- Admin akcija “Create warehouse input from purchase order” postavlja `primka_created=True` i status `received`.

## Rubni slučajevi
- Djelomični primitak robe kroz više primki nije formalno definiran u ovom modulu.
- Ako se cijena artikla promijeni nakon slanja, nova cijena se primjenjuje tek na novoj narudžbi.

## Otvorena pitanja / TODO
- Odluka o standardnom workflowu za djelomični primitak još nije donesena.
- Odluka o storno/poništavanju nakon slanja još nije donesena.

[← Back to index](../index.md)
