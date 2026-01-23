from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.remaris_connector import RemarisConnector
from artikli.models import Artikl
from stock.models import WarehouseStock


class Command(BaseCommand):
    help = "Import warehouse stock from Remaris"

    def add_arguments(self, parser):
        parser.add_argument(
            "--warehouse-id",
            type=int,
            default=6,
            help="WarehouseId to import",
        )

    def handle(self, *args, **options):
        connector = RemarisConnector()
        connector.login()
        warehouse_id = options["warehouse_id"]

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

        created = 0
        updated = 0
        skipped = 0

        with transaction.atomic():
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
                    "warehouse_id_id": warehouse_id,
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

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete. created={created} updated={updated} skipped={skipped}"
            )
        )
