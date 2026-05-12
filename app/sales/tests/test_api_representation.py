from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from artikli.models import Artikl
from configuration.models import TaxGroup
from sales.models import Representation, RepresentationReason
from stock.models import WarehouseId


class RepresentationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(username="rep-user", password="pass1234")
        self.warehouse = WarehouseId.objects.create(rm_id=904, name="Sank")
        self.reason = RepresentationReason.objects.create(code="rep-api-guests", name="Gosti")
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25-REPAPI", rate="0.2500")
        self.artikl = Artikl.objects.create(
            rm_id=91272,
            name="Kava",
            code="KAV-REP",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )

    def test_create_accepts_windows_cash_register_warehouse_id_payload(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/representations/",
            data={
                "warehouse_id": self.warehouse.rm_id,
                "reason_id": self.reason.id,
                "note": "test",
                "items": [
                    {
                        "artikl": self.artikl.rm_id,
                        "quantity": "1.0000",
                        "price": "0.00",
                    }
                ],
            },
            format="json",
            secure=True,
        )

        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.assertEqual(payload["warehouse"], self.warehouse.rm_id)
        self.assertEqual(payload["warehouse_id"], self.warehouse.rm_id)
        self.assertEqual(payload["reason_id"], self.reason.id)
        self.assertEqual(payload["items"][0]["artikl"], self.artikl.rm_id)
        self.assertEqual(Representation.objects.count(), 1)
        self.assertEqual(Representation.objects.get().user, self.user)
