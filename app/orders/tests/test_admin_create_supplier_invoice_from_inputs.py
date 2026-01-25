from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase
from django.utils import timezone

from contacts.models import Supplier
from orders.admin import WarehouseInputAdmin
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from purchases.models import SupplierInvoice
from accounting.models import Account, Ledger
from stock.models import StockAccountingConfig
from stock.models import WarehouseId
from artikli.models import Artikl


class CreateSupplierInvoiceFromInputsTests(TestCase):
    def setUp(self):
        ledger = Ledger.objects.create(name="Mozart")
        cash = Account.objects.create(
            ledger=ledger,
            code="1000",
            name="Blagajna",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        inventory = Account.objects.create(
            ledger=ledger,
            code="1310",
            name="Zaliha robe",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        cogs = Account.objects.create(
            ledger=ledger,
            code="5000",
            name="COGS",
            type=Account.AccountType.EXPENSE,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.admin = WarehouseInputAdmin(WarehouseInput, self.site)
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
        )

        self.supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        self.order = PurchaseOrder.objects.create(
            supplier=self.supplier,
            ordered_at=timezone.now(),
        )
        self.warehouse = WarehouseId.objects.create(rm_id=1, name="Skladiste 1")
        self.artikl = Artikl.objects.create(rm_id=10, name="Kava")
        StockAccountingConfig.objects.create(
            inventory_account=inventory,
            cogs_account=cogs,
            default_sale_warehouse=self.warehouse,
            default_purchase_warehouse=self.warehouse,
            auto_replenish_on_sale=False,
            default_cash_account=cash,
        )

        self.input = WarehouseInput.objects.create(
            order=self.order,
            supplier=self.supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse,
            invoice_code="INV-1",
        )
        WarehouseInputItem.objects.create(
            warehouse_input=self.input,
            artikl=self.artikl,
            quantity=Decimal("5.0000"),
            buying_price=Decimal("2.50"),
            total=Decimal("12.50"),
        )

    def _get_request(self):
        request = self.factory.post("/admin/orders/warehouseinput/")
        request.user = self.user
        setattr(request, "session", self.client.session)
        messages = FallbackStorage(request)
        setattr(request, "_messages", messages)
        return request

    def test_cannot_create_invoice_if_input_already_linked(self):
        invoice = SupplierInvoice.objects.create(
            supplier=self.supplier,
            invoice_number="INV-1",
            invoice_date=timezone.localdate(),
        )
        invoice.inputs.add(self.input)

        request = self._get_request()
        qs = WarehouseInput.objects.filter(id=self.input.id)
        self.admin.create_supplier_invoice_from_inputs(request, qs)

        self.assertEqual(SupplierInvoice.objects.count(), 1)
