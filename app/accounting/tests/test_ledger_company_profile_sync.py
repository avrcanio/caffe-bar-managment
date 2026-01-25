from django.test import TestCase

from accounting.models import Ledger
from configuration.models import CompanyProfile


class LedgerCompanyProfileSyncTests(TestCase):
    def test_ledger_syncs_name_and_oib_on_save(self):
        profile = CompanyProfile.objects.create(name="Mozart d.o.o.", oib="12345678901")

        ledger = Ledger.objects.create(
            name="Krivo ime",
            oib="",
            company_profile=profile,
        )

        self.assertEqual(ledger.name, "Mozart d.o.o.")
        self.assertEqual(ledger.oib, "12345678901")

    def test_ledger_updates_from_profile_changes(self):
        profile = CompanyProfile.objects.create(name="Mozart d.o.o.", oib="12345678901")
        ledger = Ledger.objects.create(name="Init", oib="", company_profile=profile)

        profile.name = "Mozart Bar d.o.o."
        profile.oib = "10987654321"
        profile.save(update_fields=["name", "oib"])

        ledger.save()
        ledger.refresh_from_db()

        self.assertEqual(ledger.name, "Mozart Bar d.o.o.")
        self.assertEqual(ledger.oib, "10987654321")
