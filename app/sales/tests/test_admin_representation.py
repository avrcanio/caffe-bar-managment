from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from sales.models import Representation, RepresentationReason
from stock.models import WarehouseId


class RepresentationAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.warehouse = WarehouseId.objects.create(rm_id=4, name="Sank Gornji")
        self.reason = RepresentationReason.objects.create(code="guests-admin", name="Gosti")

    def test_add_page_loads(self):
        response = self.client.get(reverse("admin:sales_representation_add"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="warehouse"')
        self.assertContains(response, 'name="reason"')

    def test_add_sets_current_user(self):
        response = self.client.post(
            reverse("admin:sales_representation_add"),
            {
                "warehouse": self.warehouse.rm_id,
                "reason": self.reason.id,
                "note": "Test reprezentacija",
                "items-TOTAL_FORMS": "0",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
                "_save": "Save",
            },
            follow=True,
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        rep = Representation.objects.get()
        self.assertEqual(rep.user_id, self.user.id)
        self.assertEqual(rep.warehouse_id, self.warehouse.rm_id)
        self.assertEqual(rep.reason_id, self.reason.id)
