from decimal import Decimal

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from artikli.admin import ArtiklPackagingLevelInline, CategoryAdmin
from artikli.models import Artikl, ArtiklPackagingLevel, Category, Deposit, UnitOfMeasureData
from barion.models import BarionCategory
from configuration.models import TaxGroup
from sales.models import SalesInvoice, SalesInvoiceItem



class CategoryAdminTests(TestCase):
    def test_admin_changelist_uses_category_model_name(self):
        self.assertEqual(reverse("admin:artikli_category_changelist"), "/admin/artikli/category/")


class CategoryAdminSortOrderAutomationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="category-admin",
            email="category-admin@example.com",
            password="pass1234",
        )
        self.factory = RequestFactory()
        self.admin_model = CategoryAdmin(Category, site)

    def _build_form(self, *, data, instance=None):
        request = self.factory.post("/admin/artikli/category/")
        request.user = self.admin
        form_class = self.admin_model.get_form(request, obj=instance)
        return form_class(data=data, instance=instance)

    def test_new_root_category_gets_next_1000_block_when_zero(self):
        Category.objects.create(name="Napitci", sort_order=1000)
        Category.objects.create(name="Bezalkoholna pića", sort_order=2000)

        form = self._build_form(
            data={"name": "Alkoholna pića", "parent": "", "sort_order": "0", "is_active": "on"}
        )

        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()
        self.assertEqual(category.sort_order, 3000)

    def test_new_child_category_gets_next_100_block_when_zero(self):
        root = Category.objects.create(name="Bezalkoholna pića", sort_order=2000)
        Category.objects.create(name="Voda", parent=root, sort_order=2100)
        Category.objects.create(name="Sokovi", parent=root, sort_order=2200)

        form = self._build_form(
            data={"name": "Energetska pića", "parent": str(root.pk), "sort_order": "0", "is_active": "on"}
        )

        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()
        self.assertEqual(category.sort_order, 2300)

    def test_new_grandchild_category_gets_next_10_block_when_zero(self):
        root = Category.objects.create(name="Bezalkoholna pića", sort_order=2000)
        parent = Category.objects.create(name="Voda", parent=root, sort_order=2100)
        Category.objects.create(name="Negazirana voda", parent=parent, sort_order=2110)
        Category.objects.create(name="Gazirana voda", parent=parent, sort_order=2120)

        form = self._build_form(
            data={"name": "Aromatizirana voda", "parent": str(parent.pk), "sort_order": "0", "is_active": "on"}
        )

        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()
        self.assertEqual(category.sort_order, 2130)

    def test_new_deeper_category_gets_next_plus_one_when_zero(self):
        root = Category.objects.create(name="Napitci", sort_order=1000)
        level1 = Category.objects.create(name="Topli napici", parent=root, sort_order=1100)
        level2 = Category.objects.create(name="Kave", parent=level1, sort_order=1110)
        level3 = Category.objects.create(name="Espresso", parent=level2, sort_order=1111)
        Category.objects.create(name="Dupli espresso", parent=level3, sort_order=1112)

        form = self._build_form(
            data={"name": "Espresso bez kofeina", "parent": str(level3.pk), "sort_order": "0", "is_active": "on"}
        )

        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()
        self.assertEqual(category.sort_order, 1113)

    def test_manual_positive_sort_order_is_preserved(self):
        root = Category.objects.create(name="Bezalkoholna pića", sort_order=2000)

        form = self._build_form(
            data={"name": "Voda", "parent": str(root.pk), "sort_order": "2450", "is_active": "on"}
        )

        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()
        self.assertEqual(category.sort_order, 2450)

    def test_parent_change_with_zero_recomputes_block(self):
        root = Category.objects.create(name="Bezalkoholna pića", sort_order=2000)
        voda = Category.objects.create(name="Voda", parent=root, sort_order=2100)
        sokovi = Category.objects.create(name="Sokovi", parent=root, sort_order=2200)
        Category.objects.create(name="Negazirana voda", parent=voda, sort_order=2110)
        Category.objects.create(name="Gazirana voda", parent=voda, sort_order=2120)
        Category.objects.create(name="Cijeđeni sokovi", parent=sokovi, sort_order=2210)
        category = Category.objects.create(name="Test", parent=voda, sort_order=2130)

        form = self._build_form(
            instance=category,
            data={"name": category.name, "parent": str(sokovi.pk), "sort_order": "0", "is_active": "on"},
        )

        self.assertTrue(form.is_valid(), form.errors)
        updated = form.save()
        self.assertEqual(updated.sort_order, 2220)

    def test_tree_order_follows_auto_sort_order_for_siblings(self):
        root = Category.objects.create(name="Bezalkoholna pića", sort_order=2000)
        voda = Category.objects.create(name="Voda", parent=root, sort_order=2100)
        Category.objects.create(name="Gazirana voda", parent=voda, sort_order=2120)

        form = self._build_form(
            data={"name": "Negazirana voda", "parent": str(voda.pk), "sort_order": "0", "is_active": "on"}
        )

        self.assertTrue(form.is_valid(), form.errors)
        created = form.save()
        siblings = list(Category.objects.filter(parent=voda).order_by("tree_id", "lft").values_list("name", flat=True))
        self.assertEqual(created.sort_order, 2130)
        self.assertEqual(siblings, ["Gazirana voda", "Negazirana voda"])


class ArtiklListFilterApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="artikli-filter-user",
            email="artikli-filter@example.com",
            password="pass1234",
        )
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
        self.cat_hot = Category.objects.create(name="Topli")
        self.cat_soft = Category.objects.create(name="Sokovi")
        self.espresso = Artikl.objects.create(
            rm_id=1001,
            name="Espresso",
            code="KAVA01",
            is_sellable=True,
            is_stock_item=False,
            category=self.cat_hot,
            tax_group=self.tax_group,
        )
        self.water = Artikl.objects.create(
            rm_id=1002,
            name="Voda",
            code="VODA01",
            is_sellable=True,
            is_stock_item=True,
            category=self.cat_soft,
            tax_group=self.tax_group,
        )
        self.internal = Artikl.objects.create(
            rm_id=1003,
            name="Interni test",
            code="INT01",
            is_sellable=False,
            is_stock_item=False,
            category=self.cat_hot,
            tax_group=self.tax_group,
        )
        self.packaging_uom = UnitOfMeasureData.objects.create(rm_id=2001, name="Komad")

    def test_filters_by_category(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/artikli/?category_id={self.cat_hot.id}", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        names = {row["name"] for row in response.json()}
        self.assertIn("Espresso", names)
        self.assertIn("Interni test", names)
        self.assertNotIn("Voda", names)

    def test_filters_by_query(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/artikli/?q=voda", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["name"], "Voda")

    def test_filters_by_is_sellable(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/artikli/?is_sellable=1", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        names = {row["name"] for row in response.json()}
        self.assertIn("Espresso", names)
        self.assertIn("Voda", names)
        self.assertNotIn("Interni test", names)

    def test_filters_by_is_stock_item(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/artikli/?is_stock_item=true", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["name"], "Voda")

    def test_invalid_category_id_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/artikli/?category_id=abc", secure=True)
        self.assertEqual(response.status_code, 400, response.content)

    def test_invalid_boolean_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/artikli/?is_sellable=maybe", secure=True)
        self.assertEqual(response.status_code, 400, response.content)

    def test_list_includes_vat_rate_and_deposit_amount(self):
        deposit = Deposit.objects.create(amount_eur=Decimal("0.10"))
        bottled = Artikl.objects.create(
            rm_id=1004,
            name="Sok boca",
            code="SOK01",
            is_sellable=True,
            is_stock_item=True,
            category=self.cat_soft,
            tax_group=self.tax_group,
            deposit=deposit,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/artikli/", secure=True)

        self.assertEqual(response.status_code, 200, response.content)
        row = next(item for item in response.json() if item["rm_id"] == bottled.rm_id)
        self.assertEqual(row["vat_rate"], 0.25)
        self.assertEqual(row["deposit_amount"], 0.1)
        self.assertEqual(row["category_sort_order"], self.cat_soft.sort_order)

    def test_detail_includes_vat_rate_and_zero_deposit_when_missing(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/artikli/{self.espresso.rm_id}/", secure=True)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["vat_rate"], 0.25)
        self.assertEqual(body["deposit_amount"], 0)
        self.assertEqual(body["category_sort_order"], self.cat_hot.sort_order)

    def test_detail_includes_packaging_levels_sorted(self):
        ArtiklPackagingLevel.objects.create(
            artikl=self.espresso,
            sort_order=0,
            unit_of_measure=self.packaging_uom,
        )
        pallet_uom = UnitOfMeasureData.objects.create(rm_id=2002, name="Paleta")
        crate_uom = UnitOfMeasureData.objects.create(rm_id=2003, name="Gajba")
        ArtiklPackagingLevel.objects.create(
            artikl=self.espresso,
            sort_order=2,
            unit_of_measure=pallet_uom,
            contains_previous=Decimal("60.0000"),
        )
        ArtiklPackagingLevel.objects.create(
            artikl=self.espresso,
            sort_order=1,
            unit_of_measure=crate_uom,
            contains_previous=Decimal("24.0000"),
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/artikli/{self.espresso.rm_id}/", secure=True)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["packaging_path"], "komad -> 24/gajba -> 60/paleta")
        self.assertEqual([row["unit_name"] for row in body["packaging_levels"]], ["Komad", "Gajba", "Paleta"])


class ArtiklPackagingLevelModelTests(TestCase):
    def setUp(self):
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
        self.artikl = Artikl.objects.create(
            rm_id=3001,
            name="Ozujsko 0,33",
            code="OZU033",
            is_sellable=True,
            is_stock_item=True,
            tax_group=self.tax_group,
        )

    def test_valid_linear_packaging_path_saves(self):
        base = ArtiklPackagingLevel(
            artikl=self.artikl,
            sort_order=0,
            unit_of_measure=UnitOfMeasureData.objects.create(rm_id=3001, name="Komad"),
        )
        crate = ArtiklPackagingLevel(
            artikl=self.artikl,
            sort_order=1,
            unit_of_measure=UnitOfMeasureData.objects.create(rm_id=3002, name="Gajba"),
            contains_previous=Decimal("24.0000"),
        )
        pallet = ArtiklPackagingLevel(
            artikl=self.artikl,
            sort_order=2,
            unit_of_measure=UnitOfMeasureData.objects.create(rm_id=3003, name="Paleta"),
            contains_previous=Decimal("60.0000"),
        )

        for level in (base, crate, pallet):
            level.full_clean()
            level.save()

        self.assertEqual(self.artikl.packaging_path_summary(), "komad -> 24/gajba -> 60/paleta")

    def test_duplicate_sort_order_is_rejected(self):
        ArtiklPackagingLevel.objects.create(
            artikl=self.artikl,
            sort_order=0,
            unit_of_measure=UnitOfMeasureData.objects.create(rm_id=3011, name="Komad"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ArtiklPackagingLevel.objects.create(
                    artikl=self.artikl,
                    sort_order=0,
                    unit_of_measure=UnitOfMeasureData.objects.create(rm_id=3012, name="Komad 2"),
                )

    def test_non_first_level_requires_positive_contains_previous(self):
        level = ArtiklPackagingLevel(
            artikl=self.artikl,
            sort_order=1,
            unit_of_measure=UnitOfMeasureData.objects.create(rm_id=3021, name="Gajba"),
            contains_previous=Decimal("0.0000"),
        )

        with self.assertRaises(ValidationError):
            level.full_clean()

    def test_first_level_does_not_require_contains_previous(self):
        level = ArtiklPackagingLevel(
            artikl=self.artikl,
            sort_order=0,
            unit_of_measure=UnitOfMeasureData.objects.create(rm_id=3031, name="Komad"),
        )

        level.full_clean()


class ArtiklPackagingLevelAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="artikli-packaging-admin",
            email="artikli-packaging-admin@example.com",
            password="pass1234",
        )
        self.factory = RequestFactory()
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
        self.artikl = Artikl.objects.create(
            rm_id=4001,
            name="Ozujsko 0,5",
            code="OZU05",
            tax_group=self.tax_group,
        )
        self.komad = UnitOfMeasureData.objects.create(rm_id=4001, name="Komad")
        self.gajba = UnitOfMeasureData.objects.create(rm_id=4002, name="Gajba")

    def test_admin_change_saves_packaging_inline(self):
        request = self.factory.post(
            reverse("admin:artikli_artikl_change", args=[self.artikl.pk]),
            {
                "rm_id": self.artikl.rm_id,
                "code": self.artikl.code,
                "name": self.artikl.name,
                "tax_group": self.tax_group.pk,
                "packaging_levels-TOTAL_FORMS": "2",
                "packaging_levels-INITIAL_FORMS": "0",
                "packaging_levels-MIN_NUM_FORMS": "0",
                "packaging_levels-MAX_NUM_FORMS": "1000",
                "packaging_levels-0-sort_order": "0",
                "packaging_levels-0-unit_of_measure": str(self.komad.pk),
                "packaging_levels-0-contains_previous": "",
                "packaging_levels-1-sort_order": "1",
                "packaging_levels-1-unit_of_measure": str(self.gajba.pk),
                "packaging_levels-1-contains_previous": "24",
            },
        )
        request.user = self.admin

        inline = ArtiklPackagingLevelInline(Artikl, site)
        formset_class = inline.get_formset(request, self.artikl)
        formset = formset_class(data=request.POST, instance=self.artikl, prefix="packaging_levels")

        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()
        self.artikl.refresh_from_db()
        self.assertEqual(self.artikl.packaging_levels.count(), 2)
        self.assertEqual(self.artikl.packaging_path_summary(), "komad -> 24/gajba")


class ArtiklAdminCategoryFilterTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="artikli-admin",
            email="artikli-admin@example.com",
            password="pass1234",
        )
        self.client = Client(HTTP_HOST="mozart.sibenik1983.hr")
        self.client.force_login(self.admin)

    def test_stale_category_tree_filter_does_not_raise_500(self):
        response = self.client.get(
            "/admin/artikli/artikl/?category__id__inhierarchy=999999",
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)


class CategoryAdminAutocompleteTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="artikli-autocomplete-admin",
            email="artikli-autocomplete-admin@example.com",
            password="pass1234",
        )
        self.client = Client(HTTP_HOST="mozart.sibenik1983.hr")
        self.client.force_login(self.admin)
        self.used_category = Category.objects.create(name="Whiskey")
        self.free_category = Category.objects.create(name="Vodka")
        BarionCategory.objects.create(category=self.used_category, sort_order=1)

    def test_barion_category_autocomplete_hides_already_selected_categories(self):
        response = self.client.get(
            reverse("admin:autocomplete"),
            {
                "app_label": "barion",
                "model_name": "barioncategory",
                "field_name": "category",
                "term": "",
            },
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        names = {row["text"] for row in response.json()["results"]}
        self.assertNotIn(self.used_category.name, names)
        self.assertIn(self.free_category.name, names)

    def test_non_barion_category_autocomplete_keeps_all_categories_visible(self):
        response = self.client.get(
            reverse("admin:autocomplete"),
            {
                "app_label": "artikli",
                "model_name": "artikl",
                "field_name": "category",
                "term": "",
            },
            secure=True,
        )
        self.assertEqual(response.status_code, 200, response.content)
        names = {row["text"] for row in response.json()["results"]}
        self.assertIn(self.used_category.name, names)
        self.assertIn(self.free_category.name, names)


class CategoryApiRouteTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="artikli-category-api-user",
            email="artikli-category-api@example.com",
            password="pass1234",
        )
        self.client = APIClient()
        self.root = Category.objects.create(name="Cigarete", is_active=True, sort_order=0)

    def test_categories_endpoint_returns_200(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/categories/", secure=True)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()[0]["name"], self.root.name)

    def test_drink_categories_endpoint_returns_404(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/drink-categories/", secure=True)

        self.assertEqual(response.status_code, 404, response.content)


class CategorySortOrderBySalesCommandTests(TestCase):
    def setUp(self):
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")

        root_drinks = Category.objects.create(name="Napitci", sort_order=10)
        self.lvl2_hot = Category.objects.create(name="Topli napici", parent=root_drinks, sort_order=10)
        self.lvl2_soft = Category.objects.create(name="Hladni napici", parent=root_drinks, sort_order=20)
        self.lvl3_coffee = Category.objects.create(name="Kave", parent=self.lvl2_hot, sort_order=10)
        lvl3_soda = Category.objects.create(name="Gazirana pića", parent=self.lvl2_soft, sort_order=10)

        root_alcohol = Category.objects.create(name="Alkoholna pića", sort_order=30)
        self.lvl2_beer = Category.objects.create(name="Pivo", parent=root_alcohol, sort_order=30)
        self.lvl3_light_beer = Category.objects.create(
            name="Svijetlo pivo",
            parent=self.lvl2_beer,
            sort_order=10,
        )

        self.art_1163 = Artikl.objects.create(
            name="KAVA SA MLIJEKOM VELIKA",
            code="1163",
            tax_group=self.tax_group,
            category=Category.objects.create(
                name="Kava sa mlijekom velika",
                parent=Category.objects.create(
                    name="Kava sa mlijekom",
                    parent=self.lvl3_coffee,
                    sort_order=10,
                ),
                sort_order=10,
            ),
        )
        self.art_1162 = Artikl.objects.create(
            name="KAVA ESPRESSO",
            code="1162",
            tax_group=self.tax_group,
            category=Category.objects.create(
                name="Kava espresso",
                parent=self.lvl3_coffee,
                sort_order=20,
            ),
        )
        self.art_169 = Artikl.objects.create(
            name="Ožujsko pivo 0,33l",
            code="169",
            tax_group=self.tax_group,
            category=Category.objects.create(
                name="Ožujsko pivo 0,33l",
                parent=self.lvl3_light_beer,
                sort_order=10,
            ),
        )

        invoice = SalesInvoice.objects.create(
            rm_number=1001,
            issued_on=timezone.localdate(),
            issued_at=timezone.now(),
        )
        SalesInvoiceItem.objects.create(
            invoice=invoice,
            artikl=self.art_1163,
            product_name=self.art_1163.name,
            quantity=Decimal("1782.0000"),
            amount=Decimal("0.00"),
        )
        SalesInvoiceItem.objects.create(
            invoice=invoice,
            artikl=self.art_1162,
            product_name=self.art_1162.name,
            quantity=Decimal("895.0000"),
            amount=Decimal("0.00"),
        )
        SalesInvoiceItem.objects.create(
            invoice=invoice,
            artikl=self.art_169,
            product_name=self.art_169.name,
            quantity=Decimal("633.0000"),
            amount=Decimal("0.00"),
        )

    def test_command_orders_level2_categories_by_sales(self):
        call_command("reorder_categories_by_sales", days=30)

        self.lvl2_hot.refresh_from_db()
        self.lvl3_coffee.refresh_from_db()
        self.lvl3_light_beer.refresh_from_db()
        self.lvl2_soft.refresh_from_db()

        self.assertEqual(self.lvl3_coffee.sort_order, 1)
        self.assertEqual(self.lvl3_light_beer.sort_order, 2)
        # Kategorija bez prodaje ostaje kako je bila.
        self.assertEqual(self.lvl2_soft.sort_order, 20)
        # Level 1 kategorija ne smije biti target kod target_level=2.
        self.assertEqual(self.lvl2_hot.sort_order, 10)
