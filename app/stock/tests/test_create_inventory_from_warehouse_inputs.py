from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl, UnitOfMeasureData
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import Inventory, WarehouseId
from stock.services import create_inventory_from_warehouse_inputs


class CreateInventoryFromWarehouseInputsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="x")

        self.supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        self.order = PurchaseOrder.objects.create(supplier=self.supplier, ordered_at=timezone.now())

        self.wh1 = WarehouseId.objects.create(rm_id=1, name="Skladiste 1")
        self.wh2 = WarehouseId.objects.create(rm_id=2, name="Skladiste 2")

        self.unit = UnitOfMeasureData.objects.create(rm_id=1, name="Komad")
        self.art1 = Artikl.objects.create(rm_id=10, name="Artikl 1", code="A1")
        self.art2 = Artikl.objects.create(rm_id=20, name="Artikl 2", code="A2")

        self.wi1 = WarehouseInput.objects.create(
            order=self.order,
            supplier=self.supplier,
            date=timezone.localdate(),
            warehouse=self.wh1,
            invoice_code="INV-1",
        )
        self.wi2 = WarehouseInput.objects.create(
            order=self.order,
            supplier=self.supplier,
            date=timezone.localdate(),
            warehouse=self.wh1,
            invoice_code="INV-2",
        )

        # wi1 has art1
        WarehouseInputItem.objects.create(
            warehouse_input=self.wi1,
            artikl=self.art1,
            unit_of_measure=self.unit,
            quantity=Decimal("1.0000"),
            buying_price=Decimal("1.00"),
            total=Decimal("1.00"),
        )
        # wi2 has art1 again + art2
        WarehouseInputItem.objects.create(
            warehouse_input=self.wi2,
            artikl=self.art1,
            unit_of_measure=self.unit,
            quantity=Decimal("2.0000"),
            buying_price=Decimal("1.00"),
            total=Decimal("2.00"),
        )
        WarehouseInputItem.objects.create(
            warehouse_input=self.wi2,
            artikl=self.art2,
            unit_of_measure=self.unit,
            quantity=Decimal("3.0000"),
            buying_price=Decimal("1.00"),
            total=Decimal("3.00"),
        )

    def test_creates_inventory_and_dedupes_artikli(self):
        inv, created, skipped = create_inventory_from_warehouse_inputs(
            inputs=[self.wi1, self.wi2],
            name="vina škaulj",
            created_by=self.user,
            note="Primke: 222,223",
        )

        self.assertIsNotNone(inv.id)
        self.assertEqual(inv.name, "vina škaulj")
        self.assertEqual(inv.note, "Primke: 222,223")
        self.assertEqual(inv.warehouse_id, self.wh1.rm_id)
        self.assertEqual(inv.status, Inventory.Status.OPEN)

        items = list(inv.items.order_by("artikl_id"))
        self.assertEqual(len(items), 2)
        self.assertEqual({it.artikl_id for it in items}, {self.art1.rm_id, self.art2.rm_id})
        self.assertTrue(all(it.quantity is None for it in items))

        self.assertEqual(created, 2)
        self.assertGreaterEqual(skipped, 1)  # duplicate art1 is skipped

    def test_requires_same_warehouse(self):
        wi_other = WarehouseInput.objects.create(
            order=self.order,
            supplier=self.supplier,
            date=timezone.localdate(),
            warehouse=self.wh2,
            invoice_code="INV-3",
        )
        WarehouseInputItem.objects.create(
            warehouse_input=wi_other,
            artikl=self.art2,
            unit_of_measure=self.unit,
            quantity=Decimal("1.0000"),
            buying_price=Decimal("1.00"),
            total=Decimal("1.00"),
        )

        with self.assertRaises(ValidationError):
            create_inventory_from_warehouse_inputs(
                inputs=[self.wi1, wi_other],
                name="vina škaulj",
                created_by=self.user,
            )

