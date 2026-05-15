from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from sales.models import SalesPriceItem


def resolve_active_sales_unit_price(
    artikl_id: int,
    *,
    at: datetime | None = None,
) -> Decimal | None:
    moment = at if at is not None else timezone.now()
    unit_price = (
        SalesPriceItem.objects.filter(
            artikl_id=artikl_id,
            is_active=True,
            price_list__is_active=True,
            price_list__valid_from__lte=moment,
        )
        .filter(
            Q(price_list__valid_to__isnull=True)
            | Q(price_list__valid_to__gte=moment)
        )
        .order_by("-price_list__valid_from", "-price_list__created_at", "-id")
        .values_list("unit_price_gross", flat=True)
        .first()
    )
    if unit_price is None:
        return None
    return Decimal(str(unit_price)).quantize(Decimal("0.0001"))
