from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounting.models import Account, Ledger
from artikli.models import Artikl
from configuration.models import DocumentType
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import StockAccountingConfig, StockAllocation, WarehouseId
from stock.services import post_sale, post_warehouse_input_to_stock


class PostSaleTests(TestCase):
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
        self.cash = Account.objects.create(
            ledger=self.ledger,
            code="1000",
            name="Blagajna",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.revenue = Account.objects.create(
            ledger=self.ledger,
            code="6000",
            name="Prihod",
            type=Account.AccountType.INCOME,
            normal_side=Account.NormalSide.CREDIT,
            is_postable=True,
            is_active=True,
        )
        self.vat = Account.objects.create(
            ledger=self.ledger,
            code="2400",
            name="PDV obveza",
            type=Account.AccountType.LIABILITY,
            normal_side=Account.NormalSide.CREDIT,
            is_postable=True,
            is_active=True,
        )

        self.doc_type = DocumentType.objects.create(
            name="Gotovinska prodaja",
            code="SALE",
            direction=DocumentType.DIRECTION_OUT,
            ledger=self.ledger,
            revenue_account=self.revenue,
            vat_output_account=self.vat,
        )

        supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        order = PurchaseOrder.objects.create(supplier=supplier, ordered_at=timezone.now())
        self.warehouse = WarehouseId.objects.create(rm_id=1, name="Skladiste A")
        self.artikl = Artikl.objects.create(rm_id=10, name="Kava")

        StockAccountingConfig.objects.create(
            inventory_account=self.inventory,
            cogs_account=self.cogs,
            default_sale_warehouse=self.warehouse,
            default_purchase_warehouse=self.warehouse,
            auto_replenish_on_sale=False,
            default_cash_account=self.cash,
        )

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

    def test_post_sale_creates_move_and_journals(self):
        move, entry = post_sale(
            warehouse=self.warehouse,
            lines=[{"artikl": self.artikl, "quantity": Decimal("2.0000")}],
            date=timezone.localdate(),
            document_type=self.doc_type,
            cash_account=self.cash,
            net=Decimal("10.00"),
            vat=Decimal("2.50"),
        )

        self.assertIsNotNone(move.id)
        self.assertTrue(StockAllocation.objects.filter(move_line__move=move).exists())
        self.assertIsNotNone(move.journal_entry_id)
        self.assertIsNotNone(entry.id)
        self.assertEqual(move.sales_journal_entry_id, entry.id)
