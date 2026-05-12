from __future__ import annotations

from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from artikli.models import Artikl, Category
from sales.models import SalesPriceItem

from .catalog_sync import CatalogEntityChange, ensure_product_sync_state, record_catalog_changes
from .models import (
    BarionCategory,
    BarionRuntimeMode,
    BarionProductSyncState,
    ItemBundleOption,
    ItemModifierDefaultSelection,
    ItemModifierGroup,
    ItemModifierGroupAssignment,
    ItemModifierOption,
    Layout,
    LayoutTable,
    ProductPopularitySnapshot,
    Table,
    UserLayoutAccess,
    Zone,
)


def _record_layout_upsert(*, layout_ids: list[int]):
    record_catalog_changes(
        changes=[
            CatalogEntityChange(entity_type="layout", entity_id=layout_id, operation="upsert")
            for layout_id in layout_ids
            if layout_id
        ]
    )


def _record_layout_delete(*, layout_id: int):
    record_catalog_changes(
        changes=[CatalogEntityChange(entity_type="layout", entity_id=layout_id, operation="delete")]
    )


def _record_category_upsert(*, category_ids: list[int]):
    record_catalog_changes(
        changes=[
            CatalogEntityChange(entity_type="category", entity_id=category_id, operation="upsert")
            for category_id in category_ids
            if category_id
        ]
    )


def _record_category_delete(*, category_id: int):
    record_catalog_changes(
        changes=[CatalogEntityChange(entity_type="category", entity_id=category_id, operation="delete")]
    )


def _record_product_upsert(*, artikl_ids: list[int], image_delta_ids: set[int] | None = None, modifier_delta_ids: set[int] | None = None):
    image_delta_ids = image_delta_ids or set()
    modifier_delta_ids = modifier_delta_ids or set()
    sync_updates = {}
    for artikl_id in {int(artikl_id) for artikl_id in artikl_ids if artikl_id}:
        sync_updates[artikl_id] = {
            "image_delta": 1 if artikl_id in image_delta_ids else 0,
            "modifier_delta": 1 if artikl_id in modifier_delta_ids else 0,
        }
    record_catalog_changes(
        changes=[
            CatalogEntityChange(entity_type="product", entity_id=artikl_id, operation="upsert")
            for artikl_id in sync_updates.keys()
        ],
        product_sync_updates=sync_updates,
    )


def _record_product_delete(*, artikl_id: int):
    record_catalog_changes(
        changes=[CatalogEntityChange(entity_type="product", entity_id=artikl_id, operation="delete")]
    )


def _modifier_artikl_ids_from_group(group: ItemModifierGroup) -> list[int]:
    return list(group.artikl_assignments.values_list("artikl_id", flat=True).distinct())


@receiver(pre_save, sender=Artikl)
def cache_artikl_pre_save(sender, instance: Artikl, **kwargs):
    if not instance.pk:
        instance._barion_prev_image_name = None
        return
    previous = Artikl.objects.filter(pk=instance.pk).only("image").first()
    instance._barion_prev_image_name = previous.image.name if previous and previous.image else None


@receiver(post_save, sender=Artikl)
def artikl_saved(sender, instance: Artikl, created: bool, **kwargs):
    ensure_product_sync_state(artikl_id=instance.id)
    previous_name = getattr(instance, "_barion_prev_image_name", None)
    current_name = instance.image.name if instance.image else None
    image_changed = (not created) and previous_name != current_name
    _record_product_upsert(
        artikl_ids=[instance.id],
        image_delta_ids={instance.id} if image_changed else set(),
    )


@receiver(post_delete, sender=Artikl)
def artikl_deleted(sender, instance: Artikl, **kwargs):
    _record_product_delete(artikl_id=instance.id)


@receiver(post_save, sender=SalesPriceItem)
def sales_price_item_saved(sender, instance: SalesPriceItem, **kwargs):
    if instance.artikl_id:
        _record_product_upsert(artikl_ids=[instance.artikl_id])


@receiver(post_delete, sender=SalesPriceItem)
def sales_price_item_deleted(sender, instance: SalesPriceItem, **kwargs):
    if instance.artikl_id:
        _record_product_upsert(artikl_ids=[instance.artikl_id])


