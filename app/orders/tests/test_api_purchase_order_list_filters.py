from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from configuration.models import PaymentType
from contacts.models import Supplier
from orders.models import PurchaseOrder


class PurchaseOrderListFilterApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="po-filter-admin",
            email="po-filter-admin@example.com",
            password="pass",
        )
        self.client.force_authenticate(user=self.user)

        self.payment_type = PaymentType.objects.create(
            rm_id=3,
            name="Gotovina",
        )
        self.supplier_one = Supplier.objects.create(rm_id=1, name="Dobavljac 1")
        self.supplier_two = Supplier.objects.create(rm_id=2, name="Dobavljac 2")

    def _create_order(self, *, supplier, status, ordered_at):
        return PurchaseOrder.objects.create(
            supplier=supplier,
            payment_type=self.payment_type,
            ordered_at=ordered_at,
            status=status,
            created_by=self.user,
        )

    def test_purchase_order_list_keeps_single_status_filter_behavior(self):
        created = self._create_order(
            supplier=self.supplier_one,
            status=PurchaseOrder.STATUS_CREATED,
            ordered_at=timezone.now(),
        )
        self._create_order(
            supplier=self.supplier_one,
            status=PurchaseOrder.STATUS_SENT,
            ordered_at=timezone.now() - timedelta(minutes=5),
        )

        response = self.client.get("/api/purchase-orders/?status=created", secure=True)

        self.assertEqual(response.status_code, 200, response.json())
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual([item["id"] for item in body["results"]], [created.id])

    def test_purchase_order_list_supports_repeated_status_query_params(self):
        now = timezone.now()
        sent = self._create_order(
            supplier=self.supplier_one,
            status=PurchaseOrder.STATUS_SENT,
            ordered_at=now,
        )
        created = self._create_order(
            supplier=self.supplier_one,
            status=PurchaseOrder.STATUS_CREATED,
            ordered_at=now - timedelta(minutes=5),
        )
        self._create_order(
            supplier=self.supplier_one,
            status=PurchaseOrder.STATUS_CONFIRMED,
            ordered_at=now - timedelta(minutes=10),
        )

        response = self.client.get(
            "/api/purchase-orders/?status=created&status=sent",
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(
            [item["id"] for item in body["results"]],
            [sent.id, created.id],
        )
        self.assertEqual(
            set(body["summary"]["status_counts"].keys()),
            {PurchaseOrder.STATUS_CREATED, PurchaseOrder.STATUS_SENT},
        )

    def test_purchase_order_list_supports_comma_separated_status_filter(self):
        now = timezone.now()
        created = self._create_order(
            supplier=self.supplier_one,
            status=PurchaseOrder.STATUS_CREATED,
            ordered_at=now,
        )
        sent = self._create_order(
            supplier=self.supplier_one,
            status=PurchaseOrder.STATUS_SENT,
            ordered_at=now - timedelta(minutes=5),
        )

        response = self.client.get(
            "/api/purchase-orders/?status=created,sent",
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(
            {item["id"] for item in response.json()["results"]},
            {created.id, sent.id},
        )

    def test_multi_status_filter_works_with_supplier_dates_and_pagination(self):
        now = timezone.now()
        newest = self._create_order(
            supplier=self.supplier_one,
            status=PurchaseOrder.STATUS_SENT,
            ordered_at=now,
        )
        second = self._create_order(
            supplier=self.supplier_one,
            status=PurchaseOrder.STATUS_CREATED,
            ordered_at=now - timedelta(days=1),
        )
        self._create_order(
            supplier=self.supplier_one,
            status=PurchaseOrder.STATUS_CREATED,
            ordered_at=now - timedelta(days=10),
        )
        self._create_order(
            supplier=self.supplier_two,
            status=PurchaseOrder.STATUS_SENT,
            ordered_at=now - timedelta(hours=2),
        )

        response = self.client.get(
            (
                "/api/purchase-orders/"
                "?status=created&status=sent"
                f"&supplier={self.supplier_one.id}"
                f"&ordered_from={(now - timedelta(days=2)).date().isoformat()}"
                "&page_size=1"
            ),
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["id"], newest.id)
        self.assertIsNotNone(body["next"])

        second_page = self.client.get(body["next"], secure=True)
        self.assertEqual(second_page.status_code, 200, second_page.json())
        self.assertEqual(second_page.json()["results"][0]["id"], second.id)
