from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.remaris_connector import RemarisConnector
from contacts.models import Stuff


class Command(BaseCommand):
    help = "Import contacts from Remaris"

    def handle(self, *args, **options):
        connector = RemarisConnector()
        connector.login()

        payload = {
            "dataSource": "contactGridDS",
            "operationType": "fetch",
            "startRow": 0,
            "endRow": 75,
            "sortBy": ["name"],
            "textMatchStyle": "exact",
            "componentId": "contactGrid",
            "oldValues": None,
            "data": {"type": 1, "activeFilter": 3},
        }

        response = connector.post_json(
            "Contact/GetData?isc_dataFormat=json",
            payload,
            referer_path="/Contact",
        )

        data = response.get("response", {}).get("data", [])

        created = 0
        updated = 0
        skipped = 0

        with transaction.atomic():
            for item in data:
                rm_id = item.get("id")
                name = item.get("name")
                if rm_id is None or name is None:
                    skipped += 1
                    continue

                defaults = {
                    "name": name,
                    "name2": item.get("name2", ""),
                    "card_number": item.get("cardNumber", ""),
                    "tax_number": item.get("taxNumber", ""),
                }

                _, was_created = Stuff.objects.update_or_create(
                    rm_id=rm_id,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete. created={created} updated={updated} skipped={skipped}"
            )
        )
