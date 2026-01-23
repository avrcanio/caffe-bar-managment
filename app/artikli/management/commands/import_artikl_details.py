import time

from django.core.management.base import BaseCommand
from django.db import transaction

from artikli.models import Artikl, ArtiklDetail
from artikli.remaris_connector import RemarisConnector
from artikli.remaris_parser import parse_hidden_inputs, parse_bool, parse_decimal, parse_int


def _detail_defaults(artikl, inputs):
    return {
        "artikl": artikl,
        "rm_id": parse_int(inputs.get("Id")) or artikl.rm_id,
        "name": inputs.get("Name") or artikl.name,
        "code": inputs.get("Code") or artikl.code,
        "barcode": inputs.get("BarCode", ""),
        "description": inputs.get("Description", ""),
        "external_code": inputs.get("ExternalCode", ""),
        "base_group_id": parse_int(inputs.get("BaseGroupId")),
        "sales_group_id": parse_int(inputs.get("SalesGroupId")),
        "keyboard_group_id": parse_int(inputs.get("KeyboardGroupId")),
        "unit_of_measure_id": parse_int(inputs.get("UnitOfMeasureId")),
        "standard_uom_id": parse_int(inputs.get("StandardUOMId")),
        "standard_uom_name": inputs.get("StandardUOMDisplayName", ""),
        "quantity_in_suom": parse_decimal(inputs.get("QuantityInSUOM")),
        "spillage_allowance": parse_decimal(inputs.get("SpillageAllowance")),
        "ordinal": parse_decimal(inputs.get("Ordinal")),
        "point_of_issue_id": parse_int(inputs.get("PointOfIssueId")),
        "is_for_sale": parse_bool(inputs.get("IsForSale")),
        "is_purchased": parse_bool(inputs.get("IsPurchased")),
        "is_product": parse_bool(inputs.get("IsProduct")),
        "is_commodity": parse_bool(inputs.get("IsCommodity")),
        "is_immaterial": parse_bool(inputs.get("IsImmaterial")),
        "is_used_on_pos": parse_bool(inputs.get("IsUsedOnPOS")),
        "is_package": parse_bool(inputs.get("IsPackage")),
        "is_negative_quantity_allowed": parse_bool(inputs.get("IsNegativeQuantityAllowed")),
        "no_discount": parse_bool(inputs.get("NoDiscount")),
        "has_return_fee": parse_bool(inputs.get("HasReturnFee")),
        "active": parse_bool(inputs.get("Active")),
        "print_on_pricelist": parse_bool(inputs.get("PrintOnPricelist")),
    }


class Command(BaseCommand):
    help = "Import artikl details from Remaris"

    def add_arguments(self, parser):
        parser.add_argument("--rm-id", type=int, help="Import single artikl by rm_id")
        parser.add_argument("--limit", type=int, help="Limit number of artikli")

    def handle(self, *args, **options):
        queryset = Artikl.objects.all().order_by("rm_id")
        if options.get("rm_id"):
            queryset = queryset.filter(rm_id=options["rm_id"])
        if options.get("limit"):
            queryset = queryset[: options["limit"]]

        connector = RemarisConnector()
        connector.login()

        created = 0
        updated = 0
        skipped = 0

        with transaction.atomic():
            for artikl in queryset:
                html = connector.get_html(
                    f"Product/Details/{artikl.rm_id}?_={int(time.time() * 1000)}",
                    referer_path="/Product",
                )
                inputs = parse_hidden_inputs(html)
                if not inputs:
                    skipped += 1
                    continue

                defaults = _detail_defaults(artikl, inputs)
                _, was_created = ArtiklDetail.objects.update_or_create(
                    rm_id=defaults["rm_id"],
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
