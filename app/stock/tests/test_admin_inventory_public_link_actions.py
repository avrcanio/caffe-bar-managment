from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.utils import timezone

from stock.admin import InventoryAdmin
from stock.models import Inventory, WarehouseId


class InventoryPublicLinkAdminActionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
        )
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.modeladmin = InventoryAdmin(Inventory, self.site)
        self.warehouse = WarehouseId.objects.create(rm_id=4, name="Sank Gornji")

    def _request(self):
        request = self.factory.post("/admin/stock/inventory/")
        request.user = self.user
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        setattr(request, "_messages", FallbackStorage(request))
        return request

    def test_generate_public_link_message_contains_public_inventory_url(self):
        inventory = Inventory.objects.create(
            warehouse=self.warehouse,
            date=timezone.now(),
            created_by=self.user,
        )
        request = self._request()

        with patch.object(
            Inventory,
            "generate_public_token",
            autospec=True,
            return_value="test-token-generate",
        ):
            self.modeladmin.generate_public_link(request, Inventory.objects.filter(pk=inventory.pk))

        messages = [message.message for message in get_messages(request)]
        self.assertEqual(len(messages), 1)
        self.assertIn('href="http://testserver/inventory/test-token-generate"', messages[0])
        self.assertIn('data-copy-public-link="http://testserver/inventory/test-token-generate"', messages[0])
        self.assertIn('class="inventory-public-link-copy"', messages[0])
        self.assertIn("<svg", messages[0])

    def test_reopen_for_correction_message_contains_public_inventory_url(self):
        inventory = Inventory.objects.create(
            warehouse=self.warehouse,
            date=timezone.now(),
            created_by=self.user,
            submitted_at=timezone.now(),
            submitted_by_name="Konobar",
            submitted_user_agent="Mozilla/5.0",
        )
        request = self._request()

        with patch.object(
            Inventory,
            "generate_public_token",
            autospec=True,
            return_value="test-token-reopen",
        ):
            self.modeladmin.reopen_for_correction(request, Inventory.objects.filter(pk=inventory.pk))

        inventory.refresh_from_db()
        self.assertIsNone(inventory.submitted_at)
        messages = [message.message for message in get_messages(request)]
        self.assertEqual(len(messages), 1)
        self.assertIn('href="http://testserver/inventory/test-token-reopen"', messages[0])
        self.assertIn('data-copy-public-link="http://testserver/inventory/test-token-reopen"', messages[0])
        self.assertIn('class="inventory-public-link-copy"', messages[0])
        self.assertIn("<svg", messages[0])
