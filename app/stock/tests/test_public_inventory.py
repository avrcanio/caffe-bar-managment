from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from artikli.models import Artikl
from stock.models import Inventory, InventoryItem, WarehouseId


class PublicInventoryApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.wh = WarehouseId.objects.create(rm_id=4, name="Sank Gornji")
        self.art1 = Artikl.objects.create(rm_id=504, name="Jamnica", code="3858884602387")
        self.art2 = Artikl.objects.create(rm_id=505, name="Cola", code="123")

        self.inv = Inventory.objects.create(warehouse=self.wh, date=timezone.now())
        self.i1 = InventoryItem.objects.create(inventory=self.inv, artikl=self.art1, quantity=None)
        self.i2 = InventoryItem.objects.create(inventory=self.inv, artikl=self.art2, quantity=None)
        self.token = self.inv.generate_public_token()

    def test_get_public_inventory_ok(self):
        r = self.client.get(f"/api/inventories/public/{self.token}/", secure=True)
        self.assertEqual(r.status_code, 200, r.json())
        data = r.json()
        self.assertEqual(data["id"], self.inv.id)
        self.assertEqual(data["warehouse_rm_id"], self.wh.rm_id)
        self.assertFalse(data["readonly"])
        self.assertEqual(len(data["items"]), 2)

        # quantities start as null
        by_id = {row["id"]: row for row in data["items"]}
        self.assertIsNone(by_id[self.i1.id]["quantity"])
        self.assertIsNone(by_id[self.i2.id]["quantity"])

    def test_submit_requires_all_items(self):
        r = self.client.post(
            f"/api/inventories/public/{self.token}/submit/",
            data={"items": [{"id": self.i1.id, "quantity": "1.0000"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(r.status_code, 400, r.json())

    def test_submit_locks_inventory(self):
        r = self.client.post(
            f"/api/inventories/public/{self.token}/submit/",
            data={
                "submitted_by_name": "Konobar 1",
                "items": [
                    {"id": self.i1.id, "quantity": "1.0000"},
                    {"id": self.i2.id, "quantity": "0"},
                ],
            },
            format="json",
            secure=True,
        )
        self.assertEqual(r.status_code, 200, r.json())

        self.inv.refresh_from_db()
        self.assertIsNotNone(self.inv.submitted_at)
        self.assertEqual(self.inv.submitted_by_name, "Konobar 1")

        self.i1.refresh_from_db()
        self.i2.refresh_from_db()
        self.assertEqual(str(self.i1.quantity), "1.0000")
        self.assertEqual(str(self.i2.quantity), "0.0000")

        r2 = self.client.post(
            f"/api/inventories/public/{self.token}/submit/",
            data={"items": [{"id": self.i1.id, "quantity": "2.0000"}, {"id": self.i2.id, "quantity": "1.0000"}]},
            format="json",
            secure=True,
        )
        self.assertEqual(r2.status_code, 409, r2.json())

        r3 = self.client.get(f"/api/inventories/public/{self.token}/", secure=True)
        self.assertEqual(r3.status_code, 200, r3.json())
        self.assertTrue(r3.json()["readonly"])

    def test_time_window(self):
        self.inv.opens_at = timezone.now() + timezone.timedelta(hours=1)
        self.inv.save(update_fields=["opens_at"])
        r = self.client.get(f"/api/inventories/public/{self.token}/", secure=True)
        self.assertEqual(r.status_code, 403, r.json())
