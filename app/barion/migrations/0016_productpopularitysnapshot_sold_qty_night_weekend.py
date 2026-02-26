from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("barion", "0015_remove_check_pos_receipt"),
    ]

    operations = [
        migrations.AddField(
            model_name="productpopularitysnapshot",
            name="sold_qty_night_weekend",
            field=models.DecimalField(decimal_places=4, default=Decimal("0.0000"), max_digits=14),
        ),
        migrations.AddIndex(
            model_name="productpopularitysnapshot",
            index=models.Index(fields=["-sold_qty_night_weekend"], name="idx_barion_pop_night_qty_desc"),
        ),
    ]
