from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl, UnitOfMeasureData
from stock.models import Inventory, InventoryItem, WarehouseId
from stock.services import clone_inventory_without_counts


class CloneInventoryWithoutCountsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="x")
        self.wh = WarehouseId.objects.create(rm_id=4, name="Sank Gornji")
        self.unit = UnitOfMeasureData.objects.create(rm_id=1, name="Komad")
        self.art = Artikl.objects.create(rm_id=510, name="Test Artikl", code="ABC")

        self.source = Inventory.objects.create(
            warehouse=self.wh,
            date=timezone.now(),
            status=Inventory.Status.COUNTED,
            created_by=self.user,
        )
        InventoryItem.objects.create(
            inventory=self.source,
            artikl=self.art,
            unit=self.unit,
            quantity=Decimal("1.0000"),
            note="x",
        )
        # Duplicate artikl should be deduped.
        InventoryItem.objects.create(
            inventory=self.source,
            artikl=self.art,
            unit=self.unit,
            quantity=Decimal("2.0000"),
            note="y",
        )

    def test_clones_items_without_quantities(self):
        new_inv, created, skipped = clone_inventory_without_counts(
            source=self.source,
            created_by=self.user,
        )

        self.assertNotEqual(new_inv.id, self.source.id)
        self.assertEqual(new_inv.warehouse_id, self.source.warehouse_id)
        self.assertEqual(new_inv.status, Inventory.Status.OPEN)

        self.assertEqual(created, 1)
        self.assertGreaterEqual(skipped, 1)

        items = list(new_inv.items.all())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].artikl_id, self.art.rm_id)
        self.assertIsNone(items[0].quantity)
