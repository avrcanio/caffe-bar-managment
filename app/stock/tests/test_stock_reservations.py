from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import WarehouseId
from stock.services import post_warehouse_input_to_stock, release_reservation, reserve_stock


class StockReservationTests(TestCase):
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
            quantity=Decimal("10.0000"),
            buying_price=Decimal("2.00"),
            total=Decimal("20.00"),
        )
        post_warehouse_input_to_stock(warehouse_input=input1)

    def test_reserve_release_flow(self):
        res = reserve_stock(
            warehouse=self.warehouse,
            artikl=self.artikl,
            quantity=Decimal("7.0000"),
            source_type="order",
            source_id=1,
        )
        with self.assertRaises(ValidationError):
            reserve_stock(
                warehouse=self.warehouse,
                artikl=self.artikl,
                quantity=Decimal("4.0000"),
            )

        release_reservation(reservation=res)
        reserve_stock(
            warehouse=self.warehouse,
            artikl=self.artikl,
            quantity=Decimal("4.0000"),
        )
