import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0032_supplierpricelist_name"),
        ("stock", "0042_supplierreturn_source_warehouse_input"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplierreturnitem",
            name="warehouse",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="supplier_return_items",
                to="stock.warehouseid",
                to_field="rm_id",
                verbose_name="Skladište stavke",
            ),
        ),
        migrations.AddField(
            model_name="supplierreturnitem",
            name="source_input_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="supplier_return_items",
                to="orders.warehouseinputitem",
                verbose_name="Stavka primke (izvor)",
            ),
        ),
    ]
