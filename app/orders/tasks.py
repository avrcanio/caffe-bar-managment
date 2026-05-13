"""
Celery discovers ``<app_label>.tasks`` by default. Import push handlers here so
``orders.push_tasks.notify_purchase_order_topic`` is registered on workers.
"""

from orders.push_tasks import notify_purchase_order_topic  # noqa: F401
