from __future__ import annotations

import logging
from decimal import Decimal

from django.db.models import F, Q
from django.utils import timezone

from artikli.remaris_connector import RemarisConnector
from sales.models import SalesPriceItem, SalesPriceList
from sales.price_resolution import resolve_active_sales_unit_price
from sales.remaris_pricelist import (
    resolve_remaris_price_list_id,
    resolve_remaris_product_id,
    save_remaris_product_price,
    sync_sales_pricelist_to_remaris,
    transfer_sales_prices_to_pos,
)

logger = logging.getLogger(__name__)


def price_lists_due_for_apply(*, at=None):
    moment = at if at is not None else timezone.now()
    return SalesPriceList.objects.filter(
        is_active=True,
        remaris_sync_transfer_pos=True,
        valid_from__lte=moment,
    ).filter(
        Q(remaris_applied_at__isnull=True) | Q(remaris_applied_at__lt=F("valid_from"))
    ).filter(Q(valid_to__isnull=True) | Q(valid_to__gt=moment))


def price_lists_due_for_revert(*, at=None):
    moment = at if at is not None else timezone.now()
    return SalesPriceList.objects.filter(
        valid_to__isnull=False,
        valid_to__lte=moment,
        remaris_applied_at__isnull=False,
        remaris_reverted_at__isnull=True,
    )


def apply_price_list_to_remaris(
    price_list: SalesPriceList,
    *,
    remaris_price_list_id: int | None = None,
    write_line=None,
) -> dict:
    target_remaris_id = (
        remaris_price_list_id
        if remaris_price_list_id is not None
        else resolve_remaris_price_list_id(price_list)
    )
    sent, skipped, errors = sync_sales_pricelist_to_remaris(
        price_list=price_list,
        remaris_price_list_id=target_remaris_id,
        include_inactive=False,
        dry_run=False,
        write_line=write_line,
    )
    if errors > 0:
        return {
            "price_list_id": price_list.id,
            "phase": "apply",
            "ok": False,
            "sent": sent,
            "skipped": skipped,
            "errors": errors,
        }

    if price_list.remaris_sync_transfer_pos:
        transfer_sales_prices_to_pos()
    now = timezone.now()
    SalesPriceList.objects.filter(pk=price_list.pk).update(
        remaris_applied_at=now,
        remaris_reverted_at=None,
    )
    price_list.remaris_applied_at = now
    price_list.remaris_reverted_at = None

    return {
        "price_list_id": price_list.id,
        "phase": "apply",
        "ok": True,
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
    }


def revert_price_list_from_remaris(
    price_list: SalesPriceList,
    *,
    remaris_price_list_id: int | None = None,
    at=None,
    write_line=None,
) -> dict:
    moment = at if at is not None else timezone.now()
    remaris_price_list_id = (
        remaris_price_list_id
        if remaris_price_list_id is not None
        else resolve_remaris_price_list_id(price_list)
    )

    items = (
        SalesPriceItem.objects.filter(price_list=price_list, is_active=True)
        .select_related(
            "artikl",
            "artikl__detail",
            "artikl__detail__sales_group",
            "artikl__detail__keyboard_group",
        )
        .order_by("id")
    )

    connector = RemarisConnector()
    connector.login()

    sent = 0
    skipped = 0
    errors = 0

    for item in items:
        artikl = item.artikl
        detail = getattr(artikl, "detail", None) if artikl else None
        product_id = resolve_remaris_product_id(artikl=artikl, detail=detail)
        if not artikl or not product_id:
            skipped += 1
            if write_line:
                write_line(
                    f"SKIP revert item_id={item.id} missing product_id "
                    f"(artikl_id={item.artikl_id})"
                )
            continue

        unit_price = resolve_active_sales_unit_price(artikl.id, at=moment)
        if unit_price is None:
            skipped += 1
            if write_line:
                write_line(
                    f"SKIP revert item_id={item.id} artikl_id={artikl.id} "
                    "no effective price"
                )
            continue

        price_value = Decimal(unit_price).quantize(Decimal("0.01"))
        context_label = f"revert item_id={item.id}"
        ok = save_remaris_product_price(
            connector,
            product_id=product_id,
            price_value=price_value,
            remaris_price_list_id=remaris_price_list_id,
            artikl=artikl,
            detail=detail,
            is_active=True,
            dry_run=False,
            write_line=write_line,
            context_label=context_label,
        )
        if ok:
            sent += 1
        else:
            errors += 1

    if errors > 0:
        return {
            "price_list_id": price_list.id,
            "phase": "revert",
            "ok": False,
            "sent": sent,
            "skipped": skipped,
            "errors": errors,
        }

    transfer_sales_prices_to_pos()
    now = timezone.now()
    SalesPriceList.objects.filter(pk=price_list.pk).update(
        remaris_reverted_at=now,
        remaris_applied_at=None,
    )
    price_list.remaris_reverted_at = now
    price_list.remaris_applied_at = None

    return {
        "price_list_id": price_list.id,
        "phase": "revert",
        "ok": True,
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
    }


def process_scheduled_sales_price_lists(*, at=None) -> dict:
    applied: list[dict] = []
    reverted: list[dict] = []
    failed: list[dict] = []

    for price_list in price_lists_due_for_apply(at=at).order_by("valid_from", "id"):
        try:
            result = apply_price_list_to_remaris(price_list)
        except Exception as exc:
            logger.exception(
                "Failed to apply sales price list id=%s to Remaris",
                price_list.id,
            )
            failed.append(
                {
                    "price_list_id": price_list.id,
                    "phase": "apply",
                    "error": str(exc),
                }
            )
            continue
        if result.get("ok"):
            applied.append(result)
        else:
            failed.append(result)

    for price_list in price_lists_due_for_revert(at=at).order_by("valid_to", "id"):
        try:
            result = revert_price_list_from_remaris(price_list, at=at)
        except Exception as exc:
            logger.exception(
                "Failed to revert sales price list id=%s from Remaris",
                price_list.id,
            )
            failed.append(
                {
                    "price_list_id": price_list.id,
                    "phase": "revert",
                    "error": str(exc),
                }
            )
            continue
        if result.get("ok"):
            reverted.append(result)
        else:
            failed.append(result)

    return {
        "applied": applied,
        "reverted": reverted,
        "failed": failed,
    }
