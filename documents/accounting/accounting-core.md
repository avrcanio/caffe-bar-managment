# Računovodstvena jezgra

> Modul: Računovodstvo
> Ovisi o: —
> Koriste ga: Tijekovi rada (nabava, prodaja), Admin

## Sadržaj
- [Kontni plan (Account)](#kontni-plan-account)
- [Temeljnice (JournalEntry)](#temeljnice-journalentry)
- [Stavke (JournalItem)](#stavke-journalitem)
- [Periodi (Period)](#periodi-period)
- [Storno (reverse)](#storno-reverse)
- [Admin (ključne akcije)](#admin-kljucne-akcije)
- [Testovi](#testovi)


Ovaj dio opisuje osnovu financijskog modula: kontni plan, temeljnice, stavke, periode, storno i zaštite integriteta.

## Kontni plan (Account)
- Hijerarhija konta: `parent` → `children`
- `is_postable` određuje smije li se knjižiti na konto
- `type` i `normal_side` služe za logiku i izvještaje

**Pravila:**
- Na konta koja imaju podkonta (`children`) ne bi se smjelo knjižiti (`is_postable=False`).
- Jedinstvenost: `code` je unique (u bazi je singleton ledger, ali model podržava izolaciju).

## Temeljnice (JournalEntry)
Statusi:
- `DRAFT` – nacrt, dopuštene izmjene
- `POSTED` – proknjiženo, zaključano
- `VOID` – poništeno (samo za DRAFT)

**Balans:**
- Temeljnica mora biti uravnotežena: zbroj Duguje = zbroj Potražuje.

**Zaključavanje:**
- POSTED/VOID se ne može mijenjati (status i datum).
- POSTED/VOID se ne može brisati.
- Zaključani period blokira knjiženje.

## Stavke (JournalItem)
- Svaka stavka je ili Duguje ili Potražuje (ne oboje).
- `debit >= 0`, `credit >= 0`.
- Ne može se knjižiti na `is_postable=False` konto.
- Ne može se dodavati/mijenjati/brisati stavke ako je entry POSTED ili VOID.

## Periodi (Period)
- Raspon: `start_date` do `end_date`
- `is_closed` zaključava knjiženje u tom periodu
- Preklapanje perioda je blokirano (app-level validacija)

## Storno (reverse)
- `JournalEntry.reverse()` kreira novu temeljnicu s obrnutim stranama (D↔P)
- `reversed_entry` OneToOne veza sprječava dvostruko storno
- Storno storna je blokiran

## Admin (ključne akcije)
- Akcija “Storniraj označene temeljnice”
- U listi se vidi je li nešto stornirano i linkovi original ↔ storno

## Testovi
Pokrenuti i pokrivaju:
- balans / post()
- zabranu brisanja POSTED
- zabranu izmjena POSTED/VOID
- zaključane periode
- storno i zaštite

[← Back to index](../index.md)