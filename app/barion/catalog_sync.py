from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from django.db import transaction
from django.db.models import Min

from .models import BarionCatalogState, BarionCatalogSyncEvent, BarionProductSyncState


@dataclass(frozen=True)
class CatalogEntityChange:
    entity_type: str
    entity_id: int
    operation: str


def get_catalog_version() -> int:
    return int(BarionCatalogState.get_solo().catalog_version)


def ensure_product_sync_state(*, artikl_id: int) -> BarionProductSyncState:
    state, _ = BarionProductSyncState.objects.get_or_create(artikl_id=artikl_id)
    return state


def get_product_sync_state(*, artikl_id: int) -> BarionProductSyncState | None:
    return BarionProductSyncState.objects.filter(artikl_id=artikl_id).first()


def _normalize_changes(changes: Iterable[CatalogEntityChange]) -> list[CatalogEntityChange]:
    latest_by_entity: dict[tuple[str, int], CatalogEntityChange] = {}
    for change in changes:
        if change.entity_id is None:
            continue
        latest_by_entity[(str(change.entity_type), int(change.entity_id))] = CatalogEntityChange(
            entity_type=str(change.entity_type),
            entity_id=int(change.entity_id),
            operation=str(change.operation),
        )
    return list(latest_by_entity.values())


def record_catalog_changes(
    *,
    changes: Iterable[CatalogEntityChange],
    product_sync_updates: dict[int, dict[str, int]] | None = None,
) -> int | None:
    normalized_changes = _normalize_changes(changes)
    sync_updates = {int(k): v for k, v in (product_sync_updates or {}).items()}
    if not normalized_changes and not sync_updates:
        return None

    with transaction.atomic():
        state = BarionCatalogState.objects.select_for_update().get_or_create(pk=1, defaults={"catalog_version": 0})[0]
        state.catalog_version = int(state.catalog_version) + 1
        state.save(update_fields=["catalog_version", "updated_at"])
        version = int(state.catalog_version)

        if normalized_changes:
            BarionCatalogSyncEvent.objects.bulk_create(
                [
                    BarionCatalogSyncEvent(
                        version=version,
                        entity_type=change.entity_type,
                        entity_id=change.entity_id,
                        operation=change.operation,
                    )
                    for change in normalized_changes
                ]
            )

        for artikl_id, updates in sync_updates.items():
            state_row = ensure_product_sync_state(artikl_id=artikl_id)
            dirty_fields: list[str] = []
            if updates.get("image_delta"):
                state_row.image_version = int(state_row.image_version) + int(updates["image_delta"])
                dirty_fields.append("image_version")
            if updates.get("modifier_delta"):
                state_row.modifier_version = int(state_row.modifier_version) + int(updates["modifier_delta"])
                dirty_fields.append("modifier_version")
            state_row.last_catalog_version = version
            dirty_fields.append("last_catalog_version")
            if dirty_fields:
                dirty_fields.append("updated_at")
                state_row.save(update_fields=dirty_fields)

        transaction.on_commit(lambda: _emit_catalog_changed(version=version))
    return version


def _emit_catalog_changed(*, version: int) -> None:
    from .tasks import send_catalog_changed_notification

    send_catalog_changed_notification.delay(version=int(version))
    return None


def earliest_catalog_event_version() -> int | None:
    row = BarionCatalogSyncEvent.objects.aggregate(min_version=Min("version"))
    if row["min_version"] is None:
        return None
    return int(row["min_version"])


def collect_delta_ids(*, after_version: int, target_version: int) -> dict[str, dict[str, set[int]]]:
    rows = (
        BarionCatalogSyncEvent.objects.filter(version__gt=after_version, version__lte=target_version)
        .order_by("version", "id")
        .values_list("entity_type", "entity_id", "operation")
    )
    result: dict[str, dict[str, set[int]]] = defaultdict(lambda: {"updated": set(), "deleted": set()})
    for entity_type, entity_id, operation in rows:
        entity_bucket = result[str(entity_type)]
        entity_id = int(entity_id)
        if operation == BarionCatalogSyncEvent.Operation.DELETE:
            entity_bucket["updated"].discard(entity_id)
            entity_bucket["deleted"].add(entity_id)
        else:
            entity_bucket["deleted"].discard(entity_id)
            entity_bucket["updated"].add(entity_id)
    return result
