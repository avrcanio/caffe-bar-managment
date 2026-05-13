from django.db import transaction
from django.http import HttpResponse, HttpResponseNotFound
from django.utils import timezone

from .models import PurchaseOrder
from .push_tasks import notify_purchase_order_topic


def confirm_purchase_order(request, token):
    order = (
        PurchaseOrder.objects.select_related("supplier")
        .filter(confirmation_token=token)
        .first()
    )
    if not order:
        return HttpResponseNotFound("Token nije vazeci.")
    if order.status == PurchaseOrder.STATUS_CONFIRMED:
        return HttpResponse("Narudzba je vec potvrdena.")
    order.status = PurchaseOrder.STATUS_CONFIRMED
    order.confirmed_at = timezone.now()
    order.save(update_fields=["status", "confirmed_at"])
    supplier_name = order.supplier.name
    order_id = order.id
    transaction.on_commit(
        lambda: notify_purchase_order_topic.delay(
            event="confirmed",
            order_id=order_id,
            supplier_name=supplier_name,
        )
    )
    return HttpResponse("Hvala, narudzba je potvrdena.")
