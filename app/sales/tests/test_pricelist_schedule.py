from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from artikli.models import Artikl
from sales.models import SalesPriceItem, SalesPriceList
from sales.price_resolution import resolve_active_sales_unit_price
from sales.pricelist_schedule import (
    apply_price_list_to_remaris,
    price_lists_due_for_apply,
    price_lists_due_for_revert,
    process_scheduled_sales_price_lists,
    revert_price_list_from_remaris,
)


class ResolveActiveSalesUnitPriceTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.base_list = SalesPriceList.objects.create(
            name="Bazni",
            is_active=True,
            valid_from=self.now - timedelta(days=30),
        )
        self.promo_list = SalesPriceList.objects.create(
            name="Promo",
            is_active=True,
            valid_from=self.now - timedelta(hours=1),
            valid_to=self.now + timedelta(hours=2),
        )
        self.artikl = Artikl.objects.create(name="Pivo", code="PIV01", rm_id=9001)
        SalesPriceItem.objects.create(
            price_list=self.base_list,
            artikl=self.artikl,
            unit_price_gross="5.00",
            is_active=True,
        )
        SalesPriceItem.objects.create(
            price_list=self.promo_list,
            artikl=self.artikl,
            unit_price_gross="3.00",
            is_active=True,
        )

    def test_uses_newer_valid_from_while_promo_active(self):
        price = resolve_active_sales_unit_price(self.artikl.id, at=self.now)
        self.assertEqual(price, Decimal("3.0000"))

    def test_falls_back_after_promo_expires(self):
        after_promo = self.promo_list.valid_to + timedelta(minutes=1)
        price = resolve_active_sales_unit_price(self.artikl.id, at=after_promo)
        self.assertEqual(price, Decimal("5.0000"))


class PriceListScheduleSelectionTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_apply_selection(self):
        due = SalesPriceList.objects.create(
            name="Due apply",
            is_active=True,
            valid_from=self.now - timedelta(minutes=5),
            valid_to=self.now + timedelta(hours=1),
        )
        SalesPriceList.objects.create(
            name="Future",
            is_active=True,
            valid_from=self.now + timedelta(hours=1),
        )
        SalesPriceList.objects.create(
            name="Already applied",
            is_active=True,
            valid_from=self.now - timedelta(hours=2),
            remaris_applied_at=self.now - timedelta(hours=1),
        )

        ids = list(price_lists_due_for_apply(at=self.now).values_list("id", flat=True))
        self.assertEqual(ids, [due.id])

    def test_revert_selection(self):
        due = SalesPriceList.objects.create(
            name="Due revert",
            is_active=True,
            valid_from=self.now - timedelta(hours=2),
            valid_to=self.now - timedelta(minutes=1),
            remaris_applied_at=self.now - timedelta(hours=1),
        )
        SalesPriceList.objects.create(
            name="Not applied yet",
            is_active=True,
            valid_from=self.now - timedelta(hours=2),
            valid_to=self.now - timedelta(minutes=1),
        )

        ids = list(price_lists_due_for_revert(at=self.now).values_list("id", flat=True))
        self.assertEqual(ids, [due.id])

    def test_expired_before_first_poll_not_selected_for_apply_or_revert(self):
        SalesPriceList.objects.create(
            name="Missed promo",
            is_active=True,
            valid_from=self.now - timedelta(hours=5),
            valid_to=self.now - timedelta(hours=1),
        )
        self.assertEqual(price_lists_due_for_apply(at=self.now).count(), 0)
        self.assertEqual(price_lists_due_for_revert(at=self.now).count(), 0)


@patch("sales.pricelist_schedule.transfer_sales_prices_to_pos")
@patch("sales.pricelist_schedule.sync_sales_pricelist_to_remaris")
class ApplyPriceListTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.price_list = SalesPriceList.objects.create(
            name="Promo apply",
            is_active=True,
            valid_from=self.now - timedelta(minutes=1),
            valid_to=self.now + timedelta(hours=1),
        )

    def test_apply_sets_remaris_applied_at(self, mock_sync, mock_transfer):
        mock_sync.return_value = (2, 0, 0)
        mock_transfer.return_value = {"ok": True}

        result = apply_price_list_to_remaris(self.price_list)

        self.assertTrue(result["ok"])
        mock_sync.assert_called_once()
        mock_transfer.assert_called_once()
        self.price_list.refresh_from_db()
        self.assertIsNotNone(self.price_list.remaris_applied_at)
        self.assertIsNone(self.price_list.remaris_reverted_at)

    def test_apply_does_not_mark_on_errors(self, mock_sync, mock_transfer):
        mock_sync.return_value = (1, 0, 1)

        result = apply_price_list_to_remaris(self.price_list)

        self.assertFalse(result["ok"])
        mock_transfer.assert_not_called()
        self.price_list.refresh_from_db()
        self.assertIsNone(self.price_list.remaris_applied_at)


