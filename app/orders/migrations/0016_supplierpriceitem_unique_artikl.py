from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0015_purchaseorder_status_and_confirmation"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="supplierpriceitem",
            constraint=models.UniqueConstraint(
                fields=("price_list", "artikl"),
                name="uniq_supplier_pricelist_artikl",
            ),
        ),
    ]
