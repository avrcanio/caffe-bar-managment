from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0029_alter_purchaseorder_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchaseOrderItemPriceAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("old_price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("new_price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                ("reason", models.TextField()),
                (
                    "artikl",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="purchase_order_price_audits",
                        to="artikli.artikl",
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="purchase_order_item_price_audits",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "purchase_order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="price_audits",
                        to="orders.purchaseorder",
                    ),
                ),
                (
                    "purchase_order_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="price_audits",
                        to="orders.purchaseorderitem",
                    ),
                ),
                (
                    "supplier",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="purchase_order_price_audits",
                        to="contacts.supplier",
                    ),
                ),
            ],
            options={
                "verbose_name": "Audit promjene cijene stavke narudzbe",
                "verbose_name_plural": "Audit promjene cijena stavki narudzbe",
                "ordering": ("-changed_at", "-id"),
            },
        ),
    ]
