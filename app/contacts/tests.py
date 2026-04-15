from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from configuration.models import PaymentType
from contacts.models import Supplier


class SupplierListApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="supplier-api-admin",
            email="supplier-api-admin@example.com",
            password="pass",
        )
        self.client.force_authenticate(user=self.user)

    def test_supplier_list_exposes_default_payment_type(self):
        payment_type = PaymentType.objects.create(
            rm_id=10,
            name="Virman",
        )
        Supplier.objects.create(
            rm_id=1,
            name="Dobavljac 1",
            default_payment_type=payment_type,
        )
        Supplier.objects.create(
            rm_id=2,
            name="Dobavljac 2",
        )

        response = self.client.get("/api/suppliers/", secure=True)

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(
            response.json(),
            [
                {
                    "id": Supplier.objects.get(rm_id=1).id,
                    "rm_id": 1,
                    "name": "Dobavljac 1",
                    "default_payment_type": payment_type.id,
                },
                {
                    "id": Supplier.objects.get(rm_id=2).id,
                    "rm_id": 2,
                    "name": "Dobavljac 2",
                    "default_payment_type": None,
                },
            ],
        )
