from django.db import migrations


def seed_pnp_categories(apps, schema_editor):
    ConsumptionTaxCategory = apps.get_model("artikli", "ConsumptionTaxCategory")
    categories = [
        ("ALCOHOL", "Alkoholna pića"),
        ("BEER", "Pivo"),
        ("WINE", "Vino"),
        ("SOFT", "Bezalkoholna pića"),
    ]
    for code, name in categories:
        ConsumptionTaxCategory.objects.get_or_create(
            code=code,
            defaults={"name": name, "is_active": True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("artikli", "0017_consumptiontaxcategory_artikl_pnp_category"),
    ]

    operations = [
        migrations.RunPython(seed_pnp_categories, migrations.RunPython.noop),
    ]
