from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contacts", "0005_supplier_orders_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplier",
            name="show_prices_on_order",
            field=models.BooleanField(default=True),
        ),
    ]
