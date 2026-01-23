from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class WarehouseStock(models.Model):
    wh_id = models.IntegerField(unique=True, null=True, blank=True)
    warehouse_id = models.ForeignKey(
        "stock.WarehouseId",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_rows",
    )
    product = models.ForeignKey(
        "artikli.Artikl",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="warehouse_stock_rows",
    )
    product_name = models.CharField(max_length=255, blank=True, default="")
    product_code = models.CharField(max_length=50, blank=True, default="")
    unit = models.CharField(max_length=100, blank=True, default="")
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    base_group_name = models.CharField(max_length=255, blank=True, default="")
    active = models.BooleanField(default=False)
    def __str__(self) -> str:
        name = self.product.name if self.product else self.product_name
        return f"{name} ({self.unit})"

    class Meta:
        verbose_name = "Stanje skladišta"
        verbose_name_plural = "Stanja skladišta"

class ProductStockDS(models.Model):
    rm_id = models.IntegerField(unique=True)
    product = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    unit_of_measure = models.CharField(max_length=100)
    input_value = models.DecimalField(max_digits=12, decimal_places=4)
    base_group_name = models.CharField(max_length=255)
    product_code = models.CharField(max_length=50)

    def __str__(self) -> str:
        return f"{self.product} ({self.product_code})"

    class Meta:
        verbose_name = "Stanje artikla"
        verbose_name_plural = "Stanja artikla"


class WarehouseId(models.Model):
    rm_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    hidden = models.BooleanField(default=False)
    ordinal = models.DecimalField(max_digits=20, decimal_places=12, null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.rm_id})"

    class Meta:
        verbose_name = "Skladiste"
        verbose_name_plural = "Skladista"


class Inventory(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Otvoreno"
        COUNTED = "counted", "Brojano"
        CLOSED = "closed", "Zatvoreno"

    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inventories",
    )
    date = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        verbose_name="Status",
    )
    created_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="inventories",
    )

    def update_status_from_items(self) -> None:
        if self.status == self.Status.CLOSED:
            return
        has_counted = (
            self.items.exclude(quantity__isnull=True).exclude(quantity=0).exists()
        )
        self.status = self.Status.COUNTED if has_counted else self.Status.OPEN
        self.save(update_fields=["status"])

    def __str__(self) -> str:
        warehouse_name = self.warehouse.name if self.warehouse else "Skladiste ?"
        return f"{warehouse_name} @ {self.date:%Y-%m-%d %H:%M}"

    class Meta:
        verbose_name = "Inventura"
        verbose_name_plural = "Inventure"


class InventoryItem(models.Model):
    inventory = models.ForeignKey(
        "stock.Inventory",
        on_delete=models.CASCADE,
        related_name="items",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inventory_items",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.ForeignKey(
        "artikli.UnitOfMeasureData",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inventory_item_units",
    )
    note = models.TextField(blank=True, default="", verbose_name="Napomena")

    def __str__(self) -> str:
        name = self.artikl.name if self.artikl else "Artikl ?"
        unit_name = self.unit.name if self.unit else "?"
        return f"{name} ({self.quantity} {unit_name})"

    def clean(self) -> None:
        if not self.artikl_id:
            raise ValidationError({"artikl": "Artikl je obavezan."})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.inventory_id:
            self.inventory.update_status_from_items()

    def delete(self, *args, **kwargs):
        inventory = self.inventory
        super().delete(*args, **kwargs)
        if inventory:
            inventory.update_status_from_items()

    class Meta:
        verbose_name = "Stavka inventure"
        verbose_name_plural = "Stavke inventure"


