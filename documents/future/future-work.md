# Budući rad

> Modul: Budući rad
> Ovisi o: —
> Koriste ga: Planiranje

## Sadržaj
- [Banka](#banka)
- [POS import](#pos-import)
- [Inventura](#inventura)
- [Izvještaji (kad zatreba)](#izvjestaji-kad-zatreba)
- [UX](#ux)


Ovaj file je popis logičnih sljedećih koraka. Odluka još nije donesena za nijednu stavku ispod.

## Banka
- Model `PaymentOrder` (nalozi za plaćanje)
- Copy/paste ili export za internet bankarstvo
- Uvoz izvoda (CSV / CAMT.053 / MT940)
- Matching transakcija → automatsko knjiženje i zatvaranje obveza

## POS import
- Import računa (pozitivni i storno)
- Grupiranje stavki po artiklu
- Mapiranje POS šifri → Artikl

## Inventura
- Inventure dokument
- Korekcije (ADJUSTMENT) + vrijednosno knjiženje

## Izvještaji (kad zatreba)
- Glavna knjiga
- Bruto bilanca
- Zalihe po skladištu (količina i vrijednost)
- Marže

## UX
- Bolji admin za bulk linije (replenish)
- Posebni ekrani izvan admina (operator-friendly)

[← Back to index](../index.md)