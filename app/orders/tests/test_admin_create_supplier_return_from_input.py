from decimal import Decimal
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponseRedirect
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounting.models import Account, JournalEntry, Ledger
from contacts.models import Supplier
from orders.admin import WarehouseInputAdmin
from orders.models import PurchaseOrder, SupplierInvoice, WarehouseInput, WarehouseInputItem
from stock.models import StockMove, StockMoveLine, SupplierReturn, WarehouseId
from artikli.models import Artikl
from configuration.models import DocumentType


class CreateSupplierReturnFromInputTests(TestCase):
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

        self.ledger = Ledger.objects.create(name="Mozart")
        self.ap_account = Account.objects.create(
            ledger=self.ledger,
            code="2200",
            name="Dobavljaci",
            type=Account.AccountType.LIABILITY,
            normal_side=Account.NormalSide.CREDIT,
            is_postable=True,
        )
        self.cash_account = Account.objects.create(
            ledger=self.ledger,
            code="1000",
            name="Blagajna",
            type=Account.AccountType.ASSET,
            normal_side=Account.NormalSide.DEBIT,
            is_postable=True,
        )

        self.supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        self.order = PurchaseOrder.objects.create(
            supplier=self.supplier,
            ordered_at=timezone.now(),
        )
        self.warehouse = WarehouseId.objects.create(rm_id=6, name="Glavno")
        self.artikl = Artikl.objects.create(rm_id=1333, name="Test artikl")

        self.input = WarehouseInput.objects.create(
            order=self.order,
            supplier=self.supplier,
            date=timezone.localdate(),
            warehouse=self.warehouse,
            invoice_code="INV-RET-1",
        )
        WarehouseInputItem.objects.create(
            warehouse_input=self.input,
            artikl=self.artikl,
            quantity=Decimal("2.0000"),
            price=Decimal("10.00"),
            total=Decimal("20.00"),
            tax_rate=Decimal("0.2500"),
        )
        self.input.stock_move = StockMove.objects.create(
            move_type=StockMove.MoveType.IN,
            date=timezone.now(),
            reference=f"Primka #{self.input.id}",
        )
        self.input.save(update_fields=["stock_move"])

    def _get_request(self):
        request = self.factory.post("/admin/orders/warehouseinput/")
        request.user = self.user
        setattr(request, "session", self.client.session)
        messages = FallbackStorage(request)
        setattr(request, "_messages", messages)
        return request

    def test_action_redirects_to_quantity_form(self):
        request = self._get_request()
        qs = WarehouseInput.objects.filter(id=self.input.id)
        response = self.admin.create_supplier_return_from_inputs(request, qs)
        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertIn("supplier-return", response.url)
        self.assertIn(f"ids={self.input.id}", response.url)

    @patch("orders.admin.post_supplier_return_charge_from_input")
    @patch("orders.admin.post_stock_out_multi_warehouse")
    def test_creates_only_stock_return_when_no_posted_invoice(self, mock_post_stock_out, mock_fin):
        return_move = StockMove.objects.create(
            move_type=StockMove.MoveType.OUT,
            date=timezone.now(),
            reference="Povrat test",
        )
        StockMoveLine.objects.create(
            move=return_move,
            warehouse=self.warehouse,
            artikl=self.artikl,
            quantity=Decimal("2.0000"),
            unit_cost=Decimal("1.0000"),
        )
        mock_post_stock_out.return_value = return_move

        request = self._get_request()
        self.admin._execute_supplier_return_from_inputs(
            request=request,
            inputs=[self.input],
            line_quantities_by_input_id={self.input.id: {self.input.items.first().id: Decimal("2.0000")}},
            warehouse_quantities_by_input_id={self.input.id: {self.input.items.first().id: {6: Decimal("2.0000")}}},
        )

        self.input.refresh_from_db()
        self.assertEqual(self.input.supplier_return_stock_move_id, return_move.id)
        self.assertIsNone(self.input.supplier_return_journal_entry_id)
        mock_post_stock_out.assert_called_once()
        mock_fin.assert_not_called()

        sr = SupplierReturn.objects.get(source_warehouse_input=self.input)
        self.assertEqual(sr.stock_move_id, return_move.id)
        self.assertEqual(sr.status, SupplierReturn.Status.POSTED)
        self.assertEqual(sr.items.count(), 1)

    @patch("orders.admin.post_supplier_return_charge_from_input")
    @patch("orders.admin.post_stock_out_multi_warehouse")
    def test_creates_financial_charge_when_posted_supplier_invoice_exists(self, mock_post_stock_out, mock_fin):
        doc_type = DocumentType.objects.create(
            name="Ulazni racun",
            code="UR",
            direction=DocumentType.DIRECTION_IN,
            ledger=self.ledger,
        )
        invoice_entry = JournalEntry.objects.create(
            ledger=self.ledger,
            number=1,
            date=timezone.localdate(),
            status=JournalEntry.Status.POSTED,
        )
        invoice = SupplierInvoice.objects.create(
            supplier=self.supplier,
            invoice_number="INV-RET-1",
            invoice_date=timezone.localdate(),
            payment_terms=SupplierInvoice.PaymentTerms.DEFERRED,
            document_type=doc_type,
            ap_account=self.ap_account,
            cash_account=self.cash_account,
            journal_entry=invoice_entry,
        )
        invoice.inputs.add(self.input)

        return_move = StockMove.objects.create(
            move_type=StockMove.MoveType.OUT,
            date=timezone.now(),
            reference="Povrat test",
        )
        StockMoveLine.objects.create(
            move=return_move,
            warehouse=self.warehouse,
            artikl=self.artikl,
            quantity=Decimal("2.0000"),
            unit_cost=Decimal("1.0000"),
        )
        charge_entry = JournalEntry.objects.create(
            ledger=self.ledger,
            number=2,
            date=timezone.localdate(),
            status=JournalEntry.Status.POSTED,
        )
        mock_post_stock_out.return_value = return_move
        mock_fin.return_value = charge_entry

        request = self._get_request()
        self.admin._execute_supplier_return_from_inputs(
            request=request,
            inputs=[self.input],
            line_quantities_by_input_id={self.input.id: {self.input.items.first().id: Decimal("2.0000")}},
            warehouse_quantities_by_input_id={self.input.id: {self.input.items.first().id: {6: Decimal("2.0000")}}},
        )

        self.input.refresh_from_db()
        self.assertEqual(self.input.supplier_return_stock_move_id, return_move.id)
        self.assertEqual(self.input.supplier_return_journal_entry_id, charge_entry.id)
        mock_post_stock_out.assert_called_once()
        mock_fin.assert_called_once()

        sr = SupplierReturn.objects.get(source_warehouse_input=self.input)
        self.assertEqual(sr.stock_move_id, return_move.id)
        self.assertEqual(sr.items.count(), 1)
