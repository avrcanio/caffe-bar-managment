from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import Artikl
from sales.models import SalesInvoiceItem
from sales.product_artikl_resolution import build_artikl_lookup, resolve_artikl_id


class Command(BaseCommand):
    help = (
        "Postavi artikl na stavkama racuna (promet) gdje je artikl prazan, "
        "koristeci normalizirano mapiranje product_name -> Artikl.name."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--product-name",
            help="Ogranicenje na tocno product_name (npr. 'Corona extra 0.355 l').",
        )
        parser.add_argument(
            "--artikl-code",
            help="Ogranicenje na artikl code kad se eksplicitno zeli (npr. 75032814).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Samo ispisi sto bi se promijenilo.",
        )

    def handle(self, *args, **options):
        product_name = options.get("product_name")
        artikl_code = options.get("artikl_code")
        dry_run = options["dry_run"]

        qs = SalesInvoiceItem.objects.filter(artikl__isnull=True).exclude(product_name="")
        if product_name:
            qs = qs.filter(product_name=product_name)

        lookup = build_artikl_lookup()
        forced_artikl_id = None
        if artikl_code:
            forced_artikl_id = (
                Artikl.objects.filter(code=artikl_code).values_list("id", flat=True).first()
            )
            if forced_artikl_id is None:
                raise SystemExit(f"Artikl code={artikl_code!r} not found.")

        to_update: list[SalesInvoiceItem] = []
        skipped = 0
        for item in qs.iterator(chunk_size=500):
            artikl_id = forced_artikl_id or resolve_artikl_id(
                item.product_name,
                lookup=lookup,
            )
            if artikl_id is None:
                skipped += 1
                continue
            item.artikl_id = artikl_id
            to_update.append(item)

        if dry_run:
            self.stdout.write(
                f"DRY-RUN: would update {len(to_update)} items, skip {skipped}."
            )
            for item in to_update[:20]:
                self.stdout.write(
                    f"  id={item.id} {item.product_name!r} -> artikl_id={item.artikl_id}"
                )
            if len(to_update) > 20:
                self.stdout.write(f"  ... and {len(to_update) - 20} more")
            return

        with transaction.atomic():
            SalesInvoiceItem.objects.bulk_update(to_update, ["artikl_id"], batch_size=500)

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {len(to_update)} items, skipped {skipped} without match."
            )
        )
