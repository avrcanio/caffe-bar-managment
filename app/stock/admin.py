import datetime
import json
from decimal import Decimal

import requests

from django.contrib import admin, messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone

from artikli.remaris_connector import RemarisConnector
from artikli.models import Artikl
from stock.models import (
    Inventory,
    InventoryItem,
    ProductStockDS,
    ReplenishRequestLine,
    StockAllocation,
    StockAccountingConfig,
    StockLot,
    StockMove,
    StockMoveLine,
    WarehouseId,
    WarehouseStock,
    WarehouseTransfer,
    WarehouseTransferItem,
)
from stock.services import replenish_to_sale_warehouse


@admin.action(description="Import stanje skladišta from Remaris", permissions=["change"])
def import_warehouse_stock(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    warehouse_ids = list(
        queryset.values_list("warehouse_id_id", flat=True).distinct()
    )
    warehouse_ids = [warehouse_id for warehouse_id in warehouse_ids if warehouse_id]
    if not warehouse_ids:
        modeladmin.message_user(
            request,
            "Nema selektiranih redova sa skladištem.",
            level=messages.WARNING,
        )
        return

    created = 0
    updated = 0
    skipped = 0

    with transaction.atomic():
        for warehouse_id in warehouse_ids:
            payload = {
                "dataSource": "warehouseStockDS",
                "operationType": "fetch",
                "startRow": 0,
                "endRow": 10001,
                "textMatchStyle": "exact",
                "componentId": "warehouseStockGrid",
                "oldValues": None,
                "data": {
                    "warehouseId": warehouse_id,
                    "allBaseGroups": True,
                    "showFilter": 20,
                    "request": "?_3403.578121292664",
                },
            }

            response = connector.post_json(
                "WarehouseStock/GetGridData?isc_dataFormat=json",
                payload,
                referer_path="/WarehouseStock",
            )

            data = response.get("response", {}).get("data", [])

            for item in data:
                wh_id = item.get("id")
                if wh_id is None:
                    skipped += 1
                    continue

                row = WarehouseStock.objects.filter(wh_id=wh_id).first()
                if not row:
                    skipped += 1
                    continue

                product_code = item.get("productCode", "")
                product = None
                if product_code:
                    product = Artikl.objects.filter(code=product_code).first()

                row.warehouse_id_id = warehouse_id
                row.product = product
                row.product_name = item.get("productName", "")
                row.product_code = product_code
                row.unit = item.get("unit", "")
                row.quantity = item.get("quantity", 0)
                row.base_group_name = item.get("baseGroupName", "")
                row.active = bool(item.get("active", False))
                row.save()
                updated += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


def _import_warehouse_stock_for_warehouses(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    warehouses = list(queryset)
    if not warehouses:
        modeladmin.message_user(
            request,
            "Nema selektiranih skladista.",
            level=messages.WARNING,
        )
        return False

    created = 0
    updated = 0
    skipped = 0

    try:
        with transaction.atomic():
            for warehouse in warehouses:
                payload = {
                    "dataSource": "warehouseStockDS",
                    "operationType": "fetch",
                    "startRow": 0,
                    "endRow": 10001,
                    "textMatchStyle": "exact",
                    "componentId": "warehouseStockGrid",
                    "oldValues": None,
                    "data": {
                        "warehouseId": warehouse.rm_id,
                        "allBaseGroups": True,
                        "showFilter": 20,
                        "request": "?_3403.578121292664",
                    },
                }

                response = connector.post_json(
                    "WarehouseStock/GetGridData?isc_dataFormat=json",
                    payload,
                    referer_path="/WarehouseStock",
                )

                data = response.get("response", {}).get("data", [])

                for item in data:
                    wh_id = item.get("id")
                    if wh_id is None:
                        skipped += 1
                        continue

                    product_code = item.get("productCode", "")
                    product = None
                    if product_code:
                        product = Artikl.objects.filter(code=product_code).first()

                    defaults = {
                        "warehouse_id_id": warehouse.rm_id,
                        "product": product,
                        "product_name": item.get("productName", ""),
                        "product_code": product_code,
                        "unit": item.get("unit", ""),
                        "quantity": item.get("quantity", 0),
                        "base_group_name": item.get("baseGroupName", ""),
                        "active": bool(item.get("active", False)),
                    }

                    _, was_created = WarehouseStock.objects.update_or_create(
                        wh_id=wh_id,
                        defaults=defaults,
                    )
                    if was_created:
                        created += 1
                    else:
                        updated += 1
    except requests.RequestException as exc:
        status_code = None
        response_text = None
        if getattr(exc, "response", None) is not None:
            status_code = exc.response.status_code
            response_text = exc.response.text
        detail = "status={status} response={response}".format(
            status=status_code if status_code is not None else "n/a",
            response=response_text if response_text else "n/a",
        )
        modeladmin.message_user(
            request,
            f"Import failed. Remaris request error. {detail}",
            level=messages.ERROR,
        )
        return False

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )
    return True


@admin.action(
    description="Import stanje artikala iz Remarisa (odabrana skladista)",
    permissions=["change"],
)
def import_warehouse_stock_for_warehouses(modeladmin, request, queryset):
    _import_warehouse_stock_for_warehouses(modeladmin, request, queryset)


@admin.action(description="Import stanje artikla from Remaris", permissions=["change"])
def import_product_stock(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    payload = {
        "dataSource": "productStockDS",
        "operationType": "fetch",
        "startRow": 0,
        "endRow": 10001,
        "textMatchStyle": "exact",
        "componentId": "productStockGrid",
        "oldValues": None,
        "data": {
            "organizationId": 2,
            "allBaseGroups": True,
            "request": "?_3976.175375320663",
        },
    }

    response = connector.post_json(
        "ProductStock/GetGridData?isc_dataFormat=json",
        payload,
        referer_path="/ProductStock",
    )

    data = response.get("response", {}).get("data", [])

    created = 0
    updated = 0
    skipped = 0

    with transaction.atomic():
        for item in data:
            rm_id = item.get("id")
            if rm_id is None:
                skipped += 1
                continue

            defaults = {
                "product": item.get("product", ""),
                "quantity": item.get("quantity", 0),
                "unit_of_measure": item.get("unitOfMeasure", ""),
                "input_value": item.get("inputValue", 0),
                "base_group_name": item.get("baseGroupName", ""),
                "product_code": item.get("productCode", ""),
            }

            _, was_created = ProductStockDS.objects.update_or_create(
                rm_id=rm_id,
                defaults=defaults,
            )
            if was_created:
                created += 1
            else:
                updated += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


def _format_remaris_error(response):
    message = response.get("message") if isinstance(response, dict) else None
    payload = {
        "success": response.get("success") if isinstance(response, dict) else None,
        "message": message or "Remaris error",
        "response": response,
    }
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)


def _format_transfer_payload_debug(transfer, items, payload):
    debug_payload = {
        "warehouse_from": transfer.from_warehouse_id,
        "warehouse_to": transfer.to_warehouse_id,
        "date": transfer.date.isoformat(),
        "dont_change_inventory_quantity": transfer.dont_change_inventory_quantity,
        "items": [
            {
                "product_id": item.get("ProductId"),
                "product_name": item.get("ProductName"),
                "quantity": item.get("Quantity"),
                "unit_name": item.get("UnitName"),
            }
            for item in items
        ],
        "payload": payload,
    }
    return json.dumps(debug_payload, ensure_ascii=True, indent=2, sort_keys=True)


@admin.action(description="Send međuskladišnicu to Remaris", permissions=["change"])
def send_warehouse_transfer_to_remaris(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    created = 0
    updated = 0
    skipped = 0
    failed = 0

    with transaction.atomic():
        for transfer in queryset:
            had_remaris_id = bool(transfer.remaris_id)
            if not transfer.from_warehouse_id or not transfer.to_warehouse_id:
                skipped += 1
                continue

            items = []
            item_errors = []
            for item in transfer.items.select_related("artikl", "unit").all():
                if not item.artikl_id or not item.quantity:
                    item_errors.append("Stavka bez artikla ili količine.")
                    continue
                if item.artikl.rm_id is None:
                    item_errors.append(
                        f"Artikl {item.artikl_id} nema rm_id (ProductId)."
                    )
                    continue
                unit_name = item.unit.name if item.unit else ""
                product_name = item.artikl.name or ""
                product_name = product_name.upper()
                items.append(
                    {
                        "ProductId": item.artikl.rm_id,
                        "ProductName": product_name,
                        "Quantity": float(item.quantity),
                        "UnitName": unit_name,
                        "_selection_8": True,
                    }
                )

            if not items:
                if item_errors:
                    transfer.last_error = _format_remaris_error(
                        {
                            "success": False,
                            "message": "Validation error",
                            "errors": item_errors,
                        }
                    )
                    transfer.last_synced_at = timezone.now()
                    transfer.status = WarehouseTransfer.Status.FAILED
                    transfer.save(update_fields=["last_error", "last_synced_at", "status"])
                    failed += 1
                    continue
                skipped += 1
                continue

            transfer_date = transfer.date
            if timezone.is_naive(transfer_date):
                transfer_date = timezone.make_aware(
                    transfer_date, timezone.get_current_timezone()
                )
            transfer_date = transfer_date.astimezone(datetime.timezone.utc)
            payload = {
                "id": transfer.remaris_id,
                "warehouseItems": items,
                "date": transfer_date.isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                ),
                "warehouseFromId": str(transfer.from_warehouse_id),
                "warehouseId": str(transfer.to_warehouse_id),
                "dontChangeInventoryQuantity": transfer.dont_change_inventory_quantity,
            }

            try:
                response = connector.post_json(
                    "WarehouseTransfer/EditPost",
                    payload,
                    referer_path="/WarehouseTransfer",
                )
            except requests.exceptions.RequestException as exc:
                response_text = None
                status_code = None
                if getattr(exc, "response", None) is not None:
                    response_text = exc.response.text
                    status_code = exc.response.status_code
                transfer.last_error = _format_remaris_error(
                    {
                        "success": False,
                        "message": "HTTP error from Remaris",
                        "status_code": status_code,
                        "response_text": response_text,
                        "payload": payload,
                    }
                )
                transfer.last_synced_at = timezone.now()
                transfer.status = WarehouseTransfer.Status.FAILED
                transfer.save(update_fields=["last_error", "last_synced_at", "status"])
                failed += 1
                continue

            if response.get("success") is True:
                transfer.remaris_id = response.get("warehouseTransferId")
                transfer.last_error = ""
                transfer.last_synced_at = timezone.now()
                transfer.status = WarehouseTransfer.Status.SENT
                transfer.save(
                    update_fields=["remaris_id", "last_error", "last_synced_at", "status"]
                )
                if had_remaris_id:
                    updated += 1
                else:
                    created += 1
            else:
                transfer.last_error = _format_remaris_error(
                    {
                        "success": False,
                        "message": "Remaris returned error",
                        "response": response,
                        "payload_debug": json.loads(
                            _format_transfer_payload_debug(transfer, items, payload)
                        ),
                    }
                )
                transfer.last_synced_at = timezone.now()
                transfer.status = WarehouseTransfer.Status.FAILED
                transfer.save(update_fields=["last_error", "last_synced_at", "status"])
                failed += 1

    modeladmin.message_user(
        request,
        "Send complete. created={created} updated={updated} skipped={skipped} failed={failed}".format(
            created=created,
            updated=updated,
            skipped=skipped,
            failed=failed,
        ),
        level=messages.SUCCESS if failed == 0 else messages.WARNING,
    )


@admin.action(description="Import skladista from Remaris", permissions=["change"])
def import_warehouse_ids(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    payload = {
        "sort": "Name asc",
        "page": 0,
        "perpage": None,
        "AppContext": {
            "OrganizationId": 2,
            "LocationId": 5,
            "WarehouseId": 4,
            "RegimeId": None,
            "PriceListId": None,
            "ContactId": None,
            "DiscountId": None,
            "SalesGroupId": None,
            "ProductTags": None,
            "FiscalPaymentTypes": None,
            "SelectedCustomerIds": None,
            "PosId": None,
            "ShowFilter": 20,
            "ShowDateRange": None,
            "DateFrom": None,
            "DateTo": None,
            "OnDate": None,
            "Year": None,
            "ReportYear": None,
            "ReportMonth": None,
            "CustomerId": None,
            "WaiterId": None,
            "PdvIraReportType": None,
            "TableTotalType": 0,
            "IncludeInvoices": False,
            "IncludeDeliveryNotes": False,
            "IncludeArchivedTables": False,
            "IncludeOpenOrders": False,
            "IncludeHotelOrders": False,
            "GroupByDiscountValue": False,
            "Billed": False,
            "NonBilled": False,
            "ShowInitialCustomer": False,
            "IncludeCanceled": False,
            "IncludeCancels": False,
            "WithBuyerOnly": False,
            "WithDiscountOnly": False,
            "LoginLogoutInvoice": 0,
            "PDV2014Margin": False,
            "AllBaseGroups": True,
            "ProductBaseGroupIds": None,
            "AllWarehouseOperationDocumentTypes": True,
            "WarehouseOperationDocumentTypes": None,
            "ProductId": None,
            "OrderCancelReasonId": None,
            "PointOfIssueId": None,
            "PaymentMethodId": None,
            "SupplyerId": None,
            "HotelGuestOrders": False,
            "HotelReceptionOrders": False,
            "NoGrouping": False,
            "NoProduction": False,
            "TableNumber": None,
            "TextSearch": None,
            "ByPaymentFilter": 0,
            "NotPayedByDate": None,
            "Currency": None,
            "IncludePivot": False,
        },
    }

    response = connector.post_json(
        "WarehouseLocation/GetLocationWarehouses?locationId=5",
        payload,
        referer_path="/WarehouseLocation",
    )

    if isinstance(response, list):
        data = response
    else:
        data = response.get("data", [])

    created = 0
    updated = 0
    skipped = 0

    with transaction.atomic():
        for item in data:
            rm_id = item.get("Id")
            if rm_id is None:
                skipped += 1
                continue

            defaults = {
                "name": item.get("Name", ""),
                "hidden": bool(item.get("Hidden", False)),
                "ordinal": item.get("Ordinal"),
            }

            _, was_created = WarehouseId.objects.update_or_create(
                rm_id=rm_id,
                defaults=defaults,
            )
            if was_created:
                created += 1
            else:
                updated += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


@admin.action(
    description="Create međuskladišnica for inventory shortage",
    permissions=["change"],
)
def create_transfer_for_inventory_shortage(modeladmin, request, queryset):
    target_warehouse_id = 8
    created = 0
    skipped = 0
    missing = 0

    if not WarehouseId.objects.filter(rm_id=target_warehouse_id).exists():
        modeladmin.message_user(
            request,
            f"Target warehouse_id {target_warehouse_id} not found.",
            level=messages.ERROR,
        )
        return

    warehouse_ids = [
        warehouse_id
        for warehouse_id in queryset.values_list("warehouse_id", flat=True).distinct()
        if warehouse_id
    ]
    if warehouse_ids:
        warehouses = WarehouseId.objects.filter(rm_id__in=warehouse_ids)
        missing_ids = set(warehouse_ids) - set(
            warehouses.values_list("rm_id", flat=True)
        )
        if missing_ids:
            modeladmin.message_user(
                request,
                "WarehouseId missing for: {ids}".format(
                    ids=", ".join(str(value) for value in sorted(missing_ids))
                ),
                level=messages.WARNING,
            )
        if warehouses.exists():
            if not _import_warehouse_stock_for_warehouses(
                modeladmin,
                request,
                warehouses,
            ):
                return

    with transaction.atomic():
        for inventory in queryset.select_related("warehouse").prefetch_related(
            "items__artikl",
            "items__unit",
        ):
            if not inventory.warehouse_id:
                skipped += 1
                continue

            shortage_note = (
                "Inventura manjak: inventory_id={id}, inventory_date={date}".format(
                    id=inventory.id,
                    date=inventory.date.strftime("%Y-%m-%d %H:%M"),
                )
            )
            overage_note = (
                "Inventura visak: inventory_id={id}, inventory_date={date}".format(
                    id=inventory.id,
                    date=inventory.date.strftime("%Y-%m-%d %H:%M"),
                )
            )

            shortage_transfer = WarehouseTransfer.objects.create(
                from_warehouse_id=inventory.warehouse_id,
                to_warehouse_id=target_warehouse_id,
                date=inventory.date,
                created_by=request.user,
                note=shortage_note,
            )
            overage_transfer = WarehouseTransfer.objects.create(
                from_warehouse_id=target_warehouse_id,
                to_warehouse_id=inventory.warehouse_id,
                date=inventory.date,
                created_by=request.user,
                note=overage_note,
            )

            shortage_items_created = 0
            overage_items_created = 0
            has_items = False
            for item in inventory.items.all():
                if not item.artikl_id or item.quantity is None:
                    continue
                has_items = True

                stock_row = WarehouseStock.objects.filter(
                    warehouse_id_id=inventory.warehouse_id,
                    product_id=item.artikl_id,
                ).first()
                stock_qty = stock_row.quantity if stock_row else Decimal("0")
                diff_qty = stock_qty - item.quantity

                if diff_qty > 0:
                    WarehouseTransferItem.objects.create(
                        transfer=shortage_transfer,
                        artikl_id=item.artikl_id,
                        quantity=diff_qty,
                        unit=item.unit,
                    )
                    shortage_items_created += 1
                elif diff_qty < 0:
                    WarehouseTransferItem.objects.create(
                        transfer=overage_transfer,
                        artikl_id=item.artikl_id,
                        quantity=abs(diff_qty),
                        unit=item.unit,
                    )
                    overage_items_created += 1

            if shortage_items_created == 0:
                shortage_transfer.delete()
            if overage_items_created == 0:
                overage_transfer.delete()

            if shortage_items_created == 0 and overage_items_created == 0:
                if has_items:
                    inventory.status = Inventory.Status.CLOSED
                    inventory.save(update_fields=["status"])
                missing += 1
                continue

            inventory.status = Inventory.Status.CLOSED
            inventory.save(update_fields=["status"])
            created += 1

    modeladmin.message_user(
        request,
        "Create transfer complete. created={created} skipped={skipped} no_items={missing}".format(
            created=created,
            skipped=skipped,
            missing=missing,
        ),
        level=messages.SUCCESS if created else messages.WARNING,
    )


@admin.register(WarehouseStock)
class WarehouseStockAdmin(admin.ModelAdmin):
    list_display = (
        "warehouse_id",
        "wh_id",
        "product",
        "product_code",
        "product_name",
        "unit",
        "quantity",
        "base_group_name",
        "active",
    )
    search_fields = ("product__name", "product_code", "product_name", "base_group_name", "unit")
    list_filter = ("warehouse_id", "active", "base_group_name", "unit")
    actions = [import_warehouse_stock]


@admin.register(ProductStockDS)
class ProductStockDSAdmin(admin.ModelAdmin):
    list_display = (
        "rm_id",
        "product",
        "product_code",
        "quantity",
        "unit_of_measure",
        "input_value",
        "base_group_name",
    )
    search_fields = ("product", "product_code", "base_group_name")
    actions = [import_product_stock]

    def response_action(self, request, queryset):
        action = request.POST.get("action")
        if action == "import_product_stock":
            func = self.get_actions(request)[action][0]
            return func(self, request, ProductStockDS.objects.all())
        return super().response_action(request, queryset)


@admin.register(WarehouseId)
class WarehouseIdAdmin(admin.ModelAdmin):
    change_list_template = "admin/stock/warehouseid/change_list.html"
    list_display = ("rm_id", "name", "hidden", "ordinal")
    search_fields = ("rm_id", "name")
    actions = [import_warehouse_ids, import_warehouse_stock_for_warehouses]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "sync-remaris/",
                self.admin_site.admin_view(self.sync_remaris),
                name="stock_warehouseid_sync_remaris",
            ),
        ]
        return custom_urls + urls

    def sync_remaris(self, request):
        func = self.get_actions(request)["import_warehouse_ids"][0]
        func(self, request, WarehouseId.objects.all())
        return HttpResponseRedirect(reverse("admin:stock_warehouseid_changelist"))

    def response_action(self, request, queryset):
        action = request.POST.get("action")
        if action == "import_warehouse_ids":
            func = self.get_actions(request)[action][0]
            return func(self, request, WarehouseId.objects.all())
        if action == "import_warehouse_stock_for_warehouses":
            func = self.get_actions(request)[action][0]
            return func(self, request, WarehouseId.objects.all())
        return super().response_action(request, queryset)


