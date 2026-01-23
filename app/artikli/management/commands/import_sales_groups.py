from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import SalesGroupData
from artikli.remaris_connector import RemarisConnector


class Command(BaseCommand):
    help = "Import sales groups from Remaris"

    def handle(self, *args, **options):
        connector = RemarisConnector()
        connector.login()

        payload = {
            "dataSource": "salesGroupDS",
            "operationType": "fetch",
            "operationId": "salesGroupDS_fetch",
            "textMatchStyle": "exact",
            "componentId": "(cacheAllData fetch)",
            "oldValues": None,
            "data": None,
        }

        response = connector.post_json(
            "Product/SalesGroupData?isc_dataFormat=json",
            payload,
            referer_path="/Product",
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

                _, was_created = SalesGroupData.objects.update_or_create(
                    rm_id=rm_id,
                    defaults={"name": name},
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
