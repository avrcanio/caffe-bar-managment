from decimal import Decimal

from artikli.remaris_connector import RemarisConnector
from sales.models import SalesPriceItem

DEFAULT_REMARIS_PRICE_LIST_ID = 10
DEFAULT_TRANSFER_IDS = [11, 20]
DEFAULT_ONLY_CHANGED_ITEMS = True
DEFAULT_TRANSFER_APP_CONTEXT = {
    "OrganizationId": 2,
    "LocationId": 5,
    "WarehouseId": None,
    "RegimeId": None,
    "PriceListId": None,
    "ContactId": None,
    "DiscountId": None,
    "SalesGroupId": None,
    "ProductTags": None,
    "FiscalPaymentTypes": None,
    "SelectedCustomerIds": None,
    "PosId": None,
    "ShowFilter": None,
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
}


def resolve_remaris_product_id(*, artikl, detail=None) -> int | None:
    if artikl and artikl.rm_id:
        return int(artikl.rm_id)
    if detail is None and artikl:
        detail = getattr(artikl, "detail", None)
    if detail and detail.rm_id:
        return int(detail.rm_id)
    return None


def build_save_price_payload(
    *,
    product_id: int,
    price_value: Decimal,
    remaris_price_list_id: int,
    artikl,
    detail=None,
    is_active: bool = True,
) -> dict:
    if detail is None and artikl:
        detail = getattr(artikl, "detail", None)
    product_code = artikl.code or (detail.code if detail else "") if artikl else ""
    product_name = artikl.name or (detail.name if detail else "") if artikl else ""
    sales_group_name = ""
    keyboard_group_name = ""
    product_ordinal = None
    if detail:
        if detail.sales_group_id and detail.sales_group:
            sales_group_name = detail.sales_group.name or ""
        if detail.keyboard_group_id and detail.keyboard_group:
            keyboard_group_name = detail.keyboard_group.name or ""
        product_ordinal = detail.ordinal

    return {
        "dataSource": "productsDs",
        "operationType": "update",
        "textMatchStyle": "exact",
        "componentId": "isc_ListGrid_0",
        "data": {
            "productId": int(product_id),
            "price": float(price_value),
        },
        "oldValues": {
            "priceListId": remaris_price_list_id,
            "productId": int(product_id),
            "productName": product_name,
            "productCode": product_code or "",
            "salesGroupName": sales_group_name,
            "price": float(price_value),
            "enabled": bool(is_active),
            "priceActive": bool(is_active),
            "isPackage": False,
            "isUserPriceAllowed": False,
            "keyboardGroup": keyboard_group_name,
            "hideOnline": False,
            "hideSelfOrdering": False,
            "salesGroupOrdinal": None,
            "productOrdinal": float(product_ordinal) if product_ordinal is not None else None,
            "groupParentId": None,
            "name": None,
            "isFolder": None,
        },
    }


def save_remaris_product_price(
    connector: RemarisConnector,
    *,
    product_id: int,
    price_value: Decimal,
    remaris_price_list_id: int,
    artikl,
    detail=None,
    is_active: bool = True,
    dry_run: bool = False,
    write_line=None,
    context_label: str = "",
) -> bool:
    payload = build_save_price_payload(
        product_id=product_id,
        price_value=price_value,
        remaris_price_list_id=remaris_price_list_id,
        artikl=artikl,
        detail=detail,
        is_active=is_active,
    )

    if dry_run:
        if write_line:
            write_line(
                f"DRY RUN {context_label} productId={product_id} price={price_value}"
            )
        return True

    try:
        response = connector.post_json(
            "PriceList/SavePrice?isc_dataFormat=json",
            payload,
            referer_path="/PriceList",
        )
    except Exception as exc:
        if write_line:
            write_line(f"ERROR {context_label} productId={product_id} err={exc}")
        return False

    status = response.get("response", {}).get("status")
    if status not in (0, "0", None):
        if write_line:
            write_line(f"ERROR {context_label} productId={product_id} status={status}")
        return False

    if write_line:
        write_line(f"OK {context_label} productId={product_id} price={price_value}")
    return True


def sync_sales_pricelist_to_remaris(
    *,
    price_list,
    remaris_price_list_id: int | None = None,
    include_inactive: bool = False,
    dry_run: bool = False,
    write_line=None,
):
    qs = (
        SalesPriceItem.objects.filter(price_list=price_list)
        .select_related(
            "artikl",
            "artikl__detail",
            "artikl__detail__sales_group",
            "artikl__detail__keyboard_group",
        )
        .order_by("id")
    )
    if not include_inactive:
        qs = qs.filter(is_active=True)

    remaris_price_list_id = (
        remaris_price_list_id
        if remaris_price_list_id is not None
        else DEFAULT_REMARIS_PRICE_LIST_ID
    )

    connector = RemarisConnector()
    if not dry_run:
        connector.login()

    sent = 0
    skipped = 0
    errors = 0

    for item in qs:
        artikl = item.artikl
        detail = getattr(artikl, "detail", None) if artikl else None
        product_id = resolve_remaris_product_id(artikl=artikl, detail=detail)

        if not artikl or not product_id:
            skipped += 1
            if write_line:
                write_line(
                    f"SKIP item_id={item.id} missing product_id (artikl_id={item.artikl_id})"
                )
            continue

        price_value = Decimal(item.unit_price_gross)
        context_label = f"item_id={item.id}"

        if dry_run:
            sent += 1
            if write_line:
                write_line(
                    f"DRY RUN {context_label} productId={product_id} price={price_value}"
                )
            continue

        ok = save_remaris_product_price(
            connector,
            product_id=product_id,
            price_value=price_value,
            remaris_price_list_id=remaris_price_list_id,
            artikl=artikl,
            detail=detail,
            is_active=bool(item.is_active),
            dry_run=False,
            write_line=write_line,
            context_label=context_label,
        )
        if ok:
            sent += 1
        else:
            errors += 1

    return sent, skipped, errors


def transfer_sales_prices_to_pos(
    *,
    transfer_ids=None,
    only_changed_items: bool | None = None,
):
    payload = {
        "ids": transfer_ids if transfer_ids is not None else DEFAULT_TRANSFER_IDS,
        "onlyChangedItems": (
            only_changed_items
            if only_changed_items is not None
            else DEFAULT_ONLY_CHANGED_ITEMS
        ),
        "AppContext": DEFAULT_TRANSFER_APP_CONTEXT,
    }

    connector = RemarisConnector()
    connector.login()
    return connector.post_json(
        "DataTransfer/Transfer",
        payload,
        referer_path="/DataTransfer",
    )
