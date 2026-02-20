# Sokovi / Inventure / Prodaja (sažetak)

Ovaj dokument sažima izračune koje smo radili za artikle (sokovi + Red Bull) između inventura i prodaje po računima.

## Vremenski raspon

Gledamo period između:
- `inventory 24 submitted_at` (lokalno Europe/Zagreb): **2026-02-13 20:13:13**
- `inventory 30 submitted_at` (lokalno Europe/Zagreb): **2026-02-14 02:33:25**

Za prodaju koristimo `SalesInvoiceItem` i vrijeme računa `SalesInvoice.issued_at` (lokalno vrijeme prikaza).

## Metod izračuna (po artiklu)

Za svaki artikl koji je prisutan na inventuri 24 i 30:

1. `inv24_qty` = izbrojano na inventuri 24
2. `sold` = suma `SalesInvoiceItem.quantity` u gore navedenom periodu (filter na `invoice.issued_at`)
3. `expected_inv30` = `inv24_qty - sold`
4. `inv30_qty` = izbrojano na inventuri 30
5. `diff` = `inv30_qty - expected_inv30`
   - `diff > 0` = visak
   - `diff < 0` = manjak

## Rezultati za sve artikle (inventory 24 i 30)

```
code        name                                         inv24   sold   expected_inv30  inv30   diff
40822549    Schweppes Bitter Lemon 0,25 l                 37      31     6              24      +18
90357985    Coca Cola Zero 0,25 l                         62      23     39             54      +15
9002515427595 Pago Naranča 0.2 l                          38      0      38             25      -13
3858884601359 Jana Voda 0.33 l                            44      30     14             3       -11
3877000209040 Orangina 0,25 l                              30      22     8              18      +10
54490086    Coca Cola 0,25 l                              87      80     7              16      +9
3856028502012 Jamnica Limunada 0,33 l                     20      0      20             12      -8
3850131005620 Hidra Up naranča 0,5 l                      14      0      14             9       -5
3856028505327 Jamnica Mineralna Voda 0,33 L               49      23     26             21      -5
40822341    Schweppes Tonic Water 0,25 l                   23      0      23             18      -5
3850131005088 Hidra ISO limun, 0,5 l                      3       4      -1             3       +4
90162800    Red Bull sugarfree 0,25 l                      12      0      12             8       -4
9002490100070 Red Bull 0,25 l                              52      30     22             24      +2
9002515427168 Pago Jabuka 0.2 l                            25      0      25             24      -1
3858884602387 Jamnica Sensation limeta kiwano 0,25 l       19      4      15             15      0
3858890873504 Jamnica Sensation bazga limun 0,25 l         21      0      21             21      0
54023840     Fanta 0,25 l                                  14      0      14             14      0
9002515427182 Pago Marelica 0.2 l                          3       0      3              3       0
9002515427229 Pago Brusnica 0,2 l                          14      0      14             14      0
9002515427236 Pago Crni ribiz 0.2 l                         0       0      0              0       0
```

## Visak / Manjak (po diff)

### Visak (diff > 0)
- `40822549` Schweppes Bitter Lemon 0,25 l: **+18**
- `90357985` Coca Cola Zero 0,25 l: **+15**
- `3877000209040` Orangina 0,25 l: **+10**
- `54490086` Coca Cola 0,25 l: **+9**
- `3850131005088` Hidra ISO limun, 0,5 l: **+4**
- `9002490100070` Red Bull 0,25 l: **+2**

### Manjak (diff < 0)
- `9002515427595` Pago Naranča 0.2 l: **-13**
- `3858884601359` Jana Voda 0.33 l: **-11**
- `3856028502012` Jamnica Limunada 0,33 l: **-8**
- `3850131005620` Hidra Up naranča 0,5 l: **-5**
- `3856028505327` Jamnica Mineralna Voda 0,33 L: **-5**
- `40822341` Schweppes Tonic Water 0,25 l: **-5**
- `90162800` Red Bull sugarfree 0,25 l: **-4**
- `9002515427168` Pago Jabuka 0.2 l: **-1**

### Bez razlike (diff = 0)
- `3858884602387` Jamnica Sensation limeta kiwano 0,25 l
- `3858890873504` Jamnica Sensation bazga limun 0,25 l
- `54023840` Fanta 0,25 l
- `9002515427182` Pago Marelica 0.2 l
- `9002515427229` Pago Brusnica 0,2 l
- `9002515427236` Pago Crni ribiz 0.2 l

