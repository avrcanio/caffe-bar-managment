from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from configuration.models import PaymentType
from contacts.models import Supplier
from orders.models import PurchaseOrder


class PurchaseOrderPaymentTypeDefaultApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="po-payment-default-admin",
            email="po-payment-default-admin@example.com",
            password="pass",
        )
        self.client.force_authenticate(user=self.user)

        self.default_payment_type = PaymentType.objects.create(
            rm_id=11,
            name="Virman",
        )
        self.manual_payment_type = PaymentType.objects.create(
            rm_id=12,
            name="Kartica",
        )
        self.supplier_with_default = Supplier.objects.create(
            rm_id=1,
            name="Dobavljac s defaultom",
            default_payment_type=self.default_payment_type,
        )
        self.supplier_without_default = Supplier.objects.create(
            rm_id=2,
            name="Dobavljac bez defaulta",
        )

    def test_create_uses_supplier_default_payment_type_when_missing(self):
        response = self.client.post(
            "/api/purchase-orders/",
            {
                "supplier": self.supplier_with_default.id,
            },
            format="json",
            secure=True,
        )

        self.assertEqual(response.status_code, 201, response.json())
        order = PurchaseOrder.objects.get(id=response.json()["id"])
        self.assertEqual(order.payment_type_id, self.default_payment_type.id)

    def test_create_keeps_payment_type_null_without_supplier_default(self):
        response = self.client.post(
            "/api/purchase-orders/",
            {
                "supplier": self.supplier_without_default.id,
            },
            format="json",
            secure=True,
        )

        self.assertEqual(response.status_code, 201, response.json())
        order = PurchaseOrder.objects.get(id=response.json()["id"])
        self.assertIsNone(order.payment_type_id)

    def test_update_uses_supplier_default_payment_type_when_missing(self):
        order = PurchaseOrder.objects.create(
            supplier=self.supplier_with_default,
            payment_type=self.manual_payment_type,
            ordered_at=timezone.now(),
            created_by=self.user,
        )

        response = self.client.put(
            f"/api/purchase-orders/{order.id}/",
            {
                "supplier": self.supplier_with_default.id,
            },
            format="json",
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        order.refresh_from_db()
        self.assertEqual(order.payment_type_id, self.default_payment_type.id)

    def test_update_uses_supplier_default_payment_type_when_null(self):
        order = PurchaseOrder.objects.create(
            supplier=self.supplier_with_default,
            payment_type=self.manual_payment_type,
            ordered_at=timezone.now(),
            created_by=self.user,
        )

        response = self.client.put(
            f"/api/purchase-orders/{order.id}/",
            {
                "supplier": self.supplier_with_default.id,
                "payment_type": None,
            },
            format="json",
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        order.refresh_from_db()
        self.assertEqual(order.payment_type_id, self.default_payment_type.id)

    def test_update_keeps_explicit_payment_type(self):
        order = PurchaseOrder.objects.create(
            supplier=self.supplier_with_default,
            payment_type=self.default_payment_type,
            ordered_at=timezone.now(),
            created_by=self.user,
        )

        response = self.client.put(
            f"/api/purchase-orders/{order.id}/",
            {
                "supplier": self.supplier_with_default.id,
                "payment_type": self.manual_payment_type.id,
            },
            format="json",
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        order.refresh_from_db()
        self.assertEqual(order.payment_type_id, self.manual_payment_type.id)
