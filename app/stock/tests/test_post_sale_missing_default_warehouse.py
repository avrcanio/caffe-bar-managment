from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounting.models import Account, Ledger
from artikli.models import Artikl
from configuration.models import DocumentType
from contacts.models import Supplier
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import StockAccountingConfig, WarehouseId
from stock.services import post_sale, post_warehouse_input_to_stock


class PostSaleMissingDefaultWarehouseTests(TestCase):
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

        self.warehouse = WarehouseId.objects.create(rm_id=1, name="Skladiste A")
        with self.assertRaises(ValidationError):
            StockAccountingConfig.objects.create(
                inventory_account=self.inventory,
                cogs_account=self.cogs,
                default_purchase_warehouse=self.warehouse,
            )

        cfg = StockAccountingConfig.objects.create(
            inventory_account=self.inventory,
            cogs_account=self.cogs,
            default_sale_warehouse=self.warehouse,
            default_purchase_warehouse=self.warehouse,
            auto_replenish_on_sale=False,
        )
        StockAccountingConfig.objects.filter(pk=cfg.pk).update(default_sale_warehouse=None)
        cfg.refresh_from_db()

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

    def test_missing_default_sale_warehouse_raises(self):
        with self.assertRaises(ValidationError):
            post_sale(
                warehouse=None,
                lines=[{"artikl": self.artikl, "quantity": Decimal("2.0000")}],
                date=timezone.localdate(),
                document_type=self.doc_type,
                cash_account=self.cash,
                net=Decimal("10.00"),
                vat=Decimal("2.50"),
            )
