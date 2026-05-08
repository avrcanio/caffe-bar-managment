from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl
from contacts.models import Supplier
from stock.models import StockAllocation, StockLot, SupplierReturn, SupplierReturnItem, WarehouseId
from stock.services import post_supplier_return_to_stock


class SupplierReturnTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(rm_id=1, name="Dobavljac")
        self.warehouse = WarehouseId.objects.create(rm_id=1, name="Skladiste 1")
        self.artikl = Artikl.objects.create(rm_id=10, name="Kava")

        StockLot.objects.create(
            warehouse=self.warehouse,
            artikl=self.artikl,
            received_at=timezone.now(),
            unit_cost=Decimal("2.00"),
            qty_in=Decimal("5.0000"),
            qty_remaining=Decimal("5.0000"),
        )

    def test_posts_supplier_return_to_stock(self):
        sr = SupplierReturn.objects.create(
            supplier=self.supplier,
            warehouse=self.warehouse,
            date=timezone.now(),
            reference="SR-1",
            note="Test",
        )
        SupplierReturnItem.objects.create(
            supplier_return=sr,
            artikl=self.artikl,
            quantity=Decimal("2.0000"),
        )

        move = post_supplier_return_to_stock(supplier_return=sr)

        sr.refresh_from_db()
        self.assertEqual(sr.status, SupplierReturn.Status.POSTED)
        self.assertEqual(sr.stock_move_id, move.id)
        self.assertEqual(move.move_type, "out")
        self.assertEqual(move.purpose, "supplier_return")

        lot = StockLot.objects.get(warehouse=self.warehouse, artikl=self.artikl)
        self.assertEqual(lot.qty_remaining, Decimal("3.0000"))

        alloc_qty = (
            StockAllocation.objects.filter(move_line__move=move)
            .aggregate(total=models.Sum("qty"))["total"]
        )
        self.assertEqual(alloc_qty, Decimal("2.0000"))

    def test_cannot_post_twice(self):
        sr = SupplierReturn.objects.create(
            supplier=self.supplier,
            warehouse=self.warehouse,
            date=timezone.now(),
        )
        SupplierReturnItem.objects.create(
            supplier_return=sr,
            artikl=self.artikl,
            quantity=Decimal("1.0000"),
        )
        post_supplier_return_to_stock(supplier_return=sr)

        with self.assertRaises(ValidationError):
            post_supplier_return_to_stock(supplier_return=sr)

    def test_insufficient_stock_raises(self):
        sr = SupplierReturn.objects.create(
            supplier=self.supplier,
            warehouse=self.warehouse,
            date=timezone.now(),
        )
        SupplierReturnItem.objects.create(
            supplier_return=sr,
            artikl=self.artikl,
            quantity=Decimal("999.0000"),
        )
        with self.assertRaises(ValidationError):
            post_supplier_return_to_stock(supplier_return=sr)