class InventoryItemInline(admin.TabularInline):
    model = InventoryItem
    extra = 0
    fields = ("artikl", "quantity", "unit", "note")
    autocomplete_fields = ("artikl",)


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ("id", "warehouse", "date", "status", "created_by")
    search_fields = ("warehouse__name", "created_by__username")
    list_filter = ("status", "warehouse")
    readonly_fields = ("created_by", "status")
    fields = ("warehouse", "date", "status", "created_by")
    actions = [create_transfer_for_inventory_shortage]
    inlines = [InventoryItemInline]

    def save_model(self, request, obj, form, change):
        if change:
            if obj.created_by_id:
                obj.created_by_id = Inventory.objects.values_list(
                    "created_by_id",
                    flat=True,
                ).get(pk=obj.pk)
            else:
                obj.created_by = request.user
        else:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class WarehouseTransferItemInline(admin.TabularInline):
    model = WarehouseTransferItem
    extra = 0
    fields = ("artikl", "quantity", "unit")
    autocomplete_fields = ("artikl",)


@admin.register(WarehouseTransfer)
class WarehouseTransferAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "from_warehouse",
        "to_warehouse",
        "date",
        "status",
        "created_by",
        "remaris_id",
        "last_synced_at",
    )
    search_fields = (
        "from_warehouse__name",
        "to_warehouse__name",
        "created_by__username",
        "remaris_id",
    )
    readonly_fields = ("created_by", "remaris_id", "last_synced_at", "last_error", "status")
    list_filter = ("status", "from_warehouse", "to_warehouse")
    fields = (
        "from_warehouse",
        "to_warehouse",
        "date",
        "dont_change_inventory_quantity",
        "note",
        "status",
        "created_by",
        "remaris_id",
        "last_synced_at",
        "last_error",
    )
    inlines = [WarehouseTransferItemInline]
    actions = [send_warehouse_transfer_to_remaris]

    def save_model(self, request, obj, form, change):
        if change:
            if obj.created_by_id:
                obj.created_by_id = WarehouseTransfer.objects.values_list(
                    "created_by_id",
                    flat=True,
                ).get(pk=obj.pk)
            else:
                obj.created_by = request.user
        else:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class StockMoveLineInline(admin.TabularInline):
    model = StockMoveLine
    extra = 0
    fields = ("warehouse", "artikl", "quantity", "unit_cost", "source_item")
    autocomplete_fields = ("artikl", "warehouse")


