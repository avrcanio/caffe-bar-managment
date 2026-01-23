from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0011_alter_warehouseinput_purchase_order"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Order",
            new_name="PurchaseOrder",
        ),
        migrations.RenameModel(
            old_name="OrderItem",
            new_name="PurchaseOrderItem",
        ),
    ]