@patch("sales.pricelist_schedule.transfer_sales_prices_to_pos")
@patch("sales.pricelist_schedule.RemarisConnector")
class RevertPriceListTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.base_list = SalesPriceList.objects.create(
            name="Bazni",
            is_active=True,
            valid_from=self.now - timedelta(days=30),
        )
        self.promo_list = SalesPriceList.objects.create(
            name="Promo revert",
            is_active=True,
            valid_from=self.now - timedelta(hours=2),
            valid_to=self.now - timedelta(minutes=1),
            remaris_applied_at=self.now - timedelta(hours=1),
        )
        self.artikl = Artikl.objects.create(name="Pivo", code="PIV02", rm_id=9002)
        SalesPriceItem.objects.create(
            price_list=self.base_list,
            artikl=self.artikl,
            unit_price_gross="5.00",
            is_active=True,
        )
        SalesPriceItem.objects.create(
            price_list=self.promo_list,
            artikl=self.artikl,
            unit_price_gross="3.00",
            is_active=True,
        )

    def test_revert_syncs_effective_base_price(self, mock_connector_cls, mock_transfer):
        connector = MagicMock()
        mock_connector_cls.return_value = connector
        connector.post_json.return_value = {"response": {"status": 0}}
        mock_transfer.return_value = {"ok": True}

        after_promo = self.promo_list.valid_to + timedelta(minutes=1)
        result = revert_price_list_from_remaris(self.promo_list, at=after_promo)

        self.assertTrue(result["ok"])
        self.assertEqual(result["sent"], 1)
        mock_transfer.assert_called_once()
        payload = connector.post_json.call_args[0][1]
        self.assertEqual(payload["data"]["productId"], 9002)
        self.assertEqual(payload["data"]["price"], 5.0)
        self.promo_list.refresh_from_db()
        self.assertIsNotNone(self.promo_list.remaris_reverted_at)
        self.assertIsNone(self.promo_list.remaris_applied_at)


class RecurringPromoScheduleTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_apply_due_when_applied_at_before_current_valid_from(self):
        due = SalesPriceList.objects.create(
            name="Recurring promo",
            is_active=True,
            valid_from=self.now - timedelta(minutes=5),
            valid_to=self.now + timedelta(hours=2),
            remaris_applied_at=self.now - timedelta(days=30),
            remaris_reverted_at=self.now - timedelta(days=29),
        )

        ids = list(price_lists_due_for_apply(at=self.now).values_list("id", flat=True))
        self.assertEqual(ids, [due.id])

    @patch("sales.pricelist_schedule.transfer_sales_prices_to_pos")
    @patch("sales.pricelist_schedule.sync_sales_pricelist_to_remaris", return_value=(1, 0, 0))
    def test_revert_clears_applied_at_for_next_cycle(self, mock_sync, mock_transfer):
        promo = SalesPriceList.objects.create(
            name="Promo cycle",
            is_active=True,
            valid_from=self.now - timedelta(hours=3),
            valid_to=self.now - timedelta(minutes=1),
            remaris_applied_at=self.now - timedelta(hours=2),
        )
        base = SalesPriceList.objects.create(
            name="Bazni",
            is_active=True,
            valid_from=self.now - timedelta(days=30),
            remaris_applied_at=self.now - timedelta(days=1),
        )
        artikl = Artikl.objects.create(name="Pivo", code="PIV03", rm_id=9003)
        SalesPriceItem.objects.create(
            price_list=base,
            artikl=artikl,
            unit_price_gross="5.00",
            is_active=True,
        )
        SalesPriceItem.objects.create(
            price_list=promo,
            artikl=artikl,
            unit_price_gross="3.00",
            is_active=True,
        )

        with patch("sales.pricelist_schedule.RemarisConnector") as mock_connector_cls:
            connector = MagicMock()
            mock_connector_cls.return_value = connector
            connector.post_json.return_value = {"response": {"status": 0}}
            result = revert_price_list_from_remaris(promo, at=self.now)

        self.assertTrue(result["ok"])
        promo.refresh_from_db()
        self.assertIsNotNone(promo.remaris_reverted_at)
        self.assertIsNone(promo.remaris_applied_at)

        promo.valid_from = self.now + timedelta(hours=1)
        promo.valid_to = self.now + timedelta(hours=5)
        promo.remaris_reverted_at = None
        promo.save(update_fields=["valid_from", "valid_to", "remaris_reverted_at"])

        future = self.now + timedelta(minutes=30)
        self.assertNotIn(
            promo.id,
            price_lists_due_for_apply(at=future).values_list("id", flat=True),
        )

        during_next = promo.valid_from + timedelta(minutes=1)
        ids = list(price_lists_due_for_apply(at=during_next).values_list("id", flat=True))
        self.assertEqual(ids, [promo.id])


@patch("sales.pricelist_schedule.revert_price_list_from_remaris")
@patch("sales.pricelist_schedule.apply_price_list_to_remaris")
class ProcessScheduledTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_idempotent_second_run(self, mock_apply, mock_revert):
        SalesPriceList.objects.create(
            name="Applied",
            is_active=True,
            valid_from=self.now - timedelta(hours=1),
            valid_to=self.now + timedelta(hours=1),
            remaris_applied_at=self.now,
        )
        SalesPriceList.objects.create(
            name="Reverted",
            is_active=True,
            valid_from=self.now - timedelta(hours=3),
            valid_to=self.now - timedelta(hours=1),
            remaris_applied_at=self.now - timedelta(hours=2),
            remaris_reverted_at=self.now - timedelta(minutes=30),
        )

        result = process_scheduled_sales_price_lists(at=self.now)

        mock_apply.assert_not_called()
        mock_revert.assert_not_called()
        self.assertEqual(result["applied"], [])
        self.assertEqual(result["reverted"], [])
