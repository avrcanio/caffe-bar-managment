from django.core.management.base import BaseCommand
from django.db import transaction

from barion.models import Layout, LayoutTable, Table, Zone


class Command(BaseCommand):
    help = "Seed test data for Barion (Layout, Zone, Table, LayoutTable)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing seed rows and recreate them.",
        )
        parser.add_argument(
            "--layout-name",
            default="Test Floor",
            help="Layout name to seed.",
        )

    def handle(self, *args, **options):
        reset = options["reset"]
        layout_name = options["layout_name"].strip() or "Test Floor"

        with transaction.atomic():
            if reset:
                self._reset_seed(layout_name)

            layout, layout_created = Layout.objects.get_or_create(
                name=layout_name,
                defaults={"is_active": True},
            )
            if not layout.is_active:
                layout.is_active = True
                layout.save(update_fields=["is_active", "updated_at"])

            zone_main, _ = Zone.objects.get_or_create(
                layout=layout,
                name="Main",
                defaults={"order": 10, "color": "#2E86AB"},
            )
            zone_terrace, _ = Zone.objects.get_or_create(
                layout=layout,
                name="Terrace",
                defaults={"order": 20, "color": "#7DCEA0"},
            )
            zone_vip, _ = Zone.objects.get_or_create(
                layout=layout,
                name="VIP",
                defaults={"order": 30, "color": "#F5B041"},
            )

            tables_seed = [
                {
                    "label": "T1",
                    "capacity": 4,
                    "shape": Table.Shape.SQUARE,
                    "is_vip": False,
                    "zone": zone_main,
                    "x": 80,
                    "y": 120,
                    "w": 90,
                    "h": 90,
                    "rotation": 0,
                    "z_index": 10,
                },
                {
                    "label": "T2",
                    "capacity": 4,
                    "shape": Table.Shape.ROUND,
                    "is_vip": False,
                    "zone": zone_main,
                    "x": 220,
                    "y": 120,
                    "w": 90,
                    "h": 90,
                    "rotation": 0,
                    "z_index": 20,
                },
                {
                    "label": "T3",
                    "capacity": 6,
                    "shape": Table.Shape.RECTANGLE,
                    "is_vip": False,
                    "zone": zone_terrace,
                    "x": 120,
                    "y": 320,
                    "w": 140,
                    "h": 90,
                    "rotation": 0,
                    "z_index": 30,
                },
                {
                    "label": "VIP1",
                    "capacity": 6,
                    "shape": Table.Shape.RECTANGLE,
                    "is_vip": True,
                    "zone": zone_vip,
                    "x": 420,
                    "y": 180,
                    "w": 160,
                    "h": 100,
                    "rotation": 0,
                    "z_index": 40,
                },
                {
                    "label": "VIP2",
                    "capacity": 8,
                    "shape": Table.Shape.RECTANGLE,
                    "is_vip": True,
                    "zone": zone_vip,
                    "x": 420,
                    "y": 340,
                    "w": 180,
                    "h": 110,
                    "rotation": 0,
                    "z_index": 50,
                },
            ]

            created_tables = 0
            created_placements = 0
            updated_placements = 0

            for item in tables_seed:
                table, table_created = Table.objects.get_or_create(
                    label=item["label"],
                    defaults={
                        "capacity": item["capacity"],
                        "shape": item["shape"],
                        "is_vip": item["is_vip"],
                        "width": item["w"],
                        "height": item["h"],
                    },
                )
                if table_created:
                    created_tables += 1
                else:
                    dirty = False
                    for field in ("capacity", "shape", "is_vip", "width", "height"):
                        value = item["w"] if field == "width" else item["h"] if field == "height" else item[field]
                        if getattr(table, field) != value:
                            setattr(table, field, value)
                            dirty = True
                    if dirty:
                        table.save(update_fields=["capacity", "shape", "is_vip", "width", "height", "updated_at"])

                placement, placement_created = LayoutTable.objects.get_or_create(
                    layout=layout,
                    table=table,
                    defaults={
                        "zone": item["zone"],
                        "x": item["x"],
                        "y": item["y"],
                        "w": item["w"],
                        "h": item["h"],
                        "rotation": item["rotation"],
                        "is_enabled": True,
                        "z_index": item["z_index"],
                    },
                )
                if placement_created:
                    created_placements += 1
                else:
                    placement.zone = item["zone"]
                    placement.x = item["x"]
                    placement.y = item["y"]
                    placement.w = item["w"]
                    placement.h = item["h"]
                    placement.rotation = item["rotation"]
                    placement.is_enabled = True
                    placement.z_index = item["z_index"]
                    placement.save(
                        update_fields=["zone", "x", "y", "w", "h", "rotation", "is_enabled", "z_index", "updated_at"]
                    )
                    updated_placements += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Barion seed complete. "
                f"layout={'created' if layout_created else 'existing'} "
                f"tables_created={created_tables} "
                f"placements_created={created_placements} "
                f"placements_updated={updated_placements}"
            )
        )

    @staticmethod
    def _reset_seed(layout_name: str) -> None:
        layout = Layout.objects.filter(name=layout_name).first()
        if not layout:
            return

        table_ids = list(LayoutTable.objects.filter(layout=layout).values_list("table_id", flat=True))
        LayoutTable.objects.filter(layout=layout).delete()
        Zone.objects.filter(layout=layout).delete()
        Layout.objects.filter(id=layout.id).delete()
        if table_ids:
            Table.objects.filter(id__in=table_ids).delete()
