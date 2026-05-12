from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from configuration.models import PaymentType
from contacts.models import Supplier
from orders.models import PurchaseOrder


class PurchaseOrderStatusTransitionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="po-status-admin",
            email="po-status-admin@example.com",
            password="pass",
        )
        self.client.force_authenticate(user=self.user)

        self.payment_type = PaymentType.objects.create(
            rm_id=3,
            name="Gotovina",
        )
        self.supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")

    def _create_order(self, *, status):
        return PurchaseOrder.objects.create(
            supplier=self.supplier,
            payment_type=self.payment_type,
            ordered_at=timezone.now(),
            status=status,
            created_by=self.user,
        )

    def test_created_order_can_transition_to_confirmed(self):
        order = self._create_order(status=PurchaseOrder.STATUS_CREATED)
        baseline = order.updated_at

        response = self.client.post(
            f"/api/purchase-orders/{order.id}/status/",
            {"status": PurchaseOrder.STATUS_CONFIRMED},
            format="json",
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.STATUS_CONFIRMED)
        self.assertIsNotNone(order.confirmed_at)
        self.assertGreater(order.updated_at, baseline)
        self.assertEqual(response.json()["status"], PurchaseOrder.STATUS_CONFIRMED)
        self.assertEqual(response.json()["status_display"], "Potvrđena")
        self.assertIn("updated_at", response.json())
        self.assertEqual(parse_datetime(response.json()["updated_at"]), order.updated_at)

    def test_purchase_order_detail_exposes_updated_at(self):
        order = self._create_order(status=PurchaseOrder.STATUS_CREATED)

        response = self.client.get(
            f"/api/purchase-orders/{order.id}/",
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertIn("updated_at", response.json())
        self.assertIsNotNone(response.json()["updated_at"])

    def test_sent_order_can_transition_to_confirmed(self):
        order = self._create_order(status=PurchaseOrder.STATUS_SENT)

        response = self.client.post(
            f"/api/purchase-orders/{order.id}/status/",
            {"status": PurchaseOrder.STATUS_CONFIRMED},
            format="json",
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.STATUS_CONFIRMED)
        self.assertIsNotNone(order.confirmed_at)

    def test_received_order_can_transition_to_received_all(self):
        order = self._create_order(status=PurchaseOrder.STATUS_RECEIVED)

        response = self.client.post(
            f"/api/purchase-orders/{order.id}/status/",
            {"status": PurchaseOrder.STATUS_RECEIVED_ALL},
            format="json",
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.STATUS_RECEIVED_ALL)
        self.assertEqual(response.json()["status_display"], "Sve stavke s narudžbe su zaprimljene")

    def test_invalid_transition_is_rejected(self):
        order = self._create_order(status=PurchaseOrder.STATUS_RECEIVED_ALL)

        response = self.client.post(
            f"/api/purchase-orders/{order.id}/status/",
            {"status": PurchaseOrder.STATUS_CONFIRMED},
            format="json",
            secure=True,
        )

        self.assertEqual(response.status_code, 400, response.json())
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.STATUS_RECEIVED_ALL)

    def test_unsupported_target_status_is_rejected(self):
        order = self._create_order(status=PurchaseOrder.STATUS_CREATED)

        response = self.client.post(
            f"/api/purchase-orders/{order.id}/status/",
            {"status": PurchaseOrder.STATUS_SENT},
            format="json",
            secure=True,
        )

        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("status", response.json())
