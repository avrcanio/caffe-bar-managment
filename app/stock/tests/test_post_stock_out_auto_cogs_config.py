from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounting.models import Account, Ledger
from artikli.models import Artikl
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import StockAccountingConfig, WarehouseId
from stock.services import post_stock_out, post_warehouse_input_to_stock


class PostStockOutAutoCogsConfigTests(TestCase):
    def setUp(self):
        self.ledger = Ledger.objects.create(name="Mozart")
        self.cogs = Account.objects.create(
            ledger=self.ledger,
            code="5000",
            name="COGS",
            type=Account.AccountType.EXPENSE,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.inventory = Account.objects.create(
            ledger=self.ledger,
            code="1310",
            name="Zaliha robe",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.warehouse = WarehouseId.objects.create(rm_id=1, name="Skladiste A")
        StockAccountingConfig.objects.create(
            inventory_account=self.inventory,
            cogs_account=self.cogs,
            default_sale_warehouse=self.warehouse,
            default_purchase_warehouse=self.warehouse,
            auto_replenish_on_sale=False,
            default_cash_account=self.cogs,
        )

        supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        order = PurchaseOrder.objects.create(supplier=supplier, ordered_at=timezone.now())
        self.artikl = Artikl.objects.create(rm_id=10, name="Kava")

        input1 = WarehouseInput.objects.create(
            order=order,
            supplier=supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse,
        )
        WarehouseInputItem.objects.create(
            warehouse_input=input1,
            artikl=self.artikl,
            quantity=Decimal("5.0000"),
            buying_price=Decimal("2.00"),
            total=Decimal("10.00"),
        )
        post_warehouse_input_to_stock(warehouse_input=input1)

    def test_auto_cogs_uses_config(self):
        move = post_stock_out(
            warehouse=self.warehouse,
            items=[{"artikl": self.artikl, "quantity": Decimal("2.0000")}],
            purpose="sale",
        )
        self.assertIsNotNone(move.journal_entry_id)
