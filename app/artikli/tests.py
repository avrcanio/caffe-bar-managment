from decimal import Decimal

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from artikli.models import Artikl, Category, Deposit
from barion.models import BarionCategory
from configuration.models import TaxGroup
from sales.models import SalesInvoice, SalesInvoiceItem



class CategoryAdminTests(TestCase):
    def test_admin_changelist_uses_category_model_name(self):
        self.assertEqual(reverse("admin:artikli_category_changelist"), "/admin/artikli/category/")


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
