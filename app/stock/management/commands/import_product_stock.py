from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.remaris_connector import RemarisConnector
from stock.models import ProductStockDS


class Command(BaseCommand):
    help = "Import product stock from Remaris"

    def handle(self, *args, **options):
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

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete. created={created} updated={updated} skipped={skipped}"
            )
        )
