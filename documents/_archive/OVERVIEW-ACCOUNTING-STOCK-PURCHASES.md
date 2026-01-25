# Overview: Accounting + Stock + Purchases (current state)

This document summarizes the accounting core, stock/FIFO layer, and purchases flow that are implemented so far.

## Accounting core (app/accounting)

### Models
- Ledger (singleton in DB).
- Account (kontni plan) with type, normal_side, parent, is_postable.
- Period (lockable accounting periods).
- JournalEntry (DRAFT/POSTED/VOID) with strict rules.
- JournalItem (debit/credit lines, one-sided, postable-only account).

### Key rules (enforced in model logic)
- POSTED and VOID entries cannot change status/date after save.
- POSTED entries cannot exist in closed Periods.
- JournalItem save/delete blocked if entry is POSTED or VOID.
- Deleting POSTED entries/items is blocked.
- Reversal (storno) supported via JournalEntry.reverse().
- VOID supported for DRAFT only.

### Reports (services)
- account_ledger(account, date_from, date_to)
- trial_balance(date_from, date_to, only_postable=True, only_nonzero=True)

### Tests
- Locking POSTED/VOID.
- Non-postable account posting blocked.
- Delete protection.
- Reversal/VOID rules.
- Reports basic correctness.

## Stock/FIFO (app/stock)

### Models
- Warehouse
- StockLot (FIFO layers)
- StockMove (IN/OUT/TRANSFER)
- StockMoveLine
- StockAllocation (OUT -> lots)
- StockReservation
- StockAccountingConfig (singleton):
  - inventory_account, cogs_account
  - default_sale_warehouse
  - default_purchase_warehouse
  - default_replenish_from_warehouse
  - auto_replenish_on_sale
  - default_cash_account
  - default_deposit_account

### Services
- post_warehouse_input_to_stock(): IN move + lots from WarehouseInput
- post_stock_out(): FIFO allocations for OUT
- post_stock_transfer(): OUT from A + IN to B with same FIFO cost
- post_cogs_for_stock_move(): creates JournalEntry for COGS
- post_sale(): orchestrates OUT (SALE) + COGS + sales journal
- replenish_to_sale_warehouse(): manual replenish from config
- reserve_stock() / release_reservation(): reservation layer

### Rules
- FIFO allocation uses lots ordered by received_at.
- OUT cannot exceed available (on_hand - reserved).
- SALE can auto-post COGS using StockAccountingConfig.
- TRANSFER is value-neutral by default.

### Tests
- IN creates lots and move lines
- OUT creates allocations and respects FIFO
- TRANSFER keeps FIFO value
- COGS posting
- Reservations and availability
- SALE flow and audit links

## Purchases (app/purchases)

### SupplierInvoice model
- supplier, invoice_number, invoice_date
- inputs (M2M WarehouseInput)
- document_type, cash_account, deposit_account, ap_account
- totals: total_net, total_vat, total_gross, deposit_total
- payment_terms (CASH/DEFERRED)
- payment_status (UNPAID/PARTIAL/PAID)
- payment fields: paid_amount, paid_at, payment_account
- journal_entry (linked posting)

### Admin actions / UX
- Action on WarehouseInput: create SupplierInvoice from selected inputs.
  - Blocks if inputs already linked to invoices.
  - Auto-fills cash/deposit accounts from StockAccountingConfig if set.
  - Shows link to created invoice.
- SupplierInvoice list shows clickable "Primke: X".
- SupplierInvoice change form:
  - payment_terms toggles fields
  - partial payments handled on Save by increasing paid_amount
  - auto-creates payment JournalEntry for DEFERRED
  - status becomes PARTIAL or PAID

### Posting logic
- CASH: post_purchase_invoice_cash_from_inputs
- DEFERRED: post_purchase_invoice_deferred_from_items
- Payment: post_supplier_invoice_payment

## Frontend/Admin static
- Custom JS/CSS for SupplierInvoice admin (toggle fields, badges, help colors).
- Static files served in DEBUG via staticfiles_urlpatterns().

## Notes / Operational flow
1) Create WarehouseInput.
2) Post warehouse input to stock (FIFO lots).
3) Create SupplierInvoice from inputs in admin.
4) Post SupplierInvoice (CASH or DEFERRED).
5) For DEFERRED, use change form to record partial payments by updating paid_amount.