@receiver(post_save, sender=ProductPopularitySnapshot)
def popularity_saved(sender, instance: ProductPopularitySnapshot, **kwargs):
    _record_product_upsert(artikl_ids=[instance.artikl_id])


@receiver(post_delete, sender=ProductPopularitySnapshot)
def popularity_deleted(sender, instance: ProductPopularitySnapshot, **kwargs):
    _record_product_upsert(artikl_ids=[instance.artikl_id])


@receiver(post_save, sender=Category)
def category_saved(sender, instance: Category, **kwargs):
    _record_category_upsert(category_ids=[instance.id])


@receiver(post_delete, sender=Category)
def category_deleted(sender, instance: Category, **kwargs):
    _record_category_delete(category_id=instance.id)


@receiver(post_save, sender=BarionCategory)
def barion_category_saved(sender, instance: BarionCategory, **kwargs):
    _record_category_upsert(category_ids=[instance.category_id])


@receiver(post_delete, sender=BarionCategory)
def barion_category_deleted(sender, instance: BarionCategory, **kwargs):
    _record_category_delete(category_id=instance.category_id)


@receiver(post_save, sender=Layout)
def layout_saved(sender, instance: Layout, **kwargs):
    _record_layout_upsert(layout_ids=[instance.id])


@receiver(post_delete, sender=Layout)
def layout_deleted(sender, instance: Layout, **kwargs):
    _record_layout_delete(layout_id=instance.id)


@receiver(post_save, sender=Zone)
def zone_saved(sender, instance: Zone, **kwargs):
    _record_layout_upsert(layout_ids=[instance.layout_id])


@receiver(post_delete, sender=Zone)
def zone_deleted(sender, instance: Zone, **kwargs):
    _record_layout_upsert(layout_ids=[instance.layout_id])


@receiver(post_save, sender=LayoutTable)
def layout_table_saved(sender, instance: LayoutTable, **kwargs):
    _record_layout_upsert(layout_ids=[instance.layout_id])


@receiver(post_delete, sender=LayoutTable)
def layout_table_deleted(sender, instance: LayoutTable, **kwargs):
    _record_layout_upsert(layout_ids=[instance.layout_id])


@receiver(post_save, sender=UserLayoutAccess)
def user_layout_access_saved(sender, instance: UserLayoutAccess, **kwargs):
    _record_layout_upsert(layout_ids=[instance.layout_id])


@receiver(post_delete, sender=UserLayoutAccess)
def user_layout_access_deleted(sender, instance: UserLayoutAccess, **kwargs):
    _record_layout_upsert(layout_ids=[instance.layout_id])


@receiver(post_save, sender=Table)
def table_saved(sender, instance: Table, **kwargs):
    layout_ids = list(instance.layout_tables.values_list("layout_id", flat=True).distinct())
    if layout_ids:
        _record_layout_upsert(layout_ids=layout_ids)


@receiver(post_save, sender=ItemModifierGroup)
def modifier_group_saved(sender, instance: ItemModifierGroup, **kwargs):
    artikl_ids = _modifier_artikl_ids_from_group(instance)
    if artikl_ids:
        _record_product_upsert(artikl_ids=artikl_ids, modifier_delta_ids=set(artikl_ids))


@receiver(pre_delete, sender=ItemModifierGroup)
def modifier_group_pre_delete(sender, instance: ItemModifierGroup, **kwargs):
    instance._barion_artikl_ids = _modifier_artikl_ids_from_group(instance)


@receiver(post_delete, sender=ItemModifierGroup)
def modifier_group_deleted(sender, instance: ItemModifierGroup, **kwargs):
    artikl_ids = getattr(instance, "_barion_artikl_ids", [])
    if artikl_ids:
        _record_product_upsert(artikl_ids=artikl_ids, modifier_delta_ids=set(artikl_ids))


@receiver(post_save, sender=ItemModifierOption)
def modifier_option_saved(sender, instance: ItemModifierOption, **kwargs):
    artikl_ids = _modifier_artikl_ids_from_group(instance.group)
    if artikl_ids:
        _record_product_upsert(artikl_ids=artikl_ids, modifier_delta_ids=set(artikl_ids))


