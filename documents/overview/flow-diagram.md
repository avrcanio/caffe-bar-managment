# Dijagram toka

```mermaid
flowchart TD
    A[Primka / WarehouseInput] --> B[Admin action: Proknjizi primku u skladiste]
    B --> C[StockMove IN]
    B --> D[StockMoveLine]
    B --> E[StockLot (FIFO sloj)]

    A --> F[Admin action: Kreiraj SupplierInvoice iz primki]
    F --> G[SupplierInvoice]

    G --> H{Payment terms}
    H -->|CASH| I[Post purchase invoice: CASH]
    H -->|DEFERRED| J[Post purchase invoice: DEFERRED]

    I --> K[JournalEntry: trosak + PDV + depozit + blagajna]
    J --> L[JournalEntry: trosak + PDV + depozit + AP]

    J --> M[Change page: povecaj paid_amount]
    M --> N[JournalEntry: placanje (D AP / P cash)]
    M --> O[Status: PARTIAL/PAID]

    P[Prodaja (lines)] --> Q[post_sale]
    Q --> R[StockMove OUT (SALE)]
    R --> S[StockAllocation (FIFO)]
    R --> T[COGS JournalEntry]
    Q --> U[Sales JournalEntry (prihod + PDV + blagajna)]

    V[Transfer] --> W[post_stock_transfer]
    W --> X[OUT iz A + IN u B (FIFO vrijednost)]
```

[← Back to index](../index.md)