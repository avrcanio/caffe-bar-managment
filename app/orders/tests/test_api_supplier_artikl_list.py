import io
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from rest_framework.test import APIClient

from artikli.models import Artikl, Category, UnitOfMeasureData
from configuration.models import TaxGroup
from contacts.models import Supplier
from orders.models import SupplierPriceItem, SupplierPriceList


def _uploaded_test_image(*, size: tuple[int, int] = (600, 900)) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color=(240, 120, 40))
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return SimpleUploadedFile("test-artikl.png", buffer.getvalue(), content_type="image/png")


class SupplierArtiklListApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="supplier-artikli-admin",
            email="supplier-artikli-admin@example.com",
            password="pass",
        )
        self.client.force_authenticate(user=self.user)

        self.supplier = Supplier.objects.create(rm_id=101, name="Demo dobavljac")
        self.tax_group = TaxGroup.objects.create(name="PDV 25", code="PDV25", rate="0.2500")
        self.unit = UnitOfMeasureData.objects.create(rm_id=1, name="kom")

        self.root_category = Category.objects.create(name="Pica", sort_order=10)
        self.child_category = Category.objects.create(
            name="Bezalkoholna",
            parent=self.root_category,
            sort_order=10,
        )
        self.leaf_category = Category.objects.create(
            name="Sokovi",
            parent=self.child_category,
            sort_order=10,
        )

    def test_supplier_artikli_returns_latest_valid_price_with_category_path_and_image_50x75(self):
        artikl = Artikl.objects.create(
            rm_id=501,
            code="ART-501",
            name="Sok naranca",
            tax_group=self.tax_group,
            category=self.leaf_category,
            image=_uploaded_test_image(),
        )

        older_price_list = SupplierPriceList.objects.create(
            supplier=self.supplier,
            name="Stari cjenik",
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            is_active=True,
        )
        newer_price_list = SupplierPriceList.objects.create(
            supplier=self.supplier,
            name="Novi cjenik",
            valid_from=date(2026, 3, 1),
            valid_to=date(2026, 12, 31),
            is_active=True,
        )

        SupplierPriceItem.objects.create(
            price_list=older_price_list,
            artikl=artikl,
            unit_of_measure=self.unit,
            price="2.10",
        )
        SupplierPriceItem.objects.create(
            price_list=newer_price_list,
            artikl=artikl,
            unit_of_measure=self.unit,
            price="2.80",
        )

        response = self.client.get(
            f"/api/suppliers/{self.supplier.id}/artikli/?ordered_at=2026-04-15T10:00:00Z",
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        row = payload["results"][0]
        self.assertEqual(row["price"], 2.8)
        self.assertEqual(row["category_id"], self.leaf_category.id)
        self.assertEqual(row["category_name"], "Sokovi")
        self.assertEqual(row["category_path"], ["Pica", "Bezalkoholna", "Sokovi"])
        self.assertTrue(row["image_50x75"].endswith(f"/api/artikli/{artikl.rm_id}/image-50x75/"))

        thumb_response = self.client.get(f"/api/artikli/{artikl.rm_id}/image-50x75/", secure=True)
        self.assertEqual(thumb_response.status_code, 200)
        thumb_image = Image.open(io.BytesIO(thumb_response.content))
        self.assertEqual(thumb_image.size, (50, 75))

    def test_supplier_artikli_uses_created_at_tiebreaker_and_fallback_category_label(self):
        artikl = Artikl.objects.create(
            rm_id=777,
            code="ART-777",
            name="Bez kategorije",
            tax_group=self.tax_group,
        )

        early = SupplierPriceList.objects.create(
            supplier=self.supplier,
            name="Cjenik A",
            valid_from=date(2026, 4, 1),
            valid_to=date(2026, 4, 30),
            is_active=True,
        )
        late = SupplierPriceList.objects.create(
            supplier=self.supplier,
            name="Cjenik B",
            valid_from=date(2026, 4, 1),
            valid_to=date(2026, 4, 30),
            is_active=True,
        )
        SupplierPriceList.objects.filter(pk=early.pk).update(created_at="2026-04-01T08:00:00Z")
        SupplierPriceList.objects.filter(pk=late.pk).update(created_at="2026-04-01T09:00:00Z")

        SupplierPriceItem.objects.create(
            price_list=early,
            artikl=artikl,
            unit_of_measure=self.unit,
            price="5.00",
        )
        SupplierPriceItem.objects.create(
            price_list=late,
            artikl=artikl,
            unit_of_measure=self.unit,
            price="5.50",
        )

        response = self.client.get(
            f"/api/suppliers/{self.supplier.id}/artikli/?ordered_at=2026-04-15T10:00:00Z",
            secure=True,
        )

        self.assertEqual(response.status_code, 200, response.json())
        row = response.json()["results"][0]
        self.assertEqual(row["price"], 5.5)
        self.assertIsNone(row["category_id"])
        self.assertIsNone(row["category_name"])
        self.assertEqual(row["category_path"], [])
        self.assertIsNone(row["image_50x75"])