@admin.register(StockMove)
class StockMoveAdmin(admin.ModelAdmin):
    list_display = ("id", "move_type", "date", "reference")
    list_filter = ("move_type",)
    search_fields = ("reference",)
    inlines = [StockMoveLineInline]


@admin.register(StockMoveLine)
class StockMoveLineAdmin(admin.ModelAdmin):
    list_display = ("id", "move", "warehouse", "artikl", "quantity", "unit_cost", "source_item")
    list_filter = ("move__move_type", "warehouse", "artikl")
    search_fields = ("artikl__name", "artikl__code", "move__reference")
    raw_id_fields = ("move", "warehouse", "artikl", "source_item")


@admin.register(ReplenishRequestLine)
class ReplenishRequestLineAdmin(admin.ModelAdmin):
    list_display = ("id", "artikl", "quantity", "created_at")
    search_fields = ("artikl__name", "artikl__code")
    autocomplete_fields = ("artikl",)
    actions = ["execute_replenish"]

    @admin.action(description="Izvrsi transfer (replenish)", permissions=["change"])
    def execute_replenish(self, request, queryset):
        lines = []
        for line in queryset.select_related("artikl"):
            if not line.artikl_id:
                continue
            lines.append({"artikl": line.artikl, "quantity": line.quantity})

        if not lines:
            self.message_user(request, "Nema stavki za transfer.", level=messages.WARNING)
            return

        try:
            move = replenish_to_sale_warehouse(lines=lines)
        except Exception as exc:
            self.message_user(request, f"Transfer nije uspio: {exc}", level=messages.ERROR)
            return

        self.message_user(
            request,
            f"Transfer kreiran (ID: {move.id}).",
            level=messages.SUCCESS,
        )


