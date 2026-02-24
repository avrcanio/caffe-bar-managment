from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from artikli.models import Artikl, DrinkCategory
from configuration.models import TaxGroup


class DrinkCategoryApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="drink-cat-user",
            email="drink-cat@example.com",
            password="pass1234",
            is_staff=False,
        )
        self.staff = User.objects.create_user(
            username="drink-cat-staff",
            email="drink-cat-staff@example.com",
            password="pass1234",
            is_staff=True,
        )
        self.active = DrinkCategory.objects.create(name="Aktivna", is_active=True)
        self.inactive = DrinkCategory.objects.create(name="Neaktivna", is_active=False)
        self.child = DrinkCategory.objects.create(name="Podkategorija", parent=self.active, is_active=True)

    def test_default_list_returns_only_active(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/drink-categories/", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        ids = {row["id"] for row in response.json()}
        self.assertIn(self.active.id, ids)
        self.assertNotIn(self.inactive.id, ids)

    def test_non_staff_cannot_include_inactive(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/drink-categories/?include_inactive=1", secure=True)
        self.assertEqual(response.status_code, 403, response.content)

    def test_staff_can_include_inactive(self):
        self.client.force_authenticate(user=self.staff)
        response = self.client.get("/api/drink-categories/?include_inactive=1", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        ids = {row["id"] for row in response.json()}
        self.assertIn(self.active.id, ids)
        self.assertIn(self.inactive.id, ids)

    def test_can_filter_by_level(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/drink-categories/?level=0", secure=True)
        self.assertEqual(response.status_code, 200, response.content)
        ids = {row["id"] for row in response.json()}
        self.assertIn(self.active.id, ids)
        self.assertNotIn(self.child.id, ids)

    def test_invalid_level_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/drink-categories/?level=abc", secure=True)
        self.assertEqual(response.status_code, 400, response.content)


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
        self.cat_hot = DrinkCategory.objects.create(name="Topli")
        self.cat_soft = DrinkCategory.objects.create(name="Sokovi")
        self.espresso = Artikl.objects.create(
            name="Espresso",
            code="KAVA01",
            is_sellable=True,
            is_stock_item=False,
            drink_category=self.cat_hot,
            tax_group=self.tax_group,
        )
        self.water = Artikl.objects.create(
            name="Voda",
            code="VODA01",
            is_sellable=True,
            is_stock_item=True,
            drink_category=self.cat_soft,
            tax_group=self.tax_group,
        )
        self.internal = Artikl.objects.create(
            name="Interni test",
            code="INT01",
            is_sellable=False,
            is_stock_item=False,
            drink_category=self.cat_hot,
            tax_group=self.tax_group,
        )

    def test_filters_by_drink_category(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f"/api/artikli/?drink_category_id={self.cat_hot.id}", secure=True)
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

    def test_invalid_drink_category_id_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/artikli/?drink_category_id=abc", secure=True)
        self.assertEqual(response.status_code, 400, response.content)

    def test_invalid_boolean_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/artikli/?is_sellable=maybe", secure=True)
        self.assertEqual(response.status_code, 400, response.content)
