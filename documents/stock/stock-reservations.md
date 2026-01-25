# Rezervacije zaliha

> Modul: Zalihe
> Ovisi o: —
> Koriste ga: Nabavni tijek rada, Prodajni tijek rada

## Sadržaj
- [Model](#model)
- [Servisi](#servisi)
- [reserve_stock(...)](#reserve_stock)
- [release_reservation(...)](#release_reservation)
- [Integracija u OUT](#integracija-u-out)
- [Testovi](#testovi)


Rezervacije sprječavaju da više dokumenata “pojede” isto stanje.

## Model
`StockReservation`:
- `warehouse`
- `artikl`
- `quantity`
- `source_type` / `source_id` (ili FK na dokument)
- aktivnost (active/released)

## Servisi

## reserve_stock(...)
- izračun:
  - `on_hand = sum(StockLot.qty_remaining)`
  - `reserved = sum(active reservations)`
  - `available = on_hand − reserved`
- ako nema dovoljno → ValidationError
- kreira rezervaciju

## release_reservation(...)
- zatvara rezervaciju nakon realizacije ili otkazivanja

## Integracija u OUT
`post_stock_out()`:
- provjerava `available` (stanje − rezervirano)
- ako je proslijeđena rezervacija:
  - mora biti aktivna i matchati warehouse/artikl
  - nakon OUT-a se automatski release-a

## Testovi
- rezervacija blokira OUT kad nema dostupnog
- release vraća dostupno
- OUT iz rezervacije release-a rezervaciju

[← Back to index](../index.md)