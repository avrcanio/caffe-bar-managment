from django.db import migrations


def set_show_prices_true(apps, schema_editor):
    Supplier = apps.get_model("contacts", "Supplier")
    Supplier.objects.update(show_prices_on_order=True)


class Migration(migrations.Migration):
    dependencies = [
        ("contacts", "0006_supplier_show_prices_on_order"),
    ]

    operations = [
        migrations.RunPython(set_show_prices_true, migrations.RunPython.noop),
    ]
