from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounting.models import Account as AccountingAccount, Ledger
from artikli.models import Artikl, UnitOfMeasureData
from configuration.models import Account as ConfigAccount, DocumentType, PaymentType
from contacts.models import Supplier
from orders.models import PurchaseOrder, SupplierInvoice, WarehouseInput, WarehouseInputItem
from stock.models import StockAccountingConfig, WarehouseId


class SupplierInvoiceWorkflowApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="api-admin",
            email="api-admin@example.com",
            password="pass",
        )
        self.client.force_authenticate(user=self.user)

        self.ledger = Ledger.objects.create(name="Mozart", oib="12345678901")
        self.acc_stock = AccountingAccount.objects.create(
            ledger=self.ledger,
            code="1310",
            name="Zaliha",
            type=AccountingAccount.AccountType.ASSET,
            normal_side=AccountingAccount.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.acc_counter = AccountingAccount.objects.create(
            ledger=self.ledger,
            code="2200",
            name="Protustavka",
            type=AccountingAccount.AccountType.LIABILITY,
            normal_side=AccountingAccount.NormalSide.CREDIT,
            is_postable=True,
            is_active=True,
        )
        self.acc_cash = AccountingAccount.objects.create(
            ledger=self.ledger,
            code="1000",
            name="Blagajna",
            type=AccountingAccount.AccountType.ASSET,
            normal_side=AccountingAccount.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )
        self.acc_ap = AccountingAccount.objects.create(
            ledger=self.ledger,
            code="2400",
            name="Dobavljači",
            type=AccountingAccount.AccountType.LIABILITY,
            normal_side=AccountingAccount.NormalSide.CREDIT,
            is_postable=True,
            is_active=True,
        )
        self.acc_vat_input = AccountingAccount.objects.create(
            ledger=self.ledger,
            code="1400",
            name="Pretporez",
            type=AccountingAccount.AccountType.ASSET,
            normal_side=AccountingAccount.NormalSide.DEBIT,
            is_postable=True,
            is_active=True,
        )

        self.cfg_stock, _ = ConfigAccount.objects.get_or_create(
            code="1310",
            defaults={"name": "Zaliha"},
        )
        self.cfg_counter, _ = ConfigAccount.objects.get_or_create(
            code="2200",
            defaults={"name": "Protustavka"},
        )
        self.doc_type = DocumentType.objects.create(
            name="Primka",
            code="10",
            direction=DocumentType.DIRECTION_IN,
            ledger=self.ledger,
            stock_account=self.cfg_stock,
            counterpart_account=self.cfg_counter,
            ap_account=self.acc_ap,
            vat_input_account=self.acc_vat_input,
        )
        self.doc_type_cash = DocumentType.objects.create(
            name="Ulaz gotovina",
            code="3",
            direction=DocumentType.DIRECTION_IN,
            ledger=self.ledger,
            stock_account=self.cfg_stock,
            counterpart_account=self.cfg_counter,
            ap_account=self.acc_ap,
            vat_input_account=self.acc_vat_input,
        )

        self.payment_cash = PaymentType.objects.create(
            rm_id=3,
            name="Gotovina",
        )
        self.payment_deferred = PaymentType.objects.create(
            rm_id=7,
            name="Virman",
        )

        self.warehouse = WarehouseId.objects.create(rm_id=1, name="Skladište 1")
        self.supplier = Supplier.objects.create(rm_id=1, name="Dobavljač")
        self.artikl = Artikl.objects.create(rm_id=10, name="Kava")
        self.unit = UnitOfMeasureData.objects.create(rm_id=501, name="kom")

        StockAccountingConfig.objects.create(
            inventory_account=self.acc_stock,
            cogs_account=self.acc_counter,
            default_sale_warehouse=self.warehouse,
            default_purchase_warehouse=self.warehouse,
            auto_replenish_on_sale=False,
            default_cash_account=self.acc_cash,
            default_deposit_account=self.acc_stock,
        )

    def _create_order(self, payment_type):
        return PurchaseOrder.objects.create(
            supplier=self.supplier,
            payment_type=payment_type,
            ordered_at=timezone.now(),
            status=PurchaseOrder.STATUS_CONFIRMED,
        )

    def _create_posted_input(self, *, payment_type, invoice_code="INV-API-1"):
        order = self._create_order(payment_type)
        wi = WarehouseInput.objects.create(
            order=order,
            supplier=self.supplier,
            payment_type=payment_type,
            date=timezone.localdate(),
            warehouse=self.warehouse,
            document_type=self.doc_type,
            invoice_code=invoice_code,
            delivery_note="OT-1",
        )
        WarehouseInputItem.objects.create(
            warehouse_input=wi,
            artikl=self.artikl,
            quantity=Decimal("2.0000"),
            price=Decimal("5.00"),
            total=Decimal("10.00"),
            tax_rate=Decimal("0.25"),
            gross_price=Decimal("12.50"),
            buying_price=Decimal("5.00"),
        )
        from stock.services import post_warehouse_input_to_stock
        from accounting.services import post_warehouse_input_to_journal

        post_warehouse_input_to_stock(warehouse_input=wi)
        post_warehouse_input_to_journal(warehouse_input=wi, user=self.user)
        wi.refresh_from_db()
        return wi

    def test_create_supplier_invoice_endpoint_creates_invoice(self):
        wi = self._create_posted_input(payment_type=self.payment_deferred, invoice_code="INV-200")

        response = self.client.post(
            f"/api/warehouse-inputs/{wi.id}/create-supplier-invoice/",
            {},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.json())
        body = response.json()
        self.assertTrue(body["created"])
        self.assertFalse(body["posted"])

        invoice = SupplierInvoice.objects.get(id=body["supplier_invoice_id"])
        self.assertEqual(invoice.invoice_number, "INV-200")
        self.assertEqual(invoice.payment_terms, SupplierInvoice.PaymentTerms.DEFERRED)
        self.assertIsNone(invoice.journal_entry_id)
        self.assertEqual(invoice.inputs.count(), 1)

    def test_create_supplier_invoice_endpoint_uses_increment_on_duplicate_number(self):
        SupplierInvoice.objects.create(
            supplier=self.supplier,
            invoice_number="INV-202",
            invoice_date=timezone.localdate(),
        )
        wi = self._create_posted_input(payment_type=self.payment_deferred, invoice_code="INV-202")

        response = self.client.post(
            f"/api/warehouse-inputs/{wi.id}/create-supplier-invoice/",
            {},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.json())
        body = response.json()
        self.assertTrue(body["created"])
        self.assertEqual(body["invoice_number"], "INV-202 (1)")

    def test_post_supplier_invoice_endpoint_posts_invoice(self):
        wi = self._create_posted_input(payment_type=self.payment_deferred, invoice_code="INV-201")
        invoice = SupplierInvoice.objects.create(
            supplier=self.supplier,
            invoice_number="INV-201",
            invoice_date=timezone.localdate(),
            payment_terms=SupplierInvoice.PaymentTerms.DEFERRED,
            document_type=self.doc_type,
            ap_account=self.acc_ap,
            deposit_total=Decimal("0.00"),
            total_net=Decimal("10.00"),
            total_vat=Decimal("2.50"),
            total_gross=Decimal("12.50"),
        )
        invoice.inputs.add(wi)

        response = self.client.post(
            f"/api/supplier-invoices/{invoice.id}/post/",
            {},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.json())
        body = response.json()
        self.assertTrue(body["posted"])
        self.assertFalse(body["already_posted"])
        self.assertIsNotNone(body["journal_entry_id"])

        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.journal_entry_id)
        self.assertEqual(invoice.payment_status, SupplierInvoice.PaymentStatus.UNPAID)

    def test_auto_flow_on_purchase_order_warehouse_input_with_cash(self):
        order = self._create_order(self.payment_cash)
        from orders.models import PurchaseOrderItem

        PurchaseOrderItem.objects.create(
            order=order,
            artikl=self.artikl,
            quantity=Decimal("2.0000"),
            unit_of_measure=self.unit,
            price=Decimal("5.00"),
        )
        response = self.client.post(
            f"/api/purchase-orders/{order.id}/warehouse-inputs/",
            {
                "document_date": str(timezone.localdate()),
                "warehouse_id": self.warehouse.rm_id,
                "invoice_code": "INV-CASH-1",
                "delivery_note": "OT-CASH-1",
                "currency": "EUR",
                "items": [
                    {
                        "purchase_order_item_id": order.items.first().id,
                        "received_quantity": "2.0000",
                        "confirmed": True,
                        "expected_unit_price": "5.00",
                    }
                ],
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 201, response.json())
        payload = response.json()
        self.assertIn("automation", payload)
        self.assertTrue(payload["automation"]["warehouse_input_posted"])
        self.assertTrue(payload["automation"]["supplier_invoice_created"])
        self.assertTrue(payload["automation"]["supplier_invoice_posted"])
        self.assertIsNotNone(payload["automation"]["supplier_invoice_id"])

        wi = WarehouseInput.objects.get(id=payload["warehouse_input"]["id"])
        self.assertIsNotNone(wi.stock_move_id)
        self.assertIsNotNone(wi.journal_entry_id)
        invoice = SupplierInvoice.objects.get(id=payload["automation"]["supplier_invoice_id"])
        self.assertIsNotNone(invoice.journal_entry_id)
        self.assertEqual(invoice.payment_terms, SupplierInvoice.PaymentTerms.CASH)
        self.assertEqual(invoice.payment_status, SupplierInvoice.PaymentStatus.PAID)

    def test_auto_flow_without_invoice_code_skips_supplier_invoice(self):
        order = self._create_order(self.payment_deferred)
        from orders.models import PurchaseOrderItem

        PurchaseOrderItem.objects.create(
            order=order,
            artikl=self.artikl,
            quantity=Decimal("1.0000"),
            unit_of_measure=self.unit,
            price=Decimal("3.00"),
        )
        response = self.client.post(
            f"/api/purchase-orders/{order.id}/warehouse-inputs/",
            {
                "document_date": str(timezone.localdate()),
                "warehouse_id": self.warehouse.rm_id,
                "invoice_code": "",
                "delivery_note": "OT-ONLY-1",
                "currency": "EUR",
                "items": [
                    {
                        "purchase_order_item_id": order.items.first().id,
                        "received_quantity": "1.0000",
                        "confirmed": True,
                        "expected_unit_price": "3.00",
                    }
                ],
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, 201, response.json())
        payload = response.json()
        self.assertTrue(payload["automation"]["warehouse_input_posted"])
        self.assertFalse(payload["automation"]["supplier_invoice_created"])
        self.assertFalse(payload["automation"]["supplier_invoice_posted"])
        self.assertIsNone(payload["automation"]["supplier_invoice_id"])
