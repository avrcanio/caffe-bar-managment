from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0018_merge_20260121_0653"),
    ]

    operations = [
        migrations.AlterField(
            model_name="warehouseinput",
            name="is_r_invoice",
            field=models.BooleanField(default=True, verbose_name="R racun"),
        ),
    ]