@admin.register(StockLot)
class StockLotAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "warehouse",
        "artikl",
        "received_at",
        "unit_cost",
        "qty_in",
        "qty_remaining",
        "source_item",
    )
    list_filter = ("warehouse", "artikl")
    search_fields = ("artikl__name", "artikl__code")


@admin.register(StockAllocation)
class StockAllocationAdmin(admin.ModelAdmin):
    list_display = ("id", "move_line", "lot", "qty", "unit_cost")
    list_filter = ("lot__warehouse", "lot__artikl")
    search_fields = ("lot__artikl__name", "lot__artikl__code")
    raw_id_fields = ("move_line", "lot")


@admin.register(StockAccountingConfig)
class StockAccountingConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "inventory_account",
        "cogs_account",
        "default_sale_warehouse",
        "default_purchase_warehouse",
        "default_replenish_from_warehouse",
        "auto_replenish_on_sale",
        "default_cash_account",
        "default_deposit_account",
    )
    autocomplete_fields = (
        "inventory_account",
        "cogs_account",
        "default_sale_warehouse",
        "default_purchase_warehouse",
        "default_replenish_from_warehouse",
        "default_cash_account",
        "default_deposit_account",
    )

    def has_add_permission(self, request):
        return not StockAccountingConfig.objects.exists()

    @admin.action(description="Replenish Glavno -> Sank", permissions=["change"])
    def replenish_to_sale(self, request, queryset):
        try:
            replenish_to_sale_warehouse(lines=[])
        except Exception as exc:
            self.message_user(request, f"Replenish nije uspio: {exc}", level=messages.ERROR)

    actions = ["replenish_to_sale"]
