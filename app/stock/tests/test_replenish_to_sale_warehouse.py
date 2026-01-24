from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounting.models import Account, Ledger
from artikli.models import Artikl
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import StockAccountingConfig, StockLot, StockMove, WarehouseId
from stock.services import post_warehouse_input_to_stock, replenish_to_sale_warehouse


class ReplenishToSaleWarehouseTests(TestCase):
    def setUp(self):
        self.ledger = Ledger.objects.create(name="Mozart")
        self.inventory = Account.objects.create(
            ledger=self.ledger,
            code="1310",
            name="Zaliha robe",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.cogs = Account.objects.create(
            ledger=self.ledger,
            code="5000",
            name="COGS",
            type=Account.AccountType.EXPENSE,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )

        self.warehouse_main = WarehouseId.objects.create(rm_id=1, name="Glavno")
        self.warehouse_bar = WarehouseId.objects.create(rm_id=2, name="Sank")
        StockAccountingConfig.objects.create(
            inventory_account=self.inventory,
            cogs_account=self.cogs,
            default_sale_warehouse=self.warehouse_bar,
            default_purchase_warehouse=self.warehouse_main,
            default_replenish_from_warehouse=self.warehouse_main,
            auto_replenish_on_sale=False,
        )

        supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        order = PurchaseOrder.objects.create(supplier=supplier, ordered_at=timezone.now())
        self.artikl = Artikl.objects.create(rm_id=10, name="Kava")

        input1 = WarehouseInput.objects.create(
            order=order,
            supplier=supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse_main,
        )
        WarehouseInputItem.objects.create(
            warehouse_input=input1,
            artikl=self.artikl,
            quantity=Decimal("10.0000"),
            buying_price=Decimal("2.00"),
            total=Decimal("20.00"),
        )
        post_warehouse_input_to_stock(warehouse_input=input1)

    def test_replenish_creates_transfer_and_lot(self):
        move = replenish_to_sale_warehouse(
            lines=[{"artikl": self.artikl, "quantity": Decimal("4.0000")}],
        )

        self.assertEqual(move.move_type, StockMove.MoveType.TRANSFER)
        lot = StockLot.objects.get(warehouse=self.warehouse_bar, artikl=self.artikl)
        self.assertEqual(lot.qty_remaining, Decimal("4.0000"))
