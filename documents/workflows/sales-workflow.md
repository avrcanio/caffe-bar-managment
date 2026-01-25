# Prodajni tijek rada

> Modul: Tijekovi rada
> Ovisi o: Računovodstvena jezgra, Zalihe
> Koriste ga: Operativa, Admin

## Sadržaj
- [Financijska prodaja (gotovina)](#financijska-prodaja-gotovina)
- [Orkestracija prodaje](#orkestracija-prodaje)
- [Auto-replenish](#auto-replenish)
- [Testovi](#testovi)


## Financijska prodaja (gotovina)
`post_sales_cash(...)`:
- D blagajna (gross)
- P prihod (net)
- P PDV obveza (vat)

Konta se uzimaju iz `DocumentType`:
- `revenue_account`
- `vat_output_account`

## Orkestracija prodaje
`post_sale(...)`:
1) robno: `post_stock_out(... purpose=SALE, auto_cogs=True)`
2) COGS: automatski kroz config
3) financije: `post_sales_cash(...)`
4) audit: veže `StockMove.sales_journal_entry` na sales journal

## Auto-replenish
Ako prodaja ide sa šanka, a fali robe:
- radi transfer iz glavnog skladišta u šank (ako config dozvoljava)

## Testovi
- post_sale kreira:
  - FIFO alokacije
  - COGS journal
  - sales journal
  - linkove na move

[← Back to index](../index.md)