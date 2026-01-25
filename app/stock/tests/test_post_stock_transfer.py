from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import StockAllocation, StockLot, WarehouseId
from stock.services import post_stock_transfer, post_warehouse_input_to_stock


class PostStockTransferTests(TestCase):
    def setUp(self):
        supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        order = PurchaseOrder.objects.create(supplier=supplier, ordered_at=timezone.now())
        self.warehouse_a = WarehouseId.objects.create(rm_id=1, name="Skladiste A")
        self.warehouse_b = WarehouseId.objects.create(rm_id=2, name="Skladiste B")
        self.artikl = Artikl.objects.create(rm_id=10, name="Kava")

        input1 = WarehouseInput.objects.create(
            order=order,
            supplier=supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse_a,
        )
        WarehouseInputItem.objects.create(
            warehouse_input=input1,
            artikl=self.artikl,
            quantity=Decimal("10.0000"),
            buying_price=Decimal("2.00"),
            total=Decimal("20.00"),
        )
        post_warehouse_input_to_stock(warehouse_input=input1)

    def test_transfer_creates_lots_and_allocations(self):
        move = post_stock_transfer(
            from_warehouse=self.warehouse_a,
            to_warehouse=self.warehouse_b,
            items=[{"artikl": self.artikl, "quantity": Decimal("6.0000")}],
            reference="Transfer A->B",
        )

        lot_a = StockLot.objects.get(warehouse=self.warehouse_a, artikl=self.artikl)
        self.assertEqual(lot_a.qty_remaining, Decimal("4.0000"))

        lots_b = StockLot.objects.filter(warehouse=self.warehouse_b, artikl=self.artikl)
        self.assertEqual(lots_b.count(), 1)
        self.assertEqual(lots_b.first().qty_remaining, Decimal("6.0000"))
        self.assertEqual(lots_b.first().unit_cost, Decimal("2.00"))

        allocations = StockAllocation.objects.filter(move_line__move=move)
        self.assertEqual(allocations.count(), 1)
        self.assertEqual(allocations.first().qty, Decimal("6.0000"))
