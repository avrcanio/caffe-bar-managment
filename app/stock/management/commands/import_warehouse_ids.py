from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.remaris_connector import RemarisConnector
from stock.models import WarehouseId


class Command(BaseCommand):
    help = "Import warehouses from Remaris"

    def handle(self, *args, **options):
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

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete. created={created} updated={updated} skipped={skipped}"
            )
        )
