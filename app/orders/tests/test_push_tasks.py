from unittest.mock import patch

from django.test import TestCase, override_settings


class MozzartPurchaseOrderPushTaskTests(TestCase):
    @override_settings(
        MOZZART_FCM_ENABLED=True,
        MOZZART_GCLOUD_API_URL="http://gcloud-api:8080",
        MOZZART_GCLOUD_CALLER_TOKEN="test-mozzart-token",
        MOZZART_FCM_PROJECT_ALIAS="fcm_barion",
        MOZZART_FCM_TOPIC="mozzart_purchase_orders",
        MOZZART_GCLOUD_TIMEOUT=3,
    )
    @patch("orders.push_tasks.requests.post")
    def test_notify_sent_posts_topic_with_notification(self, mock_post):
        from orders.push_tasks import notify_purchase_order_topic

        mock_post.return_value.json.return_value = {"success": True, "message_id": "msg-1"}
        mock_post.return_value.raise_for_status.return_value = None

        result = notify_purchase_order_topic(
            event="sent",
            order_id=231,
            supplier_name="Fructus d.o.o.",
        )

        self.assertEqual(result, True)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://gcloud-api:8080/fcm/send")
        self.assertEqual(
            kwargs["json"],
            {
                "project_alias": "fcm_barion",
                "topic": "mozzart_purchase_orders",
                "notification": {
                    "title": "Narudzba poslana",
                    "body": "#231 — Fructus d.o.o.",
                },
                "data": {
                    "type": "purchase_order_sent",
                    "purchase_order_id": "231",
                    "supplier_name": "Fructus d.o.o.",
                },
            },
        )
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer test-mozzart-token",
        )

    @override_settings(
        MOZZART_FCM_ENABLED=True,
        MOZZART_GCLOUD_API_URL="http://gcloud-api:8080",
        MOZZART_GCLOUD_CALLER_TOKEN="test-mozzart-token",
        MOZZART_FCM_PROJECT_ALIAS="fcm_barion",
        MOZZART_FCM_TOPIC="mozzart_purchase_orders",
        MOZZART_GCLOUD_TIMEOUT=3,
    )
    @patch("orders.push_tasks.requests.post")
    def test_notify_confirmed_posts_topic(self, mock_post):
        from orders.push_tasks import notify_purchase_order_topic

        mock_post.return_value.json.return_value = {"success": True, "message_id": "msg-2"}
        mock_post.return_value.raise_for_status.return_value = None

        result = notify_purchase_order_topic(
            event="confirmed",
            order_id=10,
            supplier_name="ACME",
        )

        self.assertEqual(result, True)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["data"]["type"], "purchase_order_confirmed")
        self.assertEqual(payload["data"]["purchase_order_id"], "10")
        self.assertIn("ACME", payload["notification"]["body"])

    @override_settings(MOZZART_FCM_ENABLED=False)
    @patch("orders.push_tasks.requests.post")
    def test_notify_is_noop_when_disabled(self, mock_post):
        from orders.push_tasks import notify_purchase_order_topic

        result = notify_purchase_order_topic(
            event="sent",
            order_id=1,
            supplier_name="X",
        )

        self.assertEqual(result, False)
        mock_post.assert_not_called()

    @override_settings(
        MOZZART_FCM_ENABLED=True,
        MOZZART_FCM_TOPIC="",
        MOZZART_GCLOUD_CALLER_TOKEN="x",
    )
    @patch("orders.push_tasks.requests.post")
    def test_notify_skips_when_topic_missing(self, mock_post):
        from orders.push_tasks import notify_purchase_order_topic

        result = notify_purchase_order_topic(event="sent", order_id=1, supplier_name="Y")
        self.assertEqual(result, False)
        mock_post.assert_not_called()
