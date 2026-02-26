from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl
from barion.models import ProductPopularitySnapshot
from configuration.models import TaxGroup
from sales.models import SalesInvoice, SalesInvoiceItem


class RefreshProductPopularityCommandTests(TestCase):
    def setUp(self):
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
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
    def _week_anchor(target_local_date):
        # Returns Friday/Saturday/Sunday around target date in local calendar week.
        friday = target_local_date - timedelta(days=(target_local_date.weekday() - 4) % 7)
        saturday = friday + timedelta(days=1)
        sunday = friday + timedelta(days=2)
        return friday, saturday, sunday

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

    def test_refresh_popularity_sets_night_qty_with_weekend_time_boundaries(self):
        today_local = timezone.localdate()
        friday, saturday, sunday = self._week_anchor(today_local)

        rows = [
            (self._aware(friday, 19, 59), "1.0000"),  # exclude
            (self._aware(friday, 20, 0), "1.0000"),  # include
            (self._aware(saturday, 1, 59), "1.0000"),  # include
            (self._aware(saturday, 2, 0), "1.0000"),  # exclude
            (self._aware(saturday, 20, 0), "1.0000"),  # include
            (self._aware(sunday, 1, 59), "1.0000"),  # include
            (self._aware(sunday, 2, 0), "1.0000"),  # exclude
        ]
        for idx, (issued_at, qty) in enumerate(rows, start=1):
            self._create_invoice_item(
                artikl=self.artikl_main,
                issued_at=issued_at,
                qty=qty,
                rm_number=10_000 + idx,
            )

        call_command("refresh_product_popularity", days=30, night_weeks=8)

        snapshot = ProductPopularitySnapshot.objects.get(artikl=self.artikl_main)
        self.assertEqual(snapshot.sold_qty_30d, Decimal("7.0000"))
        self.assertEqual(snapshot.sold_qty_night_weekend, Decimal("4.0000"))

    def test_refresh_popularity_keeps_night_only_items_in_snapshot(self):
        base_date = timezone.localdate() - timedelta(days=40)
        _friday, saturday, _sunday = self._week_anchor(base_date)
        night_dt = self._aware(saturday, 21, 0)
        self._create_invoice_item(
            artikl=self.artikl_night_only,
            issued_at=night_dt,
            qty="2.0000",
            rm_number=20_001,
        )

        call_command("refresh_product_popularity", days=30, night_weeks=8)

        snapshot = ProductPopularitySnapshot.objects.get(artikl=self.artikl_night_only)
        self.assertEqual(snapshot.sold_qty_30d, Decimal("0.0000"))
        self.assertEqual(snapshot.sold_qty_night_weekend, Decimal("2.0000"))
