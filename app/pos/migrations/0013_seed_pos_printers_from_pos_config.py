from django.db import migrations
from django.utils import timezone


def seed_pos_printers_from_pos_config(apps, schema_editor):
    PosDevice = apps.get_model("pos", "PosDevice")
    PosPrinterInventory = apps.get_model("pos", "PosPrinterInventory")

    for device in PosDevice.objects.select_related("pos").all().iterator():
        pos = getattr(device, "pos", None)
        config = getattr(pos, "config", {}) if pos else {}
        if not isinstance(config, dict):
            continue

        update_fields = []
        if not device.print_receiver_url:
            receipt_receiver_url = str(config.get("receipt_receiver_url", "") or "").strip()
            bar_receiver_url = str(config.get("bar_receiver_url", "") or "").strip()
            receiver_url = receipt_receiver_url or bar_receiver_url
            if receiver_url:
                device.print_receiver_url = receiver_url
                update_fields.append("print_receiver_url")

        receipt_name = str(config.get("receipt_printer_name", "") or "").strip()
        if receipt_name and not device.receipt_printer_id:
            receipt_printer, _ = PosPrinterInventory.objects.update_or_create(
                device=device,
                name=receipt_name,
                defaults={
                    "is_active": True,
                    "status": "seeded",
                    "is_default": True,
                    "last_seen_at": timezone.now(),
                    "raw_payload": {"source": "pos.config", "type": "receipt"},
                },
            )
            device.receipt_printer_id = receipt_printer.id
            update_fields.append("receipt_printer")

        bar_name = str(config.get("bar_printer_name", "") or "").strip()
        if bar_name and not device.bar_printer_id:
            bar_printer, _ = PosPrinterInventory.objects.update_or_create(
                device=device,
                name=bar_name,
                defaults={
                    "is_active": True,
                    "status": "seeded",
                    "is_default": False,
                    "last_seen_at": timezone.now(),
                    "raw_payload": {"source": "pos.config", "type": "bar"},
                },
            )
            device.bar_printer_id = bar_printer.id
            update_fields.append("bar_printer")

        if update_fields:
            device.save(update_fields=sorted(set(update_fields)))


class Migration(migrations.Migration):
    dependencies = [
        ("pos", "0012_posdevice_print_receiver_url_posprinterinventory_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_pos_printers_from_pos_config, migrations.RunPython.noop),
    ]
