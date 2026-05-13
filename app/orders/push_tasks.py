from __future__ import annotations

import logging
from typing import Literal

import requests
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

PurchaseOrderPushEvent = Literal["sent", "confirmed"]


def _post_topic_message(
    *,
    title: str,
    body: str,
    data: dict[str, str],
) -> bool:
    if not settings.MOZZART_FCM_ENABLED:
        logger.info("Mozzart FCM disabled; skipping purchase order notification.")
        return False

    if not settings.MOZZART_FCM_TOPIC:
        logger.warning("Mozzart FCM topic not configured; skipping purchase order notification.")
        return False

    if not settings.MOZZART_GCLOUD_CALLER_TOKEN:
        logger.warning(
            "Mozzart gcloud caller token not configured; skipping purchase order notification."
        )
        return False

    endpoint = f"{settings.MOZZART_GCLOUD_API_URL.rstrip('/')}/fcm/send"
    payload: dict = {
        "project_alias": settings.MOZZART_FCM_PROJECT_ALIAS,
        "topic": settings.MOZZART_FCM_TOPIC,
        "notification": {"title": title, "body": body},
        "data": data,
    }
    headers = {
        "Authorization": f"Bearer {settings.MOZZART_GCLOUD_CALLER_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=settings.MOZZART_GCLOUD_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Mozzart purchase order FCM trigger failed.")
        return False

    try:
        response_payload = response.json()
    except ValueError:
        logger.warning("Mozzart purchase order FCM trigger returned non-JSON response.")
        return False

    success = bool(response_payload.get("success"))
    if not success:
        logger.warning(
            "Mozzart purchase order FCM trigger rejected by gcloud service.",
            extra={"error_code": response_payload.get("error_code")},
        )
    return success


@shared_task
def notify_purchase_order_topic(
    *,
    event: PurchaseOrderPushEvent,
    order_id: int,
    supplier_name: str,
) -> bool:
    """
    Send FCM topic notification for purchase order lifecycle (sent / confirmed).
    Data payload values must be strings (gcloud-api contract).
    """
    supplier_name = (supplier_name or "").strip() or "Dobavljac"
    if event == "sent":
        title = "Narudzba poslana"
        body = f"#{order_id} — {supplier_name}"
        data = {
            "type": "purchase_order_sent",
            "purchase_order_id": str(int(order_id)),
            "supplier_name": supplier_name,
        }
    elif event == "confirmed":
        title = "Narudzba potvrdena"
        body = f"Dobavljac je potvrdio narudzbu #{order_id} ({supplier_name})."
        data = {
            "type": "purchase_order_confirmed",
            "purchase_order_id": str(int(order_id)),
            "supplier_name": supplier_name,
        }
    else:
        logger.error("Unknown purchase order push event: %s", event)
        return False

    return _post_topic_message(title=title, body=body, data=data)
