from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import StockAllocation, StockLot, WarehouseId
from stock.services import post_stock_out, post_warehouse_input_to_stock


class PostStockOutTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        self.order = PurchaseOrder.objects.create(
            supplier=self.supplier,
            ordered_at=timezone.now(),
        )
        self.warehouse = WarehouseId.objects.create(rm_id=1, name="Skladiste 1")
        self.artikl = Artikl.objects.create(rm_id=10, name="Kava")

        input1 = WarehouseInput.objects.create(
            order=self.order,
            supplier=self.supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse,
        )
        WarehouseInputItem.objects.create(
            warehouse_input=input1,
            artikl=self.artikl,
            quantity=Decimal("5.0000"),
            buying_price=Decimal("2.00"),
            total=Decimal("10.00"),
        )
        post_warehouse_input_to_stock(warehouse_input=input1)

        input2 = WarehouseInput.objects.create(
            order=self.order,
            supplier=self.supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse,
        )
        WarehouseInputItem.objects.create(
            warehouse_input=input2,
            artikl=self.artikl,
            quantity=Decimal("3.0000"),
            buying_price=Decimal("3.00"),
            total=Decimal("9.00"),
        )
        post_warehouse_input_to_stock(warehouse_input=input2)

    def test_fifo_allocation_and_avg_cost(self):
        move = post_stock_out(
            warehouse=self.warehouse,
            items=[{"artikl": self.artikl, "quantity": Decimal("6.0000")}],
            reference="Test izlaz",
        )

        lots = list(StockLot.objects.filter(warehouse=self.warehouse, artikl=self.artikl).order_by("received_at", "id"))
        self.assertEqual(lots[0].qty_remaining, Decimal("0.0000"))
        self.assertEqual(lots[1].qty_remaining, Decimal("2.0000"))

        allocations = StockAllocation.objects.filter(move_line__move=move).order_by("id")
        self.assertEqual(allocations.count(), 2)
        self.assertEqual(allocations[0].qty, Decimal("5.0000"))
        self.assertEqual(allocations[1].qty, Decimal("1.0000"))

        move_line = move.lines.get()
        self.assertEqual(move_line.unit_cost, Decimal("2.1667"))

    def test_insufficient_stock_raises(self):
        with self.assertRaises(ValidationError):
            post_stock_out(
                warehouse=self.warehouse,
                items=[{"artikl": self.artikl, "quantity": Decimal("20.0000")}],
            )
