from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import StockLot, StockMoveLine, WarehouseId
from stock.services import post_warehouse_input_to_stock


class PostWarehouseInputToStockTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        self.order = PurchaseOrder.objects.create(
            supplier=self.supplier,
            ordered_at=timezone.now(),
        )
        self.warehouse = WarehouseId.objects.create(rm_id=1, name="Skladiste 1")
        self.artikl = Artikl.objects.create(rm_id=10, name="Kava")

        self.input = WarehouseInput.objects.create(
            order=self.order,
            supplier=self.supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse,
        )
        self.item = WarehouseInputItem.objects.create(
            warehouse_input=self.input,
            artikl=self.artikl,
            quantity=Decimal("5.0000"),
            buying_price=Decimal("2.50"),
            total=Decimal("12.50"),
        )

    def test_creates_move_lines_and_lots(self):
        move = post_warehouse_input_to_stock(warehouse_input=self.input)

        self.input.refresh_from_db()
        self.assertEqual(self.input.stock_move_id, move.id)
        self.assertEqual(StockMoveLine.objects.filter(move=move).count(), 1)
        self.assertEqual(StockLot.objects.filter(artikl=self.artikl, warehouse=self.warehouse).count(), 1)

        lot = StockLot.objects.get(artikl=self.artikl, warehouse=self.warehouse)
        self.assertEqual(lot.qty_in, Decimal("5.0000"))
        self.assertEqual(lot.qty_remaining, Decimal("5.0000"))

    def test_cannot_post_same_input_twice(self):
        post_warehouse_input_to_stock(warehouse_input=self.input)
        with self.assertRaises(ValidationError):
            post_warehouse_input_to_stock(warehouse_input=self.input)
