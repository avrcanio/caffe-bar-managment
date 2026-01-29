import html
import os
import re
from dataclasses import dataclass
from datetime import date as date_cls, datetime as datetime_cls
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

import xlrd
from django.db import transaction
from django.utils import timezone

from artikli.remaris_connector import RemarisConnector
from sales.models import SalesInvoice, SalesInvoiceItem
from artikli.models import Artikl


@dataclass
class SalesItemRow:
    product_name: str
    quantity: Decimal
    amount: Decimal
    discount_value: Decimal | None
    discount_percent: Decimal | None


@dataclass
class SalesInvoiceRow:
    rm_number: int
    issued_on: date_cls
    issued_at: datetime_cls
    location_name: str
    buyer_name: str
    waiter_name: str
    total_amount: Decimal
    currency: str
    items: list[SalesItemRow]


def _format_remaris_date(value: date_cls) -> str:
    return f"{value.day}.{value.month}.{value.year}."


def _safe_decimal(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


TWOPLACES = Decimal("0.01")
VAT_RATE = Decimal("0.25")


def _q2(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _compute_net_vat(total_amount: Decimal) -> tuple[Decimal, Decimal]:
    if total_amount is None:
        total_amount = Decimal("0.00")
    net = total_amount / (Decimal("1.00") + VAT_RATE)
    net = _q2(net)
    vat = _q2(total_amount - net)
    return net, vat


def _safe_text(value) -> str:
    return str(value or "").strip()


def _excel_datetime(value, datemode):
    if value in ("", None):
        return None
    if isinstance(value, (int, float)):
        return xlrd.xldate.xldate_as_datetime(value, datemode)
    return None


def _parse_sales_report(path: Path) -> list[SalesInvoiceRow]:
    book = xlrd.open_workbook(path.as_posix())
    sheet = book.sheet_by_index(0)
    invoices: list[SalesInvoiceRow] = []
    row_idx = 0

    while row_idx < sheet.nrows:
        row = sheet.row_values(row_idx)
        if len(row) > 1 and _safe_text(row[1]) == "Račun:":
            rm_number = int(row[3]) if row[3] not in ("", None) else None
            issued_on_dt = _excel_datetime(row[8], book.datemode)

            row_dt = sheet.row_values(row_idx + 1) if row_idx + 1 < sheet.nrows else []
            issued_at_dt = _excel_datetime(row_dt[3] if len(row_dt) > 3 else None, book.datemode)
            waiter_name = _safe_text(row_dt[8] if len(row_dt) > 8 else "")

            row_buyer = sheet.row_values(row_idx + 2) if row_idx + 2 < sheet.nrows else []
            buyer_name = _safe_text(row_buyer[3] if len(row_buyer) > 3 else "")
            location_name = _safe_text(row_buyer[8] if len(row_buyer) > 8 else "")

            row_idx += 4
            items: list[SalesItemRow] = []
            total_amount = Decimal("0")

            while row_idx < sheet.nrows:
                item_row = sheet.row_values(row_idx)
                if len(item_row) > 6 and _safe_text(item_row[6]) == "Ukupno:":
                    total_amount = _safe_decimal(item_row[8] if len(item_row) > 8 else 0)
                    row_idx += 1
                    break

                product_name = _safe_text(item_row[1] if len(item_row) > 1 else "")
                if product_name:
                    quantity = _safe_decimal(item_row[6] if len(item_row) > 6 else 0)
                    amount = _safe_decimal(item_row[8] if len(item_row) > 8 else 0)
                    discount_value = item_row[4] if len(item_row) > 4 else None
                    discount_percent = item_row[5] if len(item_row) > 5 else None
                    items.append(
                        SalesItemRow(
                            product_name=product_name,
                            quantity=quantity,
                            amount=amount,
                            discount_value=(
                                _safe_decimal(discount_value)
                                if discount_value not in ("", None)
                                else None
                            ),
                            discount_percent=(
                                _safe_decimal(discount_percent)
                                if discount_percent not in ("", None)
                                else None
                            ),
                        )
                    )
                row_idx += 1

            if rm_number is not None and issued_on_dt and issued_at_dt:
                invoices.append(
                    SalesInvoiceRow(
                        rm_number=rm_number,
                        issued_on=issued_on_dt.date(),
                        issued_at=issued_at_dt,
                        location_name=location_name,
                        buyer_name=buyer_name,
                        waiter_name=waiter_name,
                        total_amount=total_amount,
                        currency="",
                        items=items,
                    )
                )
            continue

        row_idx += 1

    return invoices


def _download_report_excel(
    connector: RemarisConnector,
    date_from: date_cls,
    date_to: date_cls,
    organization_id: int,
    location_id: int,
    pos_id: int,
    currency: str,
    warehouse_id: int | None = None,
) -> Path:
    url = (
        "Reports/DateRangeXReport?ActionName=GetInvoices&ControllerName=ActionReports"
        "&ContextType=LocationWaiterCustomer&ContextFilterType=OrganizationLocationPos"
        "&Year=False&ManagerPermissionName=Pregled%20ra%C4%8Duna"
        "&ManagerPermissionType=Print&ShowPivot=False"
    )

    payload = {
        "IsGlobal": "False",
        "TypeName": "AppContextLocationWaiterCustomer",
        "Context": {
            "OrganizationId": str(organization_id),
            "LocationId": str(location_id),
            "PosId": str(pos_id),
            "ShowDateRange": "True",
            "DateFrom": _format_remaris_date(date_from),
            "DateTo": _format_remaris_date(date_to),
            "Currency": currency,
            "IncludeCanceled": False,
            "IncludeCancels": False,
            "WithBuyerOnly": False,
            "WithDiscountOnly": False,
            "ContactId": None,
            "SelectedCustomerIds": [],
            "PaymentMethodId": None,
        },
        "ChoosenContextFilterType": "Location",
        "DocumentTypeFilter": "Excel",
        "Email": None,
        "SendEmail": False,
        "submitCommand": "_save_",
        "ControllerName": "ActionReports",
        "ActionName": "GetInvoices",
        "RenderButtons": "True",
        "ContextFilterType": "OrganizationLocationPos",
        "ObjectId": "0",
        "Year": False,
        "AppContext": {
            "OrganizationId": organization_id,
            "LocationId": location_id,
            "WarehouseId": warehouse_id,
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
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/html,*/*",
        "X-Requested-With": "XMLHttpRequest",
        "ajax-request": "AJAX-REQUEST",
        "Origin": connector.base_url,
        "Referer": connector.base_url + "/Reports/DateRangeXReport",
    }

    response = connector.session.post(
        connector.base_url + "/" + url,
        json=payload,
        headers=headers,
    )
    response.raise_for_status()

    match = re.search(r"window\.open\('([^']+)'", response.text)
    if not match:
        raise ValueError("Remaris report did not return download URL.")

    download_path = html.unescape(match.group(1))
    download_url = connector.base_url + download_path
    download_response = connector.session.get(download_url)
    download_response.raise_for_status()

    tmp = NamedTemporaryFile(delete=False, suffix=".xls")
    tmp.write(download_response.content)
    tmp.close()
    return Path(tmp.name)


def import_sales_invoices(
    date_from: date_cls,
    date_to: date_cls,
    organization_id: int,
    location_id: int,
    pos_id: int,
    currency: str,
    warehouse_id: int | None = None,
) -> tuple[int, int, int]:
    connector = RemarisConnector()
    connector.login()

    report_path = _download_report_excel(
        connector,
        date_from=date_from,
        date_to=date_to,
        organization_id=organization_id,
        location_id=location_id,
        pos_id=pos_id,
        currency=currency,
        warehouse_id=warehouse_id,
    )

    invoices = _parse_sales_report(report_path)
    created = 0
    updated = 0
    skipped = 0

    tz = timezone.get_current_timezone()

    with transaction.atomic():
        for invoice in invoices:
            issued_at = invoice.issued_at
            if timezone.is_naive(issued_at):
                issued_at = timezone.make_aware(issued_at, tz)

            defaults = {
                "issued_at": issued_at,
                "location_name": invoice.location_name,
                "buyer_name": invoice.buyer_name,
                "waiter_name": invoice.waiter_name,
                "total_amount": invoice.total_amount,
                "currency": currency,
                "organization_id": organization_id,
                "location_id": location_id,
                "pos_id": pos_id,
            }
            net_amount, vat_amount = _compute_net_vat(invoice.total_amount)

            obj, was_created = SalesInvoice.objects.update_or_create(
                rm_number=invoice.rm_number,
                defaults={
                    **defaults,
                    "issued_on": invoice.issued_on,
                    "net_amount": net_amount,
                    "vat_amount": vat_amount,
                },
            )

            obj.items.all().delete()
            product_names = {it.product_name for it in invoice.items if it.product_name}
            artikl_map = {
                a.name: a.id
                for a in Artikl.objects.filter(name__in=product_names)
            }
            SalesInvoiceItem.objects.bulk_create(
                [
                    SalesInvoiceItem(
                        invoice=obj,
                        artikl_id=artikl_map.get(item.product_name),
                        product_name=item.product_name,
                        quantity=item.quantity,
                        amount=item.amount,
                        discount_value=item.discount_value,
                        discount_percent=item.discount_percent,
                    )
                    for item in invoice.items
                ]
            )

            if was_created:
                created += 1
            else:
                updated += 1

    return created, updated, skipped


def load_import_defaults() -> dict:
    return {
        "organization_id": int(os.getenv("REMARIS_REPORT_ORG_ID", "2")),
        "location_id": int(os.getenv("REMARIS_REPORT_LOCATION_ID", "5")),
        "pos_id": int(os.getenv("REMARIS_REPORT_POS_ID", "6")),
        "currency": os.getenv("REMARIS_REPORT_CURRENCY", "EUR"),
        "warehouse_id": int(os.getenv("REMARIS_REPORT_WAREHOUSE_ID", "4")),
    }
