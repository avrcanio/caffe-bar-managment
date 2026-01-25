# Migracije i testovi

> Modul: Tehnički
> Ovisi o: —
> Koriste ga: Razvoj, DevOps

## Sadržaj
- [Migracije](#migracije)
- [accounting](#accounting)
- [configuration](#configuration)
- [contacts](#contacts)
- [orders](#orders)
- [purchases](#purchases)
- [stock](#stock)
- [Testovi](#testovi)
- [accounting/tests](#accountingtests)
- [orders/tests](#orderstests)
- [stock/tests](#stocktests)


## Migracije

## accounting
- 0001_initial
- 0002_journalentry_reversed_entry
- 0003_ledger_company_profile

## configuration
- 0001_initial
- 0002_remariscookie
- 0003_companyprofile_orderemailtemplate
- 0004_taxgroup
- 0005_paymenttype
- 0006_paymenttype_rm_id
- 0007_documenttype
- 0008_documenttype_counterpart_account_code_and_more
- 0009_account_remove_documenttype_counterpart_account_code_and_more
- 0010_documenttype_accounting_fks
- 0011_documenttype_account_fallbacks
- 0012_documenttype_revenue_expense_fallbacks

## contacts
- 0001_initial
- 0002_stuff_delete_contact
- 0003_alter_stuff_options
- 0004_supplier
- 0005_supplier_orders_email

## orders
- 0001_initial
- 0002_order_email_sent_alter_order_ordered_at_and_more
- 0003_supplierprice
- 0004_supplierpricelist_supplierpriceitem_and_more
- 0005_supplierpricelist_currency_and_more
- 0006_orderitem_price
- 0007_order_total_gross_order_total_net
- 0008_order_payment_type
- 0009_warehouseinput_warehouseinputitem
- 0010_remove_warehouseinput_warehouse_id_and_more
- 0011_alter_warehouseinput_purchase_order
- 0012_rename_order_models
- 0013_alter_purchaseorder_payment_type_and_more
- 0014_purchaseorder_primka_created
- 0015_purchaseorder_status_and_confirmation
- 0016_purchaseorder_total_deposit_and_more
- 0016_supplierpriceitem_unique_artikl
- 0017_remove_purchaseorder_total_with_deposit_and_more
- 0018_merge_20260121_0653
- 0019_alter_warehouseinput_is_r_invoice
- 0020_alter_purchaseorder_ordered_at_and_more
- 0021_alter_purchaseorder_status
- 0022_warehouseinput_document_type_fk
- 0023_warehouseinput_journal_entry_and_more
- 0024_warehouseinput_stock_move

## purchases
- 0001_initial
- 0002_supplierinvoice_cash_account_and_more
- 0003_alter_supplierinvoice_options_and_more
- 0004_supplierinvoice_paid_amount_and_more

## stock
- 0001_initial
- 0002_warehousestock_artikl
- 0003_remove_warehousestock_artikl
- 0004_remove_warehousestock_product_name_and_more
- 0005_remove_warehousestock_artikl
- 0006_warehousestock_artikl
- 0007_remove_warehousestock_artikl_and_more
- 0008_remove_warehousestock_base_group_name
- 0009_productstockds
- 0010_warehouseid
- 0011_remove_warehousestock_base_group_order_and_more
- 0012_inventory_inventoryitem
- 0013_alter_inventory_created_by
- 0014_alter_inventoryitem_unit_alter_warehousestock_unit
- 0015_warehousetransfer_warehousetransferitem
- 0016_warehousetransfer_status
- 0017_warehousetransfer_note
- 0018_inventory_status
- 0019_alter_inventory_status_alter_inventoryitem_note
- 0020_stockmove_stocklot_stockmoveline_stockallocation
- 0021_stockmoveline_source_item
- 0022_stockmove_journal_entry
- 0023_stockmove_from_warehouse_stockmove_to_warehouse
- 0024_stockmove_reversed_move
- 0025_stockreservation
- 0026_stockmove_purpose
- 0027_stockaccountingconfig
- 0028_stockmove_sales_journal_entry
- 0029_stockaccountingconfig_default_purchase_warehouse_and_more
- 0030_stockaccountingconfig_auto_replenish_on_sale_and_more
- 0031_replenishrequestline
- 0032_stockaccountingconfig_default_cash_account_and_more

## Testovi

## accounting/tests
- test_account_ledger.py
- test_delete_posted.py
- test_journalentry_balance.py
- test_journalentry_locked.py
- test_journalitem_postable.py
- test_ledger_company_profile_sync.py
- test_post_purchase_invoice_cash.py
- test_post_purchase_invoice_cash_from_inputs.py
- test_post_sales_invoice.py
- test_reversal.py
- test_trial_balance.py
- test_void.py
- test_void_locking.py

## orders/tests
- test_admin_create_supplier_invoice_from_inputs.py
- test_admin_post_warehouse_input.py

## stock/tests
- test_post_cogs_for_stock_move.py
- test_post_sale.py
- test_post_sale_auto_replenish.py
- test_post_sale_missing_default_warehouse.py
- test_post_stock_out.py
- test_post_stock_out_auto_cogs.py
- test_post_stock_out_auto_cogs_config.py
- test_post_stock_out_reservations.py
- test_post_stock_transfer.py
- test_post_warehouse_input.py
- test_replenish_to_sale_warehouse.py
- test_reverse_stock_move.py
- test_stock_move_purpose.py
- test_stock_reservations.py

[← Back to index](../index.md)