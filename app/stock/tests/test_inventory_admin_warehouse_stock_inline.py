from decimal import Decimal

from django.contrib import admin
from django.test import SimpleTestCase
from django.utils import timezone

from artikli.models import Artikl
from stock.admin import (
    InventoryItemInline,
    _format_warehouse_stock_rows,
    _inventory_item_should_show_warehouse_stock,
)
from stock.models import Inventory, InventoryItem, WarehouseId, WarehouseStock


class InventoryWarehouseStockInlineHelpersTests(SimpleTestCase):
    def setUp(self):
        self.wh_a = WarehouseId(rm_id=101, name="Skladište A")
        self.wh_b = WarehouseId(rm_id=102, name="Skladište B")
        self.artikl = Artikl(rm_id=9001, name="Test artikl")

    def test_should_show_open_without_quantity_false(self):
        inv = Inventory(
            warehouse=self.wh_a,
            date=timezone.now(),
            status=Inventory.Status.OPEN,
        )
        item = InventoryItem(inventory=inv, artikl=self.artikl, quantity=None)
        self.assertFalse(_inventory_item_should_show_warehouse_stock(item))

    def test_should_show_open_with_quantity_true(self):
        inv = Inventory(
            warehouse=self.wh_a,
            date=timezone.now(),
            status=Inventory.Status.OPEN,
        )
        item = InventoryItem(
            inventory=inv,
            artikl=self.artikl,
            quantity=Decimal("1.0000"),
        )
        self.assertTrue(_inventory_item_should_show_warehouse_stock(item))

    def test_should_show_counted_even_if_line_quantity_null(self):
        inv = Inventory(
            warehouse=self.wh_a,
            date=timezone.now(),
            status=Inventory.Status.COUNTED,
        )
        item = InventoryItem(inventory=inv, artikl=self.artikl, quantity=None)
        self.assertTrue(_inventory_item_should_show_warehouse_stock(item))

    def test_format_rows_empty(self):
        self.assertEqual(_format_warehouse_stock_rows([]), "Nema zapisa")

    def test_format_rows_two_warehouses(self):
        rows = [
            WarehouseStock(
                warehouse_id=self.wh_a,
                product=self.artikl,
                quantity=Decimal("10.0000"),
                internal_quantity=Decimal("9.5000"),
                unit="kom",
                product_name=self.artikl.name,
                product_code="C1",
                base_group_name="",
                active=True,
            ),
            WarehouseStock(
                warehouse_id=self.wh_b,
                product=self.artikl,
                quantity=Decimal("2.0000"),
                internal_quantity=None,
                unit="kom",
                product_name=self.artikl.name,
                product_code="C1",
                base_group_name="",
                active=True,
            ),
        ]
        text = str(_format_warehouse_stock_rows(rows))
        self.assertIn("<br>", text)
        self.assertIn("Skladište A", text)
        self.assertIn("Skladište B", text)
        self.assertIn("10.0000", text)
        self.assertIn("2.0000", text)
        self.assertIn("int 9.5000", text)
        self.assertIn("int —", text)

    def test_inline_summary_uses_prefetched_stock_map(self):
        inv = Inventory(
            warehouse=self.wh_a,
            date=timezone.now(),
            status=Inventory.Status.COUNTED,
        )
        item = InventoryItem(
            inventory=inv,
            artikl=self.artikl,
            quantity=Decimal("5.0000"),
        )
        rows = [
            WarehouseStock(
                warehouse_id=self.wh_a,
                product=self.artikl,
                quantity=Decimal("1.0000"),
                internal_quantity=Decimal("1.0000"),
                unit="kom",
                product_name=self.artikl.name,
                product_code="X",
                base_group_name="",
                active=True,
            ),
            WarehouseStock(
                warehouse_id=self.wh_b,
                product=self.artikl,
                quantity=Decimal("3.0000"),
                internal_quantity=None,
                unit="kom",
                product_name=self.artikl.name,
                product_code="X",
                base_group_name="",
                active=True,
            ),
        ]
        inline = InventoryItemInline(Inventory, admin.site)
        inline._warehouse_stock_by_artikl = {self.artikl.rm_id: rows}
        html = inline.warehouse_stock_summary(item)
        self.assertIn("Skladište A", str(html))
        self.assertIn("Skladište B", str(html))
