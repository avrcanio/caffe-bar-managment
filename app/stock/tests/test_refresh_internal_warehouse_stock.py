from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl
from stock.models import StockLot, WarehouseId, WarehouseStock
from stock.services import refresh_internal_warehouse_stock


class RefreshInternalWarehouseStockTests(TestCase):
    def setUp(self):
        # Use high rm_id values to avoid collisions with any seeded/fixture data.
        self.warehouse = WarehouseId.objects.create(rm_id=9001, name="Sank")
        self.artikl = Artikl.objects.create(
            rm_id=9010,
            code="5010327755014",
            name="Gin Hendricks 0,7 l",
            is_stock_item=True,
        )

    def test_merges_fallback_row_into_remaris_row(self):
        StockLot.objects.create(
            warehouse=self.warehouse,
            artikl=self.artikl,
            received_at=timezone.now(),
            unit_cost=Decimal("34.1300"),
            qty_in=Decimal("3.0000"),
            qty_remaining=Decimal("3.0000"),
        )

        # Internal-only fallback row created before Remaris row exists.
        WarehouseStock.objects.create(
            wh_id=None,
            warehouse_id=self.warehouse,
            product=self.artikl,
            product_name=self.artikl.name,
            product_code=self.artikl.code,
            unit="",
            quantity=Decimal("0.0000"),
            internal_quantity=Decimal("3.0000"),
            internal_avg_cost=Decimal("34.1300"),
            internal_updated_at=timezone.now(),
            base_group_name="",
            active=True,
        )
        # Remaris-backed row (wh_id present) that should become the single row.
        WarehouseStock.objects.create(
            wh_id=520,
            warehouse_id=self.warehouse,
            product=self.artikl,
            product_name=self.artikl.name,
            product_code=self.artikl.code,
            unit="Komad",
            quantity=Decimal("3.0000"),
            internal_quantity=None,
            internal_avg_cost=None,
            internal_updated_at=None,
            base_group_name="Strana zestoka",
            active=True,
        )

        refresh_internal_warehouse_stock(
            warehouse_ids=[self.warehouse.rm_id],
            artikl_ids=[self.artikl.rm_id],
        )

        rows = list(
            WarehouseStock.objects.filter(warehouse_id=self.warehouse, product=self.artikl).order_by("id")
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].wh_id, 520)
        self.assertEqual(rows[0].quantity, Decimal("3.0000"))
        self.assertEqual(rows[0].internal_quantity, Decimal("3.0000"))
        self.assertEqual(rows[0].internal_avg_cost, Decimal("34.1300"))
