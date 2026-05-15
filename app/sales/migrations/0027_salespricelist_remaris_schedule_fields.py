from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0026_alter_salespriceitem_unit_price_gross"),
    ]

    operations = [
        migrations.AddField(
            model_name="salespricelist",
            name="remaris_applied_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Remaris primijenjen",
            ),
        ),
        migrations.AddField(
            model_name="salespricelist",
            name="remaris_reverted_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Remaris vracen",
            ),
        ),
    ]
