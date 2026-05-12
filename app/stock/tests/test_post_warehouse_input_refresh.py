from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import WarehouseId, WarehouseStock
from stock.services import post_warehouse_input_to_stock


class PostWarehouseInputRefreshTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        self.order = PurchaseOrder.objects.create(
            supplier=self.supplier,
            ordered_at=timezone.now(),
        )
        self.warehouse = WarehouseId.objects.create(rm_id=7, name="Sank Donji")
        self.artikl = Artikl.objects.create(
            rm_id=1053,
            code="59481164",
            name="Dunhill Fine Cut Blonde",
            is_stock_item=True,
        )

    def test_post_creates_internal_warehouse_stock_row_immediately(self):
        warehouse_input = WarehouseInput.objects.create(
            order=self.order,
            supplier=self.supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse,
        )
        WarehouseInputItem.objects.create(
            warehouse_input=warehouse_input,
            artikl=self.artikl,
            quantity=Decimal("10.0000"),
            buying_price=Decimal("4.05"),
            total=Decimal("40.50"),
        )

        post_warehouse_input_to_stock(warehouse_input=warehouse_input)

        stock_row = WarehouseStock.objects.get(
            warehouse_id=self.warehouse,
            product=self.artikl,
        )
        self.assertIsNone(stock_row.wh_id)
        self.assertEqual(stock_row.quantity, Decimal("0.0000"))
        self.assertEqual(stock_row.internal_quantity, Decimal("10.0000"))
        self.assertEqual(stock_row.internal_avg_cost, Decimal("4.0500"))
