# Katalog servisa

> Modul: Tehnički
> Ovisi o: —
> Koriste ga: Razvoj, DevOps

## Sadržaj
- [accounting/services.py](#accountingservicespy)
- [post_sales_invoice(...)](#post_sales_invoice)
- [post_sales_cash(...)](#post_sales_cash)
- [post_purchase_invoice_cash_from_items(...)](#post_purchase_invoice_cash_from_items)
- [post_purchase_invoice_cash_from_inputs(...)](#post_purchase_invoice_cash_from_inputs)
- [post_purchase_invoice_deferred_from_items(...)](#post_purchase_invoice_deferred_from_items)
- [post_supplier_invoice_payment(...)](#post_supplier_invoice_payment)
- [account_ledger(account, date_from, date_to)](#account_ledgeraccount-date_from-date_to)
- [trial_balance(date_from, date_to, only_postable=True, only_nonzero=True)](#trial_balancedate_from-date_to-only_postable=true-only_nonzero=true)
- [stock/services.py](#stockservicespy)
- [post_warehouse_input_to_stock(...)](#post_warehouse_input_to_stock)
- [post_stock_out(...)](#post_stock_out)
- [post_stock_transfer(...)](#post_stock_transfer)
- [post_cogs_for_stock_move(...)](#post_cogs_for_stock_move)
- [post_sale(...)](#post_sale)
- [reserve_stock(...)](#reserve_stock)
- [release_reservation(...)](#release_reservation)
- [replenish_to_sale_warehouse(...)](#replenish_to_sale_warehouse)
- [reverse_stock_move(...)](#reverse_stock_move)


## accounting/services.py

## post_sales_invoice(...)
- document_type
- date
- net
- vat
- description=""

## post_sales_cash(...)
- document_type
- date
- net
- vat
- cash_account
- description=""

## post_purchase_invoice_cash_from_items(...)
- document_type
- doc_date
- items
- cash_account
- deposit_account=None
- description=""

## post_purchase_invoice_cash_from_inputs(...)
- document_type
- doc_date
- inputs
- cash_account
- deposit_account=None
- description=""

## post_purchase_invoice_deferred_from_items(...)
- document_type
- doc_date
- items
- ap_account
- deposit_account=None
- description=""

## post_supplier_invoice_payment(...)
- invoice
- amount
- payment_account
- paid_date

## account_ledger(account, date_from, date_to)
- account
- date_from
- date_to

## trial_balance(date_from, date_to, only_postable=True, only_nonzero=True)
- date_from
- date_to
- only_postable
- only_nonzero


## stock/services.py

## post_warehouse_input_to_stock(...)
- warehouse_input
- warehouse (ako None, uzima default_purchase_warehouse)

## post_stock_out(...)
- warehouse
- items (lista dictova: `{"artikl": ..., "quantity": ...}`)
- move_date (optional)
- reference (optional)
- note (optional)
- reservation=None
- purpose (SALE/CONSUMPTION/WASTE/ADJUSTMENT)
- auto_cogs=True
- cogs_account=None
- inventory_account=None

## post_stock_transfer(...)
- from_warehouse
- to_warehouse
- items (lista dictova: `{"artikl": ..., "quantity": ...}`)
- move_date (optional)
- reference (optional)
- note (optional)

## post_cogs_for_stock_move(...)
- move (OUT)
- cogs_account
- inventory_account

## post_sale(...)
- warehouse (ako None, koristi se default_sale_warehouse)
- lines (lista dictova: `{"artikl": ..., "quantity": ...}`)
- date
- document_type
- cash_account
- net
- vat

## reserve_stock(...)
- warehouse
- artikl
- quantity
- source_type
- source_id

## release_reservation(...)
- reservation

## replenish_to_sale_warehouse(...)
- lines

## reverse_stock_move(...)
- move

[← Back to index](../index.md)