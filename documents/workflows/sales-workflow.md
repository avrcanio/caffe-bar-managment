# Prodajni tijek rada

> Modul: Tijekovi rada
> Ovisi o: Računovodstvena jezgra, Zalihe
> Koriste ga: Operativa, Admin

## Sadržaj
- [Financijska prodaja (gotovina)](#financijska-prodaja-gotovina)
- [Z dnevno (POS promet)](#z-dnevno-pos-promet)
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

## Z dnevno (POS promet)
Ako prodaja dolazi iz POS-a kroz `SalesInvoice`, knjiženje se radi **Z dnevno**:
1) **Kreiraj Z zapis** (SalesInvoice admin akcija “Knjiži Z (dnevno)”)  
   - kreira `SalesZPosting` za `(issued_on, location_id, pos_id)`
   - ne knjiži u glavnu knjigu
2) **Provjeri/po potrebi promijeni konta** na `SalesZPosting`
   - cash / revenue / vat konta
3) **Post Z u Journal** (SalesZPosting admin akcija)
   - kreira `JournalEntry` i `JournalItem` stavke
   - setira `posted_by`

Standardno konta:
- cash: **10220** (Novac u blagajni)
- revenue: **7603** (Prihodi od prodaje robe na malo)
- vat: **2400** (Obveze za PDV)

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
