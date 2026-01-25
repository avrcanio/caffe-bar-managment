# Testiranje

> Modul: Tehnički
> Ovisi o: —
> Koriste ga: Razvoj, DevOps

## Sadržaj
- [Testni paket](#testni-paket)
- [Performance optimizacije](#performance-optimizacije)
- [Napomena o setUpTestData](#napomena-o-setuptestdata)


## Testni paket
- Pokriva accounting, stock, purchases, orders
- Testira:
  - integritet temeljnica (balans, zaključavanje, delete)
  - storno
  - FIFO IN/OUT/TRANSFER
  - storno robnih dokumenata
  - rezervacije
  - auto-replenish
- purchase invoice workflow (admin akcije)
- **Djelomična plaćanja nisu pokrivena testom** (ručno potvrditi).
  - prodaju end-to-end

## Performance optimizacije
- FIFO lotovi:
  - `.select_for_update()`
  - `.only("id","qty_remaining","unit_cost","received_at")`
- COGS total:
  - DB aggregate `Sum(ExpressionWrapper(F("qty") * F("unit_cost")))`

## Napomena o setUpTestData
- Stock testovi često mutiraju DB (lotovi i alokacije), pa se većinom koristi `setUp()`.

[← Back to index](../index.md)