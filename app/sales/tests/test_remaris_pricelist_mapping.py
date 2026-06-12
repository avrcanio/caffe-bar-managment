from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.utils import timezone

from artikli.models import Artikl
from sales.admin import SalesPriceListAdmin, sync_sales_pricelist_to_remaris_action
from sales.models import SalesPriceItem, SalesPriceList
from sales.pricelist_schedule import apply_price_list_to_remaris, price_lists_due_for_apply
from sales.remaris_pricelist import (
    DEFAULT_REMARIS_PRICE_LIST_ID,
    resolve_remaris_price_list_id,
    sync_sales_pricelist_to_remaris,
)


class ResolveRemarisPriceListIdTests(TestCase):
    def test_fallback_to_default_when_unset(self):
        price_list = SalesPriceList(name="Bazni", valid_from=timezone.now())
        self.assertEqual(
            resolve_remaris_price_list_id(price_list),
            DEFAULT_REMARIS_PRICE_LIST_ID,
        )

    def test_uses_explicit_remaris_id(self):
        price_list = SalesPriceList(
            name="Koncert",
            valid_from=timezone.now(),
            remaris_price_list_id=9,
        )
        self.assertEqual(resolve_remaris_price_list_id(price_list), 9)


class KoncertScheduleSelectionTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_koncert_excluded_from_scheduled_apply(self):
        SalesPriceList.objects.create(
            name="Koncert",
            is_active=True,
            valid_from=self.now,
            remaris_price_list_id=9,
            remaris_sync_transfer_pos=False,
        )
        due = SalesPriceList.objects.create(
            name="Promo",
            is_active=True,
            valid_from=self.now - timezone.timedelta(minutes=5),
            remaris_price_list_id=10,
            remaris_sync_transfer_pos=True,
        )

        ids = list(price_lists_due_for_apply(at=self.now).values_list("id", flat=True))
        self.assertIn(due.id, ids)
        self.assertEqual(len(ids), 1)


@patch("sales.remaris_pricelist.save_remaris_product_price", return_value=True)
@patch("sales.remaris_pricelist.RemarisConnector")
class SyncSalesPricelistMappingTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.artikl = Artikl.objects.create(
            name="Madri Excepcional 0,4l",
            code="8600105005867",
            rm_id=1410,
        )
        self.koncert_list = SalesPriceList.objects.create(
            name="Koncert",
            is_active=True,
            valid_from=self.now,
            remaris_price_list_id=9,
            remaris_sync_transfer_pos=False,
        )
        SalesPriceItem.objects.create(
            price_list=self.koncert_list,
            artikl=self.artikl,
            unit_price_gross=Decimal("5.30"),
            is_active=True,
        )

    def test_sync_uses_koncert_remaris_id(self, mock_connector_cls, mock_save_price):
        mock_connector_cls.return_value.login = MagicMock()

        sent, skipped, errors = sync_sales_pricelist_to_remaris(
            price_list=self.koncert_list,
            dry_run=False,
        )

        self.assertEqual(sent, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(errors, 0)
        mock_save_price.assert_called_once()
        self.assertEqual(mock_save_price.call_args.kwargs["remaris_price_list_id"], 9)
        self.assertEqual(mock_save_price.call_args.kwargs["price_value"], Decimal("5.30"))


@patch("sales.admin.transfer_sales_prices_to_pos")
@patch("sales.admin.sync_sales_pricelist_to_remaris", return_value=(1, 0, 0))
class AdminSyncActionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="remaris-sync-admin",
            email="remaris-sync-admin@example.com",
            password="pass",
        )
        self.site = AdminSite()
        self.now = timezone.now()
        self.koncert_list = SalesPriceList.objects.create(
            name="Koncert",
            is_active=True,
            valid_from=self.now,
            remaris_price_list_id=9,
            remaris_sync_transfer_pos=False,
        )

    def _request(self):
        request = self.factory.post("/admin/")
        request.user = self.user
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        request._messages = FallbackStorage(request)
        return request

    def test_koncert_sync_skips_pos_transfer(self, mock_sync, mock_transfer):
        request = self._request()
        queryset = SalesPriceList.objects.filter(pk=self.koncert_list.pk)

        sync_sales_pricelist_to_remaris_action(
            SalesPriceListAdmin(SalesPriceList, self.site),
            request,
            queryset,
        )

        mock_sync.assert_called_once()
        self.assertEqual(
            mock_sync.call_args.kwargs["remaris_price_list_id"],
            9,
        )
        mock_transfer.assert_not_called()


@patch("sales.pricelist_schedule.transfer_sales_prices_to_pos")
@patch("sales.pricelist_schedule.sync_sales_pricelist_to_remaris", return_value=(1, 0, 0))
class ApplyPriceListTransferTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_koncert_apply_skips_pos_transfer(self, mock_sync, mock_transfer):
        koncert = SalesPriceList.objects.create(
            name="Koncert",
            is_active=True,
            valid_from=self.now,
            remaris_price_list_id=9,
            remaris_sync_transfer_pos=False,
        )

        result = apply_price_list_to_remaris(koncert)

        self.assertTrue(result["ok"])
        mock_sync.assert_called_once()
        self.assertEqual(mock_sync.call_args.kwargs["remaris_price_list_id"], 9)
        mock_transfer.assert_not_called()

    def test_promo_apply_runs_pos_transfer(self, mock_sync, mock_transfer):
        promo = SalesPriceList.objects.create(
            name="Promo",
            is_active=True,
            valid_from=self.now,
            remaris_price_list_id=10,
            remaris_sync_transfer_pos=True,
        )

        result = apply_price_list_to_remaris(promo)

        self.assertTrue(result["ok"])
        mock_transfer.assert_called_once()
