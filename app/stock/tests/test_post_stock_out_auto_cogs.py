from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounting.models import Account, Ledger
from artikli.models import Artikl
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import StockAllocation, WarehouseId
from stock.services import post_stock_out, post_warehouse_input_to_stock


class PostStockOutAutoCogsTests(TestCase):
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

        supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        order = PurchaseOrder.objects.create(supplier=supplier, ordered_at=timezone.now())
        self.warehouse = WarehouseId.objects.create(rm_id=1, name="Skladiste A")
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

    def test_auto_cogs_for_sale(self):
        move = post_stock_out(
            warehouse=self.warehouse,
            items=[{"artikl": self.artikl, "quantity": Decimal("3.0000")}],
            purpose="sale",
            cogs_account=self.cogs,
            inventory_account=self.inventory,
        )
        self.assertIsNotNone(move.journal_entry_id)

        total_cost = sum(
            (a.qty * a.unit_cost for a in StockAllocation.objects.filter(move_line__move=move)),
            Decimal("0.00"),
        )
        entry = move.journal_entry
        debit = entry.items.filter(account=self.cogs).first().debit
        credit = entry.items.filter(account=self.inventory).first().credit
        self.assertEqual(debit, total_cost)
        self.assertEqual(credit, total_cost)

    def test_no_auto_cogs_for_waste(self):
        move = post_stock_out(
            warehouse=self.warehouse,
            items=[{"artikl": self.artikl, "quantity": Decimal("1.0000")}],
            purpose="waste",
            cogs_account=self.cogs,
            inventory_account=self.inventory,
        )
        self.assertIsNone(move.journal_entry_id)
