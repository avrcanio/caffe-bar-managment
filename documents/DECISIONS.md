# Odluke

> Modul: Odluke
> Ovisi o: —
> Koriste ga: Svi

## Sadržaj
- [2026-01-25 — 1 firma = 1 baza](#2026-01-25-1-firma-=-1-baza)
- [2026-01-25 — Ledger je singleton](#2026-01-25-ledger-je-singleton)
- [2026-01-25 — FIFO za sve artikle](#2026-01-25-fifo-za-sve-artikle)
- [2026-01-25 — StockAccountingConfig je singleton](#2026-01-25-stockaccountingconfig-je-singleton)
- [2026-01-25 — Prodaja automatski radi COGS za purpose=SALE](#2026-01-25-prodaja-automatski-radi-cogs-za-purpose=sale)
- [2026-01-25 — Ulazni računi: CASH ili DEFERRED](#2026-01-25-ulazni-racuni-cash-ili-deferred)
- [2026-01-25 — Djelomična plaćanja preko change forme](#2026-01-25-djelomicna-placanja-preko-change-forme)
- [2026-01-25 — Rezervacije zaliha kao zaseban sloj](#2026-01-25-rezervacije-zaliha-kao-zaseban-sloj)


## 2026-01-25 — 1 firma = 1 baza
**Status:** prihvaćeno  
**Razlog:** izolacija podataka i jednostavnija operativa  
**Utjecaj:** accounting, konfiguracije, deployment

## 2026-01-25 — Ledger je singleton
**Status:** prihvaćeno  
**Razlog:** podržava pravilo “1 firma = 1 baza”  
**Utjecaj:** accounting, admin, migracije

## 2026-01-25 — FIFO za sve artikle
**Status:** prihvaćeno  
**Razlog:** porezni i inventurni zahtjevi  
**Utjecaj:** stock, accounting, reporting

## 2026-01-25 — StockAccountingConfig je singleton
**Status:** prihvaćeno  
**Razlog:** centralna konfiguracija konta i skladišta  
**Utjecaj:** stock, accounting, admin

## 2026-01-25 — Prodaja automatski radi COGS za purpose=SALE
**Status:** prihvaćeno  
**Razlog:** točan COGS u trenutku prodaje  
**Utjecaj:** stock, accounting, reporting

## 2026-01-25 — Ulazni računi: CASH ili DEFERRED
**Status:** prihvaćeno  
**Razlog:** realni računovodstveni scenariji  
**Utjecaj:** purchases, accounting, admin

## 2026-01-25 — Djelomična plaćanja preko change forme
**Status:** prihvaćeno  
**Razlog:** operativna jednostavnost u adminu  
**Utjecaj:** purchases, accounting, admin

## 2026-01-25 — Rezervacije zaliha kao zaseban sloj
**Status:** prihvaćeno  
**Razlog:** sprječavanje prodaje iznad dostupnog stanja  
**Utjecaj:** stock, workflows