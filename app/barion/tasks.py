from __future__ import annotations

import logging

import requests
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task
def send_catalog_changed_notification(*, version: int) -> bool:
    if not settings.BARION_FCM_ENABLED:
        logger.info("Barion FCM trigger disabled; skipping catalog_changed notification.")
        return False

    if not settings.BARION_FCM_TOPIC:
        logger.warning("Barion FCM topic not configured; skipping catalog_changed notification.")
        return False

    if not settings.BARION_GCLOUD_CALLER_TOKEN:
        logger.warning("Barion gcloud caller token not configured; skipping catalog_changed notification.")
        return False

    endpoint = f"{settings.BARION_GCLOUD_API_URL.rstrip('/')}/fcm/send"
    payload = {
        "project_alias": settings.BARION_FCM_PROJECT_ALIAS,
        "topic": settings.BARION_FCM_TOPIC,
        "data": {
            "type": "catalog_changed",
            "catalogVersion": str(int(version)),
        },
    }
    headers = {
        "Authorization": f"Bearer {settings.BARION_GCLOUD_CALLER_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=settings.BARION_GCLOUD_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Barion catalog_changed FCM trigger failed.")
        return False

    try:
        response_payload = response.json()
    except ValueError:
        logger.warning("Barion catalog_changed FCM trigger returned non-JSON response.")
        return False

    success = bool(response_payload.get("success"))
    if not success:
        logger.warning(
            "Barion catalog_changed FCM trigger rejected by gcloud service.",
            extra={"error_code": response_payload.get("error_code")},
        )
    return success
