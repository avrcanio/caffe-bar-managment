from django.db import migrations, models
import django.db.models.deletion


def copy_pnp_categories(apps, schema_editor):
    OldCategory = apps.get_model("artikli", "ConsumptionTaxCategory")
    NewCategory = apps.get_model("configuration", "ConsumptionTaxCategory")
    for old in OldCategory.objects.all():
        NewCategory.objects.update_or_create(
            id=old.id,
            defaults={
                "code": old.code,
                "name": old.name,
                "is_active": old.is_active,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("configuration", "0013_consumption_tax_category"),
        ("artikli", "0018_seed_consumption_tax_categories"),
    ]

    operations = [
        migrations.RunPython(copy_pnp_categories, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="artikl",
            name="pnp_category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="artikli",
                to="configuration.consumptiontaxcategory",
                verbose_name="PnP kategorija",
            ),
        ),
        migrations.DeleteModel(
            name="ConsumptionTaxCategory",
        ),
    ]
