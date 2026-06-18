from django.test import TestCase

from artikli.models import Artikl
from sales.product_artikl_resolution import (
    build_artikl_lookup,
    normalize_product_name,
    resolve_artikl_id,
)


class ProductArtiklResolutionTests(TestCase):
    def setUp(self):
        self.corona = Artikl.objects.create(
            name="Corona extra 0,355 l",
            code="75032814",
            rm_id=75032814,
        )

    def test_normalize_comma_dot_equivalent(self):
        self.assertEqual(
            normalize_product_name("Corona extra 0.355 l"),
            normalize_product_name("Corona extra 0,355 l"),
        )

    def test_resolve_corona_remaris_product_name(self):
        lookup = build_artikl_lookup()
        self.assertEqual(
            resolve_artikl_id("Corona extra 0.355 l", lookup=lookup),
            self.corona.id,
        )
