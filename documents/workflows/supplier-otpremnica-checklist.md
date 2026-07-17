# Checklist: otpremnica → artikli → nabavni cjenik

> Modul: Tijekovi rada  
> Primjena: unos robe / cijena iz papirnate otpremnice ili računa-otpremnice  
> Primjeri: Atlantic Trade — Cedevita (A102TP746017443-R-1); Fructus — Voće (2744/PV1/1)

Kada stigne WhatsApp / sken otpremnice, radi se isti redoslijed. Cilj je da agent ili operater može ponoviti postupak za bilo kojeg dobavljača.

## Sadržaj

- [1. Izvuci podatke s dokumenta](#1-izvuci-podatke-s-dokumenta)
- [2. Provjeri dobavljača](#2-provjeri-dobavljaca)
- [3. Provjeri artikle](#3-provjeri-artikle)
- [4. Nabavni cjenik](#4-nabavni-cjenik)
- [5. (Opcionalno) Narudžba / primka](#5-opcionalno-narudzba--primka)
- [6. Predložak management commanda](#6-predlozak-management-commanda)
- [7. Referentni primjer: Atlantic Cedevita](#7-referentni-primjer-atlantic-cedevita)
- [8. Referentni primjer: Fructus Voće](#8-referentni-primjer-fructus-voće)
- [9. Verifikacija](#9-verifikacija)

---

## 1. Izvuci podatke s dokumenta

S otpremnice / računa-otpremnice zabilježi:

| Polje | Primjer |
|-------|---------|
| Dobavljač (naziv) | ATLANTIC TRADE D.O.O. |
| OIB dobavljača | 85106679092 |
| Broj dokumenta | A102TP746017443-R-1 |
| Datum dokumenta | 02.07.2026. |
| Način plaćanja | Gotovina |
| Po stavci: šifra dobavljača, naziv, **EAN ili interna šifra**, količina, **neto cijena / JM**, iznos | |

**Važno za cijene:**

- Na Atlantic / Fructus / sličnim računima stupac „Cijena“ je obično **neto** (bez PDV-a).
- Kontrola: `količina × cijena ≈ iznos stavke`; zbroj neto + PDV = „Za platiti“.
- U `SupplierPriceItem.price` ide **neto** cijena u EUR.
- Voće / povrće (Fructus): JM je često **Kg**, ne Komad; količine mogu biti decimalne (npr. 14,300 kg).

---

## 2. Provjeri dobavljača

Model: `contacts.Supplier` (`name`, `tax_number` = OIB, `street`, `town`).

```bash
docker exec mozzart python manage.py shell -c "
from contacts.models import Supplier
from django.db.models import Q
q = Supplier.objects.filter(
    Q(name__icontains='atlantic') | Q(tax_number__icontains='85106679092')
)
for s in q:
    print(s.id, s.rm_id, s.name, s.tax_number, s.street, s.town)
"
```

- Ako postoji → zabilježi `Supplier.id` (npr. Atlantic = **13**).
- Ako ne postoji → kreiraj dobavljača prije cjenika / narudžbe.
- Manje razlike u OIB-u ili adresi (stari Remaris podaci) ne znače automatski „nema dobavljača“ — potvrdi po nazivu.

---

## 3. Provjeri artikle

Artikli se tipično traže po **EAN-u** u `Artikl.code` (i/ili `ArtiklDetail.barcode`). Za voće/povrće bez EAN-a na papiru traži po **nazivu** (npr. Lubenica, Dinja, Limun) — interna `Artikl.code` nije šifra s Fructus računa.

Za svaku stavku otpremnice:

1. Traži `Artikl.objects.filter(code=ean)` ili `detail__barcode=ean` (ili `name__icontains=…` za Kg artikle).
2. Ako nema → kreiraj artikl (šifra = EAN ako postoji, `is_stock_item=True`, porezna grupa, kategorija, JM Komad ili Kg…).
3. Ako ima → zabilježi `id`, `code`, `name`.

```bash
docker exec mozzart python manage.py shell -c "
from artikli.models import Artikl
from django.db.models import Q
eans = ['3850322009154', '3850322009406']  # zamijeni
for ean in eans:
    a = Artikl.objects.filter(Q(code=ean) | Q(detail__barcode=ean)).first()
    print(ean, '->', (a.id, a.name) if a else 'MISSING')
"
```

Ne miješaj **kutiju** i **pojedinačni** artikl (npr. Cedevita Limun kom vs kutija 50×19 g) — za nabavu po komadima koristi pojedinačni EAN s otpremnice.

---

## 4. Nabavni cjenik

Modeli (`orders`):

- `SupplierPriceList` — `supplier`, `name`, `valid_from`, `valid_to`, `currency`, `is_active`
- `SupplierPriceItem` — `price_list`, `artikl`, `unit_of_measure`, `price`  
  (unique: `price_list` + `artikl`)

Pravila:

1. Jedinica mjere: **Komad** (`rm_id=3`) za komadne artikle; **Kg** (`rm_id=1`) za voće/povrće (Fructus).
2. `valid_from` — datum koji zada korisnik (npr. 1.5.2026. / 1.7.2026.), ne nužno datum otpremnice.
3. Cijena = neto s dokumenta.
4. Idempotentnost: ako cjenik istog imena već postoji, dodaj samo nedostajuće stavke; skip ako je artikl već na aktivnom cjeniku istog dobavljača.
5. U novi cjenik idu **samo artikli koji još nisu** na aktivnom nabavnom cjeniku tog dobavljača (npr. Limun već postoji → ne duplicirati; Lubenica/Dinja → dodati).
6. Ne dira se prodajni cjenik (`SalesPriceList`) osim ako korisnik eksplicitno traži.

**Pokretanje (obrazac):**

```bash
docker exec mozzart python manage.py create_<supplier>_<grupa>_supplier_pricelist --dry-run
docker exec mozzart python manage.py create_<supplier>_<grupa>_supplier_pricelist
```

Referentni commandi:

- [`create_atlantic_cedevita_supplier_pricelist.py`](../../app/artikli/management/commands/create_atlantic_cedevita_supplier_pricelist.py)
- [`create_tdr_supplier_pricelist.py`](../../app/artikli/management/commands/create_tdr_supplier_pricelist.py)
- [`create_fructus_voce_supplier_pricelist.py`](../../app/artikli/management/commands/create_fructus_voce_supplier_pricelist.py)

---

## 5. (Opcionalno) Narudžba / primka

Ako treba i robni/dokumentarni trag:

1. `PurchaseOrder` + stavke (količine s otpremnice, cijene iz cjenika ili **eksplicitno s računa**).
2. Datum narudžbe: tipično **jedan dan prije** datuma računa/otpremnice (npr. račun 14.07. → PO 13.07.).
3. Ako već postoji druga Fructus/dobavljač PO istog dana, **ne skipati cijeli dan** — skip samo ako postoji PO s istim setom artikl+količina (line signature). Vidi Fructus command.
4. Zatim `WarehouseInput` (primka) i knjiženje u skladište — vidi [purchase-workflow.md](purchase-workflow.md) i [operations-step-by-step.md](operations-step-by-step.md).

Referentni commandi:

- [`create_atlantic_cedevita_otpremnica_purchase_order.py`](../../app/artikli/management/commands/create_atlantic_cedevita_otpremnica_purchase_order.py)
- [`create_fructus_otpremnica_2744_purchase_order.py`](../../app/artikli/management/commands/create_fructus_otpremnica_2744_purchase_order.py)
- Slični: `create_tdr_otpremnica_*`, `create_koktel_otpremnica_*`

---

## 6. Predložak management commanda

Novi cjenik = kopija Atlantic/TDR/Fructus commanda s novim konstantama:

```python
SUPPLIER_ID = 13                    # contacts.Supplier.id
KOMAD_UOM_RM_ID = 3                 # ili KG_UOM_RM_ID = 1 za voće
PRICELIST_NAME = "Cedevita"         # kratki naziv grupe proizvoda
PRICELIST_VALID_FROM = date(2026, 5, 1)

ITEMS = [
    ("3850322009154", Decimal("0.46")),  # EAN / Artikl.code, neto EUR/JM
    # ...
]
```

Obavezno:

- `--dry-run`
- `transaction.atomic()` pri pisanju
- fail hard ako artikl ili dobavljač ne postoje
- skip već postojećih stavki

Lokacija: `app/artikli/management/commands/`.

---

## 7. Referentni primjer: Atlantic Cedevita

**Dokument:** račun-otpremnica Atlantic Trade, br. A102TP746017443-R-1, 02.07.2026.

**Dobavljač:** ATLANTIC TRADE d.o.o. — `Supplier.id=13` (rm_id=28).

**Artikli (svi postoje / dodani prije cjenika):**

| EAN | Artikl id | Naziv u bazi | Neto cijena |
|-----|-----------|--------------|-------------|
| 3850322009154 | 1113 | Cedevita Limun 19 gr | 0,46 |
| 3850322009406 | 1312 | Cedevita Bazga Limun 19g | 0,46 |
| 3850322016343 | 1292 | Cedevita Ananas Mango 19gr | 0,46 |
| 3850322016978 | 1293 | Cedevita Limunska Trava 19gr | 0,46 |

**Cjenik:**

- Naziv: `Cedevita`
- `valid_from`: **2026-05-01**
- Dobavljač: Atlantic (13)
- UOM: Komad
- Command: `create_atlantic_cedevita_supplier_pricelist`

**Što je urađeno u sesiji (redoslijed):**

1. Čitanje slike otpremnice iz `.temp/wp/…`
2. Match artikala po EAN-u → 3/4 postojeća; dodan Bazga Limun (1312)
3. Match dobavljača → Atlantic id=13
4. Kreiran nabavni cjenik s cijenama s računa i `valid_from=1.5.2026`
5. (Opcionalno) purchase order command za količine 50×4

---

## 8. Referentni primjer: Fructus Voće

**Dokument:** račun-otpremnica Fructus d.o.o., br. **2744/PV1/1**, 14.07.2026.  
Izvor slike: `.temp/wp/WhatsApp Image 2026-07-14 at 12.24.14.jpeg`

**Dobavljač:** Fructus d.o.o. — `Supplier.id=14` (rm_id=36), OIB 02599933894.

**Artikli s računa (match po nazivu / postojećem `Artikl.code`):**

| Šifra (Fructus) | Artikl id | Code u bazi | Naziv | Neto €/kg | Na cjeniku prije? |
|-----------------|-----------|-------------|-------|-----------|-------------------|
| 00220 | 1313 | 16769594 | Lubenica | 1,00 | ne → dodano |
| 00453 | 1314 | 27809119 | Dinja | 1,60 | ne → dodano |
| 00059 | 1155 | 98212780 | Limun | 1,41 | da → skip cjenik |

**Cjenik:**

- Naziv: `Voće`
- `valid_from`: **2026-07-01**
- Dobavljač: Fructus (14)
- UOM: **Kg**
- Stavke: samo Lubenica + Dinja
- Command: `create_fructus_voce_supplier_pricelist`

**Narudžba:**

- Datum: **13.07.2026.** (jedan dan prije računa)
- Status: `confirmed`, plaćanje Gotovina
- Stavke: sve 3 s računa, **eksplicitne cijene** s dokumenta (Limun inače resolvea stariju cijenu 1,40)
- Druga PO istog dana uz postojeći `#328` (druga otpremnica) — skip samo po line signature
- Command: `create_fructus_otpremnica_2744_purchase_order`
- Rezultat: PO `#332`, neto ≈ 20,69 €

**Što je urađeno (redoslijed):**

1. OCR / čitanje slike otpremnice
2. Match dobavljača → Fructus id=14
3. Match artikala → sva 3 postoje; Limun već na aktivnom cjeniku
4. Kreiran nabavni cjenik `Voće` s Lubenicom/Dinjom
5. Kreirana druga narudžba 13.07. s tri stavke

```bash
docker exec mozzart python manage.py create_fructus_voce_supplier_pricelist --dry-run
docker exec mozzart python manage.py create_fructus_voce_supplier_pricelist
docker exec mozzart python manage.py create_fructus_otpremnica_2744_purchase_order --dry-run
docker exec mozzart python manage.py create_fructus_otpremnica_2744_purchase_order
```

---

## 9. Verifikacija

```bash
docker exec mozzart python manage.py shell -c "
from contacts.models import Supplier
from orders.models import SupplierPriceList, SupplierPriceItem
s = Supplier.objects.get(pk=13)  # zamijeni (Fructus=14)
for pl in SupplierPriceList.objects.filter(supplier=s).order_by('-valid_from'):
    print(pl.id, pl.name, pl.valid_from, pl.is_active, pl.items.count())
    for i in pl.items.select_related('artikl', 'unit_of_measure'):
        uom = i.unit_of_measure.name if i.unit_of_measure else None
        print(' ', i.artikl.code, i.artikl.name, i.price, uom)
"
```

Checklist:

- [ ] Dobavljač postoji
- [ ] Svi artikli s dokumenta postoje (EAN ili naziv)
- [ ] Cjenik ima točan `valid_from` i `name`
- [ ] Sve nove stavke: neto cijena + ispravna JM (Komad ili Kg)
- [ ] U cjenik idu samo artikli koji prije nisu bili na aktivnom listu
- [ ] Dry-run pa stvarni run bez duplikata
- [ ] (Ako PO) datum = dan prije računa; druga PO istog dana OK ako je drugi set stavki

---

## Povezano

- [Nabavni tijek rada](purchase-workflow.md)
- [Narudžbe dobavljaču](purchase-orders.md)
- [Operativni koraci](operations-step-by-step.md)

[← Back to index](../index.md)