class WarehouseTransfer(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    from_warehouse = models.ForeignKey(
        "stock.WarehouseId",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="outgoing_transfers",
    )
    to_warehouse = models.ForeignKey(
        "stock.WarehouseId",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="incoming_transfers",
    )
    date = models.DateTimeField()
    dont_change_inventory_quantity = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="warehouse_transfers",
    )
    remaris_id = models.IntegerField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")

    def clean(self) -> None:
        if (
            self.from_warehouse_id
            and self.to_warehouse_id
            and self.from_warehouse_id == self.to_warehouse_id
        ):
            raise ValidationError({"to_warehouse": "Skladišta moraju biti različita."})

    def __str__(self) -> str:
        from_name = self.from_warehouse.name if self.from_warehouse else "?"
        to_name = self.to_warehouse.name if self.to_warehouse else "?"
        return f"{from_name} -> {to_name} @ {self.date:%Y-%m-%d %H:%M}"

    class Meta:
        verbose_name = "Međuskladišnica"
        verbose_name_plural = "Međuskladišnice"


class WarehouseTransferItem(models.Model):
    transfer = models.ForeignKey(
        "stock.WarehouseTransfer",
        on_delete=models.CASCADE,
        related_name="items",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="warehouse_transfer_items",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.ForeignKey(
        "artikli.UnitOfMeasureData",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="warehouse_transfer_item_units",
    )

    def __str__(self) -> str:
        name = self.artikl.name if self.artikl else "Artikl ?"
        unit_name = self.unit.name if self.unit else "?"
        return f"{name} ({self.quantity} {unit_name})"

    class Meta:
        verbose_name = "Stavka međuskladišnice"
        verbose_name_plural = "Stavke međuskladišnice"


class StockLot(models.Model):
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_lots",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_lots",
    )
    received_at = models.DateTimeField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4)
    qty_in = models.DecimalField(max_digits=12, decimal_places=4, validators=[MinValueValidator(0)])
    qty_remaining = models.DecimalField(max_digits=12, decimal_places=4, validators=[MinValueValidator(0)])
    source_item = models.ForeignKey(
        "orders.WarehouseInputItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_lots",
    )

    def __str__(self) -> str:
        name = self.artikl.name if self.artikl else "Artikl ?"
        warehouse_name = self.warehouse.name if self.warehouse else "Skladiste ?"
        return f"{name} @ {warehouse_name} ({self.qty_remaining}/{self.qty_in})"

    class Meta:
        verbose_name = "FIFO sloj"
        verbose_name_plural = "FIFO slojevi"


class StockMove(models.Model):
    class MoveType(models.TextChoices):
        IN = "in", "Ulaz"
        OUT = "out", "Izlaz"
        TRANSFER = "transfer", "Transfer"
        ADJUST = "adjust", "Ispravak"

    move_type = models.CharField(max_length=20, choices=MoveType.choices)
    date = models.DateTimeField()
    reference = models.CharField(max_length=200, blank=True, default="")
    note = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return f"{self.move_type} @ {self.date:%Y-%m-%d %H:%M}"

    class Meta:
        verbose_name = "Skladisno kretanje"
        verbose_name_plural = "Skladisna kretanja"


class StockMoveLine(models.Model):
    move = models.ForeignKey(
        "stock.StockMove",
        on_delete=models.CASCADE,
        related_name="lines",
    )
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_move_lines",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_move_lines",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=4, validators=[MinValueValidator(0)])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    source_item = models.ForeignKey(
        "orders.WarehouseInputItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stock_move_lines",
    )

    def __str__(self) -> str:
        name = self.artikl.name if self.artikl else "Artikl ?"
        return f"{name} ({self.quantity})"

    class Meta:
        verbose_name = "Stavka kretanja"
        verbose_name_plural = "Stavke kretanja"


class StockAllocation(models.Model):
    move_line = models.ForeignKey(
        "stock.StockMoveLine",
        on_delete=models.CASCADE,
        related_name="allocations",
    )
    lot = models.ForeignKey(
        "stock.StockLot",
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    qty = models.DecimalField(max_digits=12, decimal_places=4, validators=[MinValueValidator(0)])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4)

    def __str__(self) -> str:
        return f"{self.lot} -> {self.qty}"

    class Meta:
        verbose_name = "FIFO alokacija"
        verbose_name_plural = "FIFO alokacije"