@receiver(pre_delete, sender=ItemModifierOption)
def modifier_option_pre_delete(sender, instance: ItemModifierOption, **kwargs):
    instance._barion_artikl_ids = _modifier_artikl_ids_from_group(instance.group)


@receiver(post_delete, sender=ItemModifierOption)
def modifier_option_deleted(sender, instance: ItemModifierOption, **kwargs):
    artikl_ids = getattr(instance, "_barion_artikl_ids", [])
    if artikl_ids:
        _record_product_upsert(artikl_ids=artikl_ids, modifier_delta_ids=set(artikl_ids))


@receiver(post_save, sender=ItemBundleOption)
def bundle_option_saved(sender, instance: ItemBundleOption, **kwargs):
    artikl_ids = _modifier_artikl_ids_from_group(instance.group)
    if artikl_ids:
        _record_product_upsert(artikl_ids=artikl_ids, modifier_delta_ids=set(artikl_ids))


@receiver(pre_delete, sender=ItemBundleOption)
def bundle_option_pre_delete(sender, instance: ItemBundleOption, **kwargs):
    instance._barion_artikl_ids = _modifier_artikl_ids_from_group(instance.group)


@receiver(post_delete, sender=ItemBundleOption)
def bundle_option_deleted(sender, instance: ItemBundleOption, **kwargs):
    artikl_ids = getattr(instance, "_barion_artikl_ids", [])
    if artikl_ids:
        _record_product_upsert(artikl_ids=artikl_ids, modifier_delta_ids=set(artikl_ids))


@receiver(post_save, sender=ItemModifierGroupAssignment)
def modifier_assignment_saved(sender, instance: ItemModifierGroupAssignment, **kwargs):
    _record_product_upsert(artikl_ids=[instance.artikl_id], modifier_delta_ids={instance.artikl_id})


@receiver(post_delete, sender=ItemModifierGroupAssignment)
def modifier_assignment_deleted(sender, instance: ItemModifierGroupAssignment, **kwargs):
    _record_product_upsert(artikl_ids=[instance.artikl_id], modifier_delta_ids={instance.artikl_id})


@receiver(pre_delete, sender=ItemModifierDefaultSelection)
def modifier_default_pre_delete(sender, instance: ItemModifierDefaultSelection, **kwargs):
    instance._barion_artikl_id = instance.assignment.artikl_id if instance.assignment_id else None


@receiver(post_save, sender=ItemModifierDefaultSelection)
def modifier_default_saved(sender, instance: ItemModifierDefaultSelection, **kwargs):
    if instance.assignment_id:
        _record_product_upsert(
            artikl_ids=[instance.assignment.artikl_id],
            modifier_delta_ids={instance.assignment.artikl_id},
        )


@receiver(post_delete, sender=ItemModifierDefaultSelection)
def modifier_default_deleted(sender, instance: ItemModifierDefaultSelection, **kwargs):
    artikl_id = getattr(instance, "_barion_artikl_id", None)
    if artikl_id:
        _record_product_upsert(artikl_ids=[artikl_id], modifier_delta_ids={artikl_id})


@receiver(post_save, sender=BarionRuntimeMode)
def runtime_mode_saved(sender, instance: BarionRuntimeMode, **kwargs):
    category_ids = list(BarionCategory.objects.filter(is_active=True).values_list("category_id", flat=True))
    artikl_ids = list(BarionProductSyncState.objects.values_list("artikl_id", flat=True))
    product_sync_updates = {
        int(artikl_id): {
            "image_delta": 0,
            "modifier_delta": 0,
        }
        for artikl_id in artikl_ids
    }
    record_catalog_changes(
        changes=[
            *[
                CatalogEntityChange(entity_type="category", entity_id=category_id, operation="upsert")
                for category_id in category_ids
                if category_id
            ],
            *[
                CatalogEntityChange(entity_type="product", entity_id=artikl_id, operation="upsert")
                for artikl_id in artikl_ids
                if artikl_id
            ],
        ],
        product_sync_updates=product_sync_updates,
    )
