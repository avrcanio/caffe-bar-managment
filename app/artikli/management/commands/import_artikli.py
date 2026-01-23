import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import Artikl


class Command(BaseCommand):
    help = "Import artikli from product.json"

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="/app/product.json",
            help="Path to product.json",
        )

    def handle(self, *args, **options):
        path = Path(options["path"]).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        payload = json.loads(path.read_text(encoding="utf-8"))
        data = payload.get("response", {}).get("data", [])

        created = 0
        updated = 0

        with transaction.atomic():
            for item in data:
                rm_id = item.get("id")
                name = item.get("name")
                code = item.get("code")
                if rm_id is None or name is None or code is None:
                    continue

                obj, was_created = Artikl.objects.update_or_create(
                    rm_id=rm_id,
                    defaults={"name": name, "code": code},
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete. created={created} updated={updated}"
            )
        )
