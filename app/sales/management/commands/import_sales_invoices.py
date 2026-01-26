from datetime import date as date_cls

from django.core.management.base import BaseCommand, CommandError

from sales.remaris_importer import import_sales_invoices, load_import_defaults


class Command(BaseCommand):
    help = "Import Remaris sales invoices (Excel report)."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="date_from", required=True)
        parser.add_argument("--to", dest="date_to", required=True)
        parser.add_argument("--organization-id", type=int)
        parser.add_argument("--location-id", type=int)
        parser.add_argument("--pos-id", type=int)
        parser.add_argument("--currency")
        parser.add_argument("--warehouse-id", type=int)

    def handle(self, *args, **options):
        try:
            date_from = date_cls.fromisoformat(options["date_from"])
            date_to = date_cls.fromisoformat(options["date_to"])
        except ValueError as exc:
            raise CommandError("Dates must be in YYYY-MM-DD format.") from exc

        defaults = load_import_defaults()
        for key in ("organization_id", "location_id", "pos_id", "currency", "warehouse_id"):
            if options.get(key) is not None:
                defaults[key] = options[key]

        created, updated, skipped = import_sales_invoices(
            date_from=date_from,
            date_to=date_to,
            **defaults,
        )
        self.stdout.write(
            f"Import complete. created={created} updated={updated} skipped={skipped}"
        )
