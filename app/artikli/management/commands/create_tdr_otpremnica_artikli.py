from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import Artikl, ArtiklPackagingLevel, Category, UnitOfMeasureData

CIGARETE_CATEGORY_ID = 155
KOMAD_UOM_RM_ID = 3
PAKET_UOM_RM_ID = 7
PAKET_CONTAINS_PREVIOUS = Decimal("10")

TDR_OTPREMNICA_ITEMS = [
    ("10233801", "DUNHILL OPUS ENIGMA BLACK", "38506529"),
    ("10221864", "DUNHILL SIGNATURE BLACK", "38506420"),
    ("10243690", "LUCKY STRIKE AMBER", "59479024"),
    ("10249544", "LUCKY STRIKE ROUNDED TOBACCO", "3856008879493"),
    ("10249478", "NEO STICKS TOBACCO BRIGHT", "59481744"),
    ("10240987", "VELO Cherry Ice 6mg", "3856008884831"),
    ("10240988", "VELO Cherry Ice 10mg", "3856008884862"),
    ("10198925", "VELO Freezing Peppermint 17 mg", "3856008880758"),
    ("10243556", "VELO Smooth Peppermint 6mg", "3856008885012"),
    ("10242319", "VELO Smooth Peppermint 8mg", "3856008884923"),
    ("10244781", "VELO Peppermint Storm 17 mg", "3856008885074"),
]


def title_case_name(value: str) -> str:
    parts = []
    for word in value.split():
        if not word:
            continue
        lowered = word.lower()
        if lowered in {"mg", "g", "l", "ml"}:
            parts.append(lowered)
            continue
        parts.append(word[:1].upper() + word[1:].lower())
    return " ".join(parts)


class Command(BaseCommand):
    help = "Create TDR otpremnica artikli (EAN kutijice, Cigarete category, Komad->Paket packaging)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print actions without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        category = Category.objects.filter(pk=CIGARETE_CATEGORY_ID).first()
        if not category:
            raise RuntimeError(f"Category id={CIGARETE_CATEGORY_ID} (Cigarete) not found.")

        komad_uom = UnitOfMeasureData.objects.filter(rm_id=KOMAD_UOM_RM_ID).first()
        paket_uom = UnitOfMeasureData.objects.filter(rm_id=PAKET_UOM_RM_ID).first()
        if not komad_uom or not paket_uom:
            raise RuntimeError(
                f"Required UOM missing: Komad rm_id={KOMAD_UOM_RM_ID}, "
                f"Paket rm_id={PAKET_UOM_RM_ID}."
            )

        created = 0
        skipped = 0

        def process_items():
            nonlocal created, skipped
            for tdr_code, raw_name, ean in TDR_OTPREMNICA_ITEMS:
                name = title_case_name(raw_name)
                if Artikl.objects.filter(code=ean).exists():
                    self.stdout.write(f"SKIP existing code={ean} ({name})")
                    skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        f"DRY-RUN create: name={name!r} code={ean} "
                        f"category=Cigarete packaging=komad->10/paket tdr={tdr_code}"
                    )
                    created += 1
                    continue

                artikl = Artikl.objects.create(
                    name=name,
                    code=ean,
                    category=category,
                    is_sellable=True,
                    is_stock_item=True,
                    rm_id=None,
                )
                ArtiklPackagingLevel.objects.create(
                    artikl=artikl,
                    unit_of_measure=komad_uom,
                    sort_order=0,
                    contains_previous=None,
                )
                ArtiklPackagingLevel.objects.create(
                    artikl=artikl,
                    unit_of_measure=paket_uom,
                    sort_order=1,
                    contains_previous=PAKET_CONTAINS_PREVIOUS,
                )
                self.stdout.write(
                    f"CREATED id={artikl.id} name={name!r} code={ean} "
                    f"path={artikl.packaging_path_summary()}"
                )
                created += 1

        if dry_run:
            process_items()
        else:
            with transaction.atomic():
                process_items()

        label = "Dry-run complete" if dry_run else "Create complete"
        self.stdout.write(self.style.SUCCESS(f"{label}. created={created} skipped={skipped}"))
