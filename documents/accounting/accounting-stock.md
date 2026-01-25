# Računovodstvo zaliha (COGS)

> Modul: Računovodstvo
> Ovisi o: Zalihe (FIFO)
> Koriste ga: Tijekovi rada (nabava, prodaja), Admin

## Sadržaj
- [COGS knjiženje](#cogs-knjizenje)
- [StockMove.purpose](#stockmovepurpose)
- [StockAccountingConfig (singleton)](#stockaccountingconfig-singleton)
- [Auto-replenish](#auto-replenish)
- [Testovi](#testovi)


Ovaj dio opisuje kako se robni FIFO spaja s financijama (COGS, inventory).

## COGS knjiženje
`post_cogs_for_stock_move(move)`:
- radi za OUT s `purpose=SALE`
- izračuna total_cost iz `StockAllocation` (DB aggregate)
- kreira `JournalEntry`:
  - D `cogs_account`
  - P `inventory_account`
- veže na `StockMove.journal_entry`
- blokira dvostruko knjiženje

## StockMove.purpose
- SALE → auto COGS
- WASTE / CONSUMPTION / ADJUSTMENT → trenutno bez auto COGS
- Odluka o automatskom knjiženju za WASTE/CONSUMPTION/ADJUSTMENT još nije donesena.

## StockAccountingConfig (singleton)
Sadrži:
- `inventory_account`
- `cogs_account`
- `default_cash_account`
- `default_deposit_account`
- `default_sale_warehouse`
- `default_purchase_warehouse`
- `default_replenish_from_warehouse`
- `auto_replenish_on_sale`

Validacija:
- zahtijeva `inventory_account` i `cogs_account`
- `default_sale_warehouse` i `default_purchase_warehouse` su obavezni
- `default_cash_account` i `default_deposit_account` su opcionalni (koriste se kao fallback)
- ako je `auto_replenish_on_sale=True`, mora postojati replenish warehouse

## Auto-replenish
U `post_sale()`:
- ako fali na šanku (default_sale_warehouse)
- i `auto_replenish_on_sale=True`
- radi transfer iz `default_replenish_from_warehouse` → šank

## Testovi
- SALE auto COGS
- config fallback
- auto replenishment

[← Back to index](../index.md)