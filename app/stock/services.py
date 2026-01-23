import logging

from django.db import transaction

from artikli.models import Artikl
from artikli.remaris_connector import RemarisConnector
from stock.models import WarehouseId, WarehouseStock

logger = logging.getLogger(__name__)


def refresh_warehouse_stock_for_product_code(product_code: str) -> None:
    if not product_code:
        return

    connector = RemarisConnector()
    connector.login()

    warehouse_ids = list(WarehouseId.objects.values_list("rm_id", flat=True))
    if not warehouse_ids:
        return

    product = Artikl.objects.filter(code=product_code).first()

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
                if item.get("productCode", "") != product_code:
                    continue

                wh_id = item.get("id")
                if wh_id is None:
                    continue

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
                WarehouseStock.objects.update_or_create(wh_id=wh_id, defaults=defaults)

    logger.info("Warehouse stock refreshed for product_code=%s", product_code)
