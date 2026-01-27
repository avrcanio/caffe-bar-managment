from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase
from django.utils import timezone

from artikli.models import Artikl
from accounting.models import Account as AccountingAccount, JournalEntry, Ledger
from contacts.models import Supplier
from configuration.models import Account as ConfigAccount, DocumentType
from orders.admin import WarehouseInputAdmin
from orders.models import PurchaseOrder, WarehouseInput, WarehouseInputItem
from stock.models import WarehouseId


class PostWarehouseInputAdminActionTests(TestCase):
    def setUp(self):
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
        self.ledger = Ledger.objects.create(name="Test", oib="12345678901")
        self.acc_stock = AccountingAccount.objects.create(
            ledger=self.ledger,
            code="1310",
            name="Zaliha",
            type=AccountingAccount.AccountType.ASSET,
            normal_side=AccountingAccount.NormalSide.DEBIT,
            is_postable=True,
        )
        self.acc_counter = AccountingAccount.objects.create(
            ledger=self.ledger,
            code="2200",
            name="Protustavka",
            type=AccountingAccount.AccountType.LIABILITY,
            normal_side=AccountingAccount.NormalSide.CREDIT,
            is_postable=True,
        )
        self.cfg_stock, _ = ConfigAccount.objects.get_or_create(code="1310", defaults={"name": "Zaliha"})
        self.cfg_counter, _ = ConfigAccount.objects.get_or_create(code="2200", defaults={"name": "Protustavka"})
        self.doc_type = DocumentType.objects.create(
            name="Primka",
            code="10",
            direction=DocumentType.DIRECTION_IN,
            ledger=self.ledger,
            stock_account=self.cfg_stock,
            counterpart_account=self.cfg_counter,
        )

        self.input = WarehouseInput.objects.create(
            order=self.order,
            supplier=self.supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse,
            document_type=self.doc_type,
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

    def test_action_sets_stock_move_and_skips_second_time(self):
        request = self._get_request()
        qs = WarehouseInput.objects.filter(id=self.input.id)

        self.admin.post_warehouse_input_to_stock_action(request, qs)
        self.input.refresh_from_db()
        first_move_id = self.input.stock_move_id
        self.assertIsNotNone(first_move_id)
        self.assertIsNotNone(self.input.journal_entry_id)
        entry = self.input.journal_entry
        self.assertEqual(entry.status, JournalEntry.Status.POSTED)
        items = list(entry.items.order_by("id"))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].account_id, self.acc_stock.id)
        self.assertEqual(items[0].debit, Decimal("12.50"))
        self.assertEqual(items[1].account_id, self.acc_counter.id)
        self.assertEqual(items[1].credit, Decimal("12.50"))

        # second run should not create a new move
        self.admin.post_warehouse_input_to_stock_action(request, qs)
        self.input.refresh_from_db()
        self.assertEqual(self.input.stock_move_id, first_move_id)
        self.assertEqual(self.input.journal_entry_id, entry.id)
