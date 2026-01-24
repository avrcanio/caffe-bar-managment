from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import StockLot, WarehouseId
from stock.services import post_warehouse_input_to_stock, reverse_stock_move


class ReverseStockMoveTests(TestCase):
    def setUp(self):
        supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        order = PurchaseOrder.objects.create(supplier=supplier, ordered_at=timezone.now())
        self.warehouse = WarehouseId.objects.create(rm_id=1, name="Skladiste A")
        self.artikl = Artikl.objects.create(rm_id=10, name="Kava")

        input1 = WarehouseInput.objects.create(
            order=order,
            supplier=supplier,
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
        self.move_in = post_warehouse_input_to_stock(warehouse_input=input1)

    def test_reverse_in_creates_out_and_zeroes_stock(self):
        reversal = reverse_stock_move(move=self.move_in)

        lot = StockLot.objects.get(warehouse=self.warehouse, artikl=self.artikl)
        self.assertEqual(lot.qty_remaining, Decimal("0.0000"))
        self.assertEqual(reversal.move_type, "out")
