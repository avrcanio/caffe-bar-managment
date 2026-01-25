# PDV i povratna naknada

> Modul: Računovodstvo
> Ovisi o: —
> Koriste ga: Tijekovi rada (nabava, prodaja), Admin

## Sadržaj
- [PDV (TaxGroup)](#pdv-taxgroup)
- [Artikl i PDV](#artikl-i-pdv)
- [Povratna naknada (Deposit)](#povratna-naknada-deposit)
- [Knjiženje depozita na ulaznom računu](#knjizenje-depozita-na-ulaznom-racunu)
- [Povrat depozita (kasnije)](#povrat-depozita-kasnije)


Ovaj dio opisuje kako se računa PDV te kako se tretira povratna naknada (depozit) za ambalažu.

## PDV (TaxGroup)
- Postoji model `TaxGroup` s poljem `rate` u decimalnom obliku (npr. 0.2500).
- Jedini izvor istine za PDV stopu: **`TaxGroup.rate`**.
- U obračunima se normalizira u postotak: `percent = rate * 100` → 5 / 13 / 25.

**Postojeće grupe iz baze:**
- PDV25 → 0.2500
- PDV13 → 0.1300
- PDV5 → 0.0500

## Artikl i PDV
- `Artikl.tax_group` određuje PDV stopu artikla.
- Stavke primke koriste `it.tax_group` ili `it.artikl.tax_group`.

## Povratna naknada (Deposit)
- `Artikl.deposit` (FK na Deposit) predstavlja ambalažu/depozit.
- Depozit se računa automatski iz stavki:
  - `deposit_total += artikl.deposit.amount_eur * quantity`

**Važno:**
- Depozit **ne ulazi u PDV osnovicu**.
- Depozit se knjiži na posebno konto `deposit_account` (imovina/potraživanje).

## Knjiženje depozita na ulaznom računu
Ako ulazni račun ima depozit:
- D `deposit_account` = depozit
- PDV se računa samo na osnovice (neto) po stopama.

## Povrat depozita (kasnije)
Tipični scenariji:
- povrat u gotovini
- kupon/bon (vaučer)
- prebijanje na idućem računu

Sva tri scenarija zatvaraju `deposit_account` kreditnom stavkom.

[← Back to index](../index.md)