from django.db import migrations, models


def set_status(apps, schema_editor):
    PurchaseOrder = apps.get_model("orders", "PurchaseOrder")
    for order in PurchaseOrder.objects.all():
        order.status = "sent" if getattr(order, "email_sent", False) else "created"
        order.save(update_fields=["status"])


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0014_purchaseorder_primka_created"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorder",
            name="status",
            field=models.CharField(
                choices=[("created", "Kreirana"), ("sent", "Poslana"), ("confirmed", "Potvrdena")],
                default="created",
                max_length=20,
                verbose_name="status narudzbe",
            ),
        ),
        migrations.AddField(
            model_name="purchaseorder",
            name="confirmation_token",
            field=models.CharField(
                blank=True,
                max_length=128,
                null=True,
                unique=True,
                verbose_name="token potvrde",
            ),
        ),
        migrations.AddField(
            model_name="purchaseorder",
            name="confirmation_sent_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="vrijeme slanja potvrde",
            ),
        ),
        migrations.AddField(
            model_name="purchaseorder",
            name="confirmed_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="vrijeme potvrde",
            ),
        ),
        migrations.RunPython(set_status, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="purchaseorder",
            name="email_sent",
        ),
    ]
