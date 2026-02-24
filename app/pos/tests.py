from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from pos.models import PosProfile


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
