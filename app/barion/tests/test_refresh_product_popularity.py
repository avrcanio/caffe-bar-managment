from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl, Category
from barion.models import BarionCategory, BarionCategorySettings, ProductPopularitySnapshot
from configuration.models import TaxGroup
from sales.models import SalesInvoice, SalesInvoiceItem


class BarionCategoryModelTests(TestCase):
    def test_settings_singleton_can_be_fetched(self):
        settings = BarionCategorySettings.get_solo()
        self.assertEqual(settings.pk, 1)
        self.assertEqual(str(settings.day_start), "07:00:00")
        self.assertEqual(str(settings.day_end), "20:00:00")
        self.assertEqual(str(settings.night_start), "20:00:00")
        self.assertEqual(str(settings.night_end), "02:00:00")

    def test_barion_category_disallows_duplicate_category(self):
        category = Category.objects.create(name="Napitci")
        BarionCategory.objects.create(category=category)

        with self.assertRaises(IntegrityError):
            BarionCategory.objects.create(category=category)

    def test_settings_allow_cross_midnight_periods(self):
        settings = BarionCategorySettings.get_solo()
        settings.day_start = time(7, 0)
        settings.day_end = time(20, 0)
        settings.night_start = time(20, 0)
        settings.night_end = time(2, 0)

        settings.full_clean()


class RefreshProductPopularityCommandTests(TestCase):
    def setUp(self):
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
        self.settings = BarionCategorySettings.get_solo()
        self.artikl_main = Artikl.objects.create(
            name="Test artikal",
            code="TEST-POP-1",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )
        self.artikl_night_only = Artikl.objects.create(
            name="Night only artikal",
            code="TEST-POP-2",
            is_sellable=True,
            is_stock_item=False,
            tax_group=self.tax_group,
        )

    @staticmethod
    def _aware(local_date, hh, mm):
        naive = datetime.combine(local_date, time(hh, mm))
        return timezone.make_aware(naive, timezone.get_current_timezone())

    @staticmethod
    def _create_invoice_item(*, artikl, issued_at, qty, rm_number):
        invoice = SalesInvoice.objects.create(
            rm_number=rm_number,
            issued_on=timezone.localtime(issued_at).date(),
            issued_at=issued_at,
        )
        SalesInvoiceItem.objects.create(
            invoice=invoice,
            artikl=artikl,
            product_name=artikl.name,
            quantity=Decimal(str(qty)).quantize(Decimal("0.0001")),
            amount=Decimal("10.00"),
        )

    def test_refresh_popularity_splits_day_and_night_by_configured_windows(self):
        today_local = timezone.localdate()
        rows = [
            (self._aware(today_local, 6, 59), "1.0000"),
            (self._aware(today_local, 7, 0), "1.0000"),
            (self._aware(today_local, 19, 59), "1.0000"),
            (self._aware(today_local, 20, 0), "1.0000"),
            (self._aware(today_local + timedelta(days=1), 1, 59), "1.0000"),
            (self._aware(today_local + timedelta(days=1), 2, 0), "1.0000"),
        ]
        for idx, (issued_at, qty) in enumerate(rows, start=1):
            self._create_invoice_item(
                artikl=self.artikl_main,
                issued_at=issued_at,
                qty=qty,
                rm_number=10_000 + idx,
            )

        call_command("refresh_product_popularity")

        snapshot = ProductPopularitySnapshot.objects.get(artikl=self.artikl_main)
        self.assertEqual(snapshot.sold_qty_day, Decimal("2.0000"))
        self.assertEqual(snapshot.sold_qty_night, Decimal("2.0000"))

    def test_refresh_popularity_keeps_night_only_items_in_snapshot(self):
        base_date = timezone.localdate() - timedelta(days=5)
        night_dt = self._aware(base_date, 21, 0)
        self._create_invoice_item(
            artikl=self.artikl_night_only,
            issued_at=night_dt,
            qty="2.0000",
            rm_number=20_001,
        )

        call_command("refresh_product_popularity")

        snapshot = ProductPopularitySnapshot.objects.get(artikl=self.artikl_night_only)
        self.assertEqual(snapshot.sold_qty_day, Decimal("0.0000"))
        self.assertEqual(snapshot.sold_qty_night, Decimal("2.0000"))

    def test_refresh_popularity_counts_after_midnight_inside_night_window(self):
        today_local = timezone.localdate()
        self._create_invoice_item(
            artikl=self.artikl_main,
            issued_at=self._aware(today_local + timedelta(days=1), 1, 30),
            qty="3.0000",
            rm_number=30_001,
        )

        call_command("refresh_product_popularity")

        snapshot = ProductPopularitySnapshot.objects.get(artikl=self.artikl_main)
        self.assertEqual(snapshot.sold_qty_day, Decimal("0.0000"))
        self.assertEqual(snapshot.sold_qty_night, Decimal("3.0000"))
