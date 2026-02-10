from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("artikli", "0026_set_default_tax_group_pdv25"),
    ]

    operations = [
        migrations.AlterField(
            model_name="artikl",
            name="tax_group",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.SET_NULL,
                null=True,
                blank=False,
                related_name="artikli",
                to="configuration.taxgroup",
                verbose_name="porezna grupa",
            ),
        ),
    ]

