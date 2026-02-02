# AI Chat Customizations (Mozzart)

Datum: 2026-02-02

Ovaj dokument opisuje prilagodbe AI chata (backend + frontend) napravljene u projektu `/srv/mozzart`.

## 1) /ai web stranica (Django)
- Dodana je `/ai` stranica koja radi server-side pretragu artikala po nazivu i prikazuje rezultate u tablici.
- Prikaz uključuje: `id`, `rm_id`, `code`, `name`, `is_sellable`, `is_stock_item` i Normativ ingredient nazive.

Relevantne datoteke:
- `app/ai/views.py`
- `app/templates/ai/search.html`
- `app/config/urls.py` (ruta `path("ai/", AiSearchView.as_view(), name="ai-search")`)

## 2) AI API logika (`app/ai/services.py`)

### 2.1. Pretraga artikala
- Upiti poput `pronađi/pronadi/pronadji mi artikl X` vraćaju detalje artikla (prodajni/skladišni, cijena, normativ, dobavljač).
- Upit `artikl X` ili `prikaži/pokaži mi artikle X` vraća listu svih matching artikala (svaki u svom redu) s linkovima:
  - `/admin/artikli/artikl/<id>/change/`
  - `/ai?q=<naziv>`

### 2.2. ID i RM ID
- Podržani su upiti tipa `id 1178`, `rm_id 584`, `rm 584`, `rmid 584`.

### 2.3. Skladišni artikli i normativ
- Ako je `is_stock_item = False`, AI neće vraćati “nema na skladištu”, nego jasno kaže da nije skladišni artikl i prikaže normativ (ako postoji).
- Normativ uključuje ingredient naziv i količinu.

### 2.4. Prodajna cijena
- Za artikl se traži `SalesPriceItem` iz aktivnog cjenika (default prioritet) i vraća se `unit_price_gross`.

### 2.5. Nabavna cijena i dobavljač
- Za skladišne artikle prikazuje `SupplierPriceItem` + naziv dobavljača (`SupplierPriceList.supplier`).

### 2.6. Stanje po skladištu
- Prikazuje `WarehouseStock.internal_quantity` po skladištu, uz naziv skladišta (`WarehouseId.name`).

### 2.7. “Top” prodaja
- `najprodavaniji artikli jučer` → po količini (qty).
- `najprodavaniji artikli jučer financijski` → po iznosu (amount).

### 2.8. Prodaja po kategoriji pića (DrinkCategory)
- Logika prepoznaje `DrinkCategory` iz upita i koristi najviši parent koji još uvijek sadrži taj naziv (npr. “Pivo”), te uključuje sve potomke.
- Podržani sinonimi:
  - pivo: pivo, piva, pive
  - vino: vino, vina
  - sok: sok, sokovi
  - voda: voda, vode
  - rakija: rakija, rakije
  - kava: kava, kave

### 2.9. Prodaja “samo kava” i univerzalni vremenski filteri
- Vremenski filteri su centralizirani: `danas`, `jučer`, `prekjučer`, `prije X dana`, `prošli tjedan` (Mon–Sun), `prošli mjesec`.
- “Prodaja samo kava …” radi za sve gore navedene vremenske filtere i daje listu artikala + qty + amount.
- Opća prodaja/promet koristi isti time-filter.

### 2.10. Kupljeno od dobavljača (WarehouseInput)
- Upit tipa: `koliko robe je kupljeno kod Koktel ...` koristi `WarehouseInput` + `WarehouseInputItem`.
- Prikazuje:
  - listu kupljenih artikala (qty + amount),
  - listu primki (payment_type, total),
  - ukupni zbroj (`sum(total)`).
- Dobavljač se prepoznaje i iz sinonima: `koktel`, `koktela`, `koktelu`.

### 2.11. Kupljeno po kategoriji pića + dobavljač
- Upiti tipa: `koliko je kupljeno piva kod koktel prošli mjesec`:
  - koriste najviši parent “Pivo” + sve potomke
  - filtriraju `WarehouseInputItem` po dobavljaču + vremenskom filtru
  - vraćaju kupljene artikle po qty i amount

## 3) Frontend AI chat (`frontend/src/app/ai/page.tsx`)
- Chat prikazuje odgovore po redovima i prepoznaje Markdown linkove `[text](url)` kao klikabilne.
- Linkovi koji počinju s `/` renderaju se kao `Link` (Next.js), ostali kao `<a>`.

## 4) API točka
- AI API: `POST /api/ai/query/` s JSON `{ "question": "..." }`.

## 5) Testiranje / restart
- Nakon promjena u backendu: `docker compose restart web`
- Nakon promjena u frontend-u: `docker compose restart frontend`

## 6) Datoteke koje su mijenjane
- `app/ai/services.py`
- `app/ai/views.py`
- `app/config/urls.py`
- `app/templates/ai/search.html`
- `frontend/src/app/ai/page.tsx`

