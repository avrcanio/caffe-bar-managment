from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import UnitOfMeasureData
from artikli.remaris_connector import RemarisConnector


class Command(BaseCommand):
    help = "Import unit measures from Remaris"

    def handle(self, *args, **options):
        connector = RemarisConnector()
        connector.login()

        payload = {
            "dataSource": "unitOfMeasureDS",
            "operationType": "fetch",
            "operationId": "unitOfMeasureDS_fetch",
            "textMatchStyle": "exact",
            "componentId": "(cacheAllData fetch)",
            "oldValues": None,
            "data": None,
        }

        response = connector.post_json(
            "Product/UnitOfMeasureData?isc_dataFormat=json",
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

                _, was_created = UnitOfMeasureData.objects.update_or_create(
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
