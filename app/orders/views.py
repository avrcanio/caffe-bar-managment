from django.http import HttpResponse, HttpResponseNotFound
from django.utils import timezone

from .models import PurchaseOrder


def confirm_purchase_order(request, token):
    order = PurchaseOrder.objects.filter(confirmation_token=token).first()
    if not order:
        return HttpResponseNotFound("Token nije vazeci.")
    if order.status == PurchaseOrder.STATUS_CONFIRMED:
        return HttpResponse("Narudzba je vec potvrdena.")
    order.status = PurchaseOrder.STATUS_CONFIRMED
    order.confirmed_at = timezone.now()
    order.save(update_fields=["status", "confirmed_at"])
    return HttpResponse("Hvala, narudzba je potvrdena.")
