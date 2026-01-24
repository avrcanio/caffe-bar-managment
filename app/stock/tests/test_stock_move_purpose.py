from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import WarehouseId
from stock.services import post_stock_out, post_warehouse_input_to_stock


class StockMovePurposeTests(TestCase):
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
        post_warehouse_input_to_stock(warehouse_input=input1)

    def test_out_sets_purpose(self):
        move = post_stock_out(
            warehouse=self.warehouse,
            items=[{"artikl": self.artikl, "quantity": Decimal("2.0000")}],
            purpose="sale",
            auto_cogs=False,
        )
        self.assertEqual(move.purpose, "sale")
