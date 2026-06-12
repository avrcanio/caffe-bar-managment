from django.core.management.base import BaseCommand, CommandError

from sales.models import SalesPriceList
from sales.remaris_pricelist import (
    resolve_remaris_price_list_id,
    sync_sales_pricelist_to_remaris,
)


class Command(BaseCommand):
    help = "Sync sales price list items to Remaris (one update per item)."

    def add_arguments(self, parser):
        parser.add_argument("--price-list-id", type=int, required=True)
        parser.add_argument(
            "--remaris-price-list-id",
            type=int,
            required=False,
            help="Remaris priceListId; default from SalesPriceList.remaris_price_list_id.",
        )
        parser.add_argument("--include-inactive", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        price_list_id = options["price_list_id"]
        remaris_price_list_id = options["remaris_price_list_id"]
        include_inactive = options["include_inactive"]
        dry_run = options["dry_run"]

        price_list = SalesPriceList.objects.filter(id=price_list_id).first()
        if not price_list:
            raise CommandError(f"SalesPriceList id={price_list_id} not found.")

        target_remaris_id = (
            remaris_price_list_id
            if remaris_price_list_id is not None
            else resolve_remaris_price_list_id(price_list)
        )

        sent, skipped, errors = sync_sales_pricelist_to_remaris(
            price_list=price_list,
            remaris_price_list_id=target_remaris_id,
            include_inactive=include_inactive,
            dry_run=dry_run,
            write_line=self.stdout.write,
        )

        self.stdout.write(
            f"Done. priceListId={target_remaris_id} sent={sent} "
            f"skipped={skipped} errors={errors}"
        )
