from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from artikli.models import Artikl
from stock.admin import create_transfer_for_inventory_shortage
from stock.models import Inventory, InventoryItem, StockMove, WarehouseId, WarehouseStock, WarehouseTransfer


class _DummyAdmin:
    def message_user(self, request, message, level=None):
        return None


class InventoryShortageAdminActionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
        )
        self.factory = RequestFactory()
        self.modeladmin = _DummyAdmin()

        self.inventory_warehouse = WarehouseId.objects.create(rm_id=6, name="Glavno")
        self.target_warehouse = WarehouseId.objects.create(rm_id=8, name="Otpis")
        self.artikl = Artikl.objects.create(rm_id=1335, name="Test Artikl")

    def _request(self):
        request = self.factory.post("/admin/stock/inventory/")
        request.user = self.user
        return request

    @patch("stock.admin._import_warehouse_stock_for_warehouses", return_value=True)
    def test_action_uses_internal_quantity_for_diff(self, _mock_import):
        inventory = Inventory.objects.create(
            warehouse=self.inventory_warehouse,
            date=timezone.now(),
            status=Inventory.Status.OPEN,
            created_by=self.user,
        )
        InventoryItem.objects.create(
            inventory=inventory,
            artikl=self.artikl,
            quantity=Decimal("5.0000"),
        )
        # External quantity differs on purpose; internal is authoritative for this action.
        WarehouseStock.objects.create(
            warehouse_id=self.inventory_warehouse,
            product=self.artikl,
            quantity=Decimal("20.0000"),
            internal_quantity=Decimal("3.0000"),
            unit="kom",
            product_name=self.artikl.name,
            product_code="X",
            base_group_name="",
            active=True,
        )

        request = self._request()
        qs = Inventory.objects.filter(id=inventory.id)
        create_transfer_for_inventory_shortage(self.modeladmin, request, qs)

        # internal(3) - counted(5) = -2 => overage IN move, no shortage transfer.
        self.assertFalse(WarehouseTransfer.objects.exists())
        move = StockMove.objects.get(move_type=StockMove.MoveType.IN, reference__startswith="Inventura visak")
        line = move.lines.get(artikl_id=self.artikl.rm_id)
        self.assertEqual(line.quantity, Decimal("2.0000"))
        inventory.refresh_from_db()
        self.assertEqual(inventory.status, Inventory.Status.CLOSED)

    @patch("stock.admin._import_warehouse_stock_for_warehouses", return_value=True)
    def test_action_skips_when_inventory_already_closed(self, _mock_import):
        inventory = Inventory.objects.create(
            warehouse=self.inventory_warehouse,
            date=timezone.now(),
            status=Inventory.Status.OPEN,
            created_by=self.user,
        )
        InventoryItem.objects.create(
            inventory=inventory,
            artikl=self.artikl,
            quantity=Decimal("5.0000"),
        )
        WarehouseStock.objects.create(
            warehouse_id=self.inventory_warehouse,
            product=self.artikl,
            quantity=Decimal("20.0000"),
            internal_quantity=Decimal("3.0000"),
            unit="kom",
            product_name=self.artikl.name,
            product_code="X",
            base_group_name="",
            active=True,
        )

        request = self._request()
        qs = Inventory.objects.filter(id=inventory.id)

        create_transfer_for_inventory_shortage(self.modeladmin, request, qs)
        first_move_count = StockMove.objects.count()
        first_transfer_count = WarehouseTransfer.objects.count()

        create_transfer_for_inventory_shortage(self.modeladmin, request, qs)

        self.assertEqual(StockMove.objects.count(), first_move_count)
        self.assertEqual(WarehouseTransfer.objects.count(), first_transfer_count)
