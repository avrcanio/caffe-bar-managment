from decimal import Decimal

from django.test import TestCase

from artikli.models import Artikl, ArtiklDetail, UnitOfMeasureData
from configuration.models import TaxGroup
from contacts.models import Supplier
from orders.admin import SupplierPriceItemAdminForm
from orders.models import SupplierPriceList


class SupplierPriceItemAdminFormTests(TestCase):
    def setUp(self):
        self.tax_group = TaxGroup.objects.create(
            name="PDV 25",
            code="PDV25",
            rate=Decimal("0.2500"),
        )
        self.supplier = Supplier.objects.create(rm_id=501, name="Test Supplier")
        self.price_list = SupplierPriceList.objects.create(supplier=self.supplier)

        self.default_uom = UnitOfMeasureData.objects.create(rm_id=1001, name="kom")
        self.explicit_uom = UnitOfMeasureData.objects.create(rm_id=1002, name="kg")

        self.artikl_with_default_uom = Artikl.objects.create(
            name="Artikl with default UoM",
            code="A-DEFAULT",
            tax_group=self.tax_group,
        )
        ArtiklDetail.objects.create(
            artikl=self.artikl_with_default_uom,
            rm_id=9001,
            name="Artikl with default UoM",
            code="A-DEFAULT",
            unit_of_measure=self.default_uom,
        )

        self.artikl_without_default_uom = Artikl.objects.create(
            name="Artikl without default UoM",
            code="A-NO-UOM",
            tax_group=self.tax_group,
        )
        ArtiklDetail.objects.create(
            artikl=self.artikl_without_default_uom,
            rm_id=9002,
            name="Artikl without default UoM",
            code="A-NO-UOM",
        )

    def _build_form(self, *, artikl_id, unit_of_measure):
        return SupplierPriceItemAdminForm(
            data={
                "price_list": self.price_list.id,
                "artikl": artikl_id,
                "unit_of_measure": unit_of_measure,
                "price": "12.34",
            }
        )

    def test_empty_unit_of_measure_is_filled_from_artikl_default(self):
        form = self._build_form(
            artikl_id=self.artikl_with_default_uom.id,
            unit_of_measure="",
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["unit_of_measure"], self.default_uom)

    def test_empty_unit_of_measure_without_artikl_default_returns_validation_error(self):
        form = self._build_form(
            artikl_id=self.artikl_without_default_uom.id,
            unit_of_measure="",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("unit_of_measure", form.errors)
        self.assertIn(
            "Odaberite jedinicu mjere ili postavite zadanu na artiklu.",
            form.errors["unit_of_measure"],
        )

    def test_explicit_unit_of_measure_is_preserved(self):
        form = self._build_form(
            artikl_id=self.artikl_with_default_uom.id,
            unit_of_measure=self.explicit_uom.pk,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["unit_of_measure"], self.explicit_uom)
