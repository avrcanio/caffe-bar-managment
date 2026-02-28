from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from pos.models import Pos, PosDevice, PosPrinterInventory, PosProfile
from stock.models import WarehouseId


class PosPinLoginApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="pin-user",
            email="pin@example.com",
            password="pass1234",
        )
        self.profile = PosProfile.objects.create(user=self.user)
        self.profile.set_pin("1234")
        self.profile.save(update_fields=["pin_hash"])

    def test_requires_pin(self):
        response = self.client.post("/api/pos/pin/login/", data={}, format="json", secure=True)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["detail"], "PIN je obavezan.")

    def test_login_with_pin_returns_token_payload(self):
        response = self.client.post(
            "/api/pos/pin/login/",
            data={"pin": "1234"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertIn("token", payload)
        self.assertEqual(payload["user_id"], self.user.id)
        self.assertEqual(payload["username"], self.user.username)

    def test_login_does_not_require_csrf_even_with_session_cookie(self):
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(
            "/api/pos/pin/login/",
            data={"pin": "1234", "username": self.user.username},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_pin_verify_returns_cache_window(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/pos/pin/verify/",
            data={"pin": "1234"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["ok"], True)
        self.assertIn("verified_for_seconds", payload)

    def test_sensitive_receipt_create_requires_recent_verify(self):
        self.client.force_authenticate(user=self.user)
        blocked = self.client.post("/api/pos/receipts/", data={}, format="json", secure=True)
        self.assertEqual(blocked.status_code, 428, blocked.content)
        self.assertEqual(blocked.json()["pin_verify_required"], True)

        verify = self.client.post(
            "/api/pos/pin/verify/",
            data={"pin": "1234"},
            format="json",
            secure=True,
        )
        self.assertEqual(verify.status_code, 200, verify.content)

        after_verify = self.client.post("/api/pos/receipts/", data={}, format="json", secure=True)
        self.assertEqual(after_verify.status_code, 400, after_verify.content)
        self.assertEqual(after_verify.json()["detail"], "items su obavezne.")


class PosPrinterInventoryApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="printer-user",
            email="printer@example.com",
            password="pass1234",
        )
        warehouse = WarehouseId.objects.create(rm_id=1001, name="WH-TEST")
        pos = Pos.objects.create(
            external_pos_id=1001,
            name="POS-TEST",
            warehouse=warehouse,
            is_active=True,
        )
        self.device = PosDevice.objects.create(
            device_id="android-dev-1",
            pos=pos,
            name="Android 1",
            is_active=True,
        )
        PosProfile.objects.create(
            user=self.user,
            is_registered=True,
            registered_device_id=self.device.device_id,
        )
        self.client.force_authenticate(user=self.user)

    def test_printer_sync_upsert_and_deactivate_missing(self):
        stale = PosPrinterInventory.objects.create(
            device=self.device,
            name="OLD-PRINTER",
            is_active=True,
        )
        response = self.client.post(
            "/api/pos/printers/sync/",
            data={
                "device_id": self.device.device_id,
                "receiver_url": "http://100.64.0.8:8089/print",
                "printers": [
                    {"name": "STAR-TSP100", "is_default": True, "status": "ready", "raw": {"driver": "star"}},
                    {"name": "KITCHEN-2", "is_default": False, "status": "idle", "raw": {}},
                ],
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.device.refresh_from_db()
        stale.refresh_from_db()
        self.assertEqual(self.device.print_receiver_url, "http://100.64.0.8:8089/print")
        self.assertFalse(stale.is_active)
        self.assertEqual(self.device.printers.filter(is_active=True).count(), 2)

    def test_printer_selection_and_list(self):
        receipt = PosPrinterInventory.objects.create(device=self.device, name="RECEIPT", is_active=True)
        bar = PosPrinterInventory.objects.create(device=self.device, name="BAR", is_active=True)
        selection = self.client.patch(
            f"/api/pos/devices/{self.device.device_id}/printer-selection/",
            data={
                "receiver_url": "http://100.64.0.8:8089/print",
                "receipt_printer_id": receipt.id,
                "bar_printer_id": bar.id,
            },
            format="json",
            secure=True,
        )
        self.assertEqual(selection.status_code, 200, selection.content)
        payload = selection.json()
        self.assertEqual(payload["receipt_printer"]["id"], receipt.id)
        self.assertEqual(payload["bar_printer"]["id"], bar.id)

        listed = self.client.get(
            f"/api/pos/printers/?device_id={self.device.device_id}",
            secure=True,
        )
        self.assertEqual(listed.status_code, 200, listed.content)
        list_payload = listed.json()
        self.assertEqual(list_payload["receipt_printer_id"], receipt.id)
        self.assertEqual(list_payload["bar_printer_id"], bar.id)
        self.assertEqual(len(list_payload["printers"]), 2)
