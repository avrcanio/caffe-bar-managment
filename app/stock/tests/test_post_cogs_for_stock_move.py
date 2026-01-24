from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounting.models import Account, Ledger, JournalEntry
from artikli.models import Artikl
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import StockAllocation, WarehouseId
from stock.services import post_cogs_for_stock_move, post_stock_out, post_warehouse_input_to_stock


class PostCogsForStockMoveTests(TestCase):
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
        self.warehouse = WarehouseId.objects.create(rm_id=1, name="Skladiste 1")
        artikl = Artikl.objects.create(rm_id=10, name="Kava")

        input1 = WarehouseInput.objects.create(
            order=order,
            supplier=supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse,
        )
        WarehouseInputItem.objects.create(
            warehouse_input=input1,
            artikl=artikl,
            quantity=Decimal("5.0000"),
            buying_price=Decimal("2.00"),
            total=Decimal("10.00"),
        )
        post_warehouse_input_to_stock(warehouse_input=input1)

        input2 = WarehouseInput.objects.create(
            order=order,
            supplier=supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse,
        )
        WarehouseInputItem.objects.create(
            warehouse_input=input2,
            artikl=artikl,
            quantity=Decimal("3.0000"),
            buying_price=Decimal("3.00"),
            total=Decimal("9.00"),
        )
        post_warehouse_input_to_stock(warehouse_input=input2)

        self.move = post_stock_out(
            warehouse=self.warehouse,
            items=[{"artikl": artikl, "quantity": Decimal("6.0000")}],
            reference="Test izlaz",
        )

    def test_posts_cogs_and_links_journal_entry(self):
        entry = post_cogs_for_stock_move(
            move=self.move,
            cogs_account=self.cogs,
            inventory_account=self.inventory,
        )

        self.move.refresh_from_db()
        self.assertEqual(self.move.journal_entry_id, entry.id)
        self.assertEqual(entry.status, JournalEntry.Status.POSTED)
        self.assertEqual(entry.items.count(), 2)

        total_cost = sum(
            (
                a.qty * a.unit_cost
                for a in StockAllocation.objects.filter(move_line__move=self.move).select_related("move_line", "lot")
            ),
            Decimal("0.00"),
        )
        debit = entry.items.filter(account=self.cogs).first().debit
        credit = entry.items.filter(account=self.inventory).first().credit
        self.assertEqual(debit, total_cost)
        self.assertEqual(credit, total_cost)

    def test_cannot_post_twice(self):
        post_cogs_for_stock_move(
            move=self.move,
            cogs_account=self.cogs,
            inventory_account=self.inventory,
        )
        with self.assertRaises(ValidationError):
            post_cogs_for_stock_move(
                move=self.move,
                cogs_account=self.cogs,
                inventory_account=self.inventory,
            )