## Sokovi u višku (na osnovu 4 artikla)

Sokovi koje smo tretirali kao “sok” i njihov visak:
- Schweppes Bitter Lemon `40822549`: +18
- Coca Cola Zero `90357985`: +15
- Orangina `3877000209040`: +10
- Coca Cola `54490086`: +9

Zbroj: `18 + 15 + 10 + 9 = 52` => **52 soka viška** (po ova 4 artikla).

## “Prodaja na boce” (sa slike)

Na slici se vidi 19 redova. Iz toga smo izveli:

### Sokovi iz paketa “+ 4 SOKA”
- Stavki s “+ 4 SOKA”: **12**
- Sokova ukupno: `12 * 4 = 48` => **48 sokova**

Ako to oduzmemo od sokova u višku iz prethodnog poglavlja:
- `52 - 48 = 4` => **4 soka viška (neto, nakon odbitka “+4 SOKA” paketa)**

### Red Bull iz paketa “+ 4 RED BULLA”
- Stavki s “+ 4 RED BULLA”: **2**
- Red Bullova ukupno: `2 * 4 = 8` => **8 Red Bullova**

## Red Bull stanje (po inventura 24 -> 30)

Red Bull artikli i diff:
- Red Bull regular `9002490100070`: **+2**
- Red Bull sugarfree `90162800`: **-4**

Zbroj (neto): `+2 + (-4) = -2` => **manjak 2 Red Bulla ukupno**.

Ako dodatno “odbijemo” prodaju iz paketa `+4 RED BULLA` (8 kom):
- `-2 - 8 = -10` => **manjak 10** (uz tu pretpostavku)

## RepresentationItem provjera (Red Bull u istom periodu)

Provjereno za period `inventory 24 -> 30` i artikle:
- `9002490100070` Red Bull 0,25
- `90162800` Red Bull sugarfree 0,25

Rezultat:
- `RepresentationItem` zapisa: **0**

---

## Inventory 25 -> 31 (normativ, preračun po omjerima)

Report je generiran u: `documents/stock/inv_25_31_normativ.md`

Parametri:
- Period (lokalno): `2026-02-13 20:50` -> `2026-02-14 02:51`
- Broj računa u periodu: **220**
- “Paketi” tipa `X 0,7L + 4 SOKA` / `X 0,7L + 4 RED BULLA` nisu uključeni u potrošnju (da ne dupliramo prodaju boca)

Najveći viškovi (inv31 - očekivano):
- `5010327105215` Monkey Shoulder 0,7l: **+3.9800 L** (≈ **+5.6857** boca)
- `5010677850100` Grey Goose Vodka 0,7l: **+4.2100 L** (≈ **+6.0143** boca)
- `5010327755014` Gin Hendricks 0,7 l: **+3.2800 L** (≈ **+4.6857** boca)

Najveći manjci:
- `5901041003836` Belvedere Bespoke Luminous Vodka 1,75 l: **-1.7500 L** (≈ **-1.0000** boca)
- `4067700015020` Jagermeister 0,7 l: **-1.1500 L** (≈ **-1.1500** boca)
- `500026702362` Johnnie Walker Black Label 1 l: **-1.0000 L** (≈ **-1.0000** boca)

Ručna korekcija (donos):
- Na `inventory 31` za Monkey Shoulder u napomeni stoji: “donio Gogo 6 boca” (nisu zaprimljene).
- To znači da treba **oduzeti 6 boca** od viška: `5.6857 - 6.0000 = -0.3143` boca (≈ `-0.2200 L`).

- Na `inventory 31` za Gin Hendricks u napomeni stoji: “Sina donio 3 boce” (nisu zaprimljene).
- To znači da treba **oduzeti 3 boce** od viška: `4.6857 - 3.0000 = 1.6857` boca (≈ `1.1800 L`).

Ručna korekcija (paketi na računima):
- Tito's Handmade Vodka 0,7l (`619947000112`): u periodu postoje 4 “paketa” (`TITO'S VODKA 0,7L + 4 SOKA/RED BULLA`) = **4 boce**.
- To treba dodati u prodaju: `0.2145 L + (4 * 0.7000 L) = 3.0145 L`, pa diff postaje `-0.1355 L` (≈ `-0.1936` boca).
