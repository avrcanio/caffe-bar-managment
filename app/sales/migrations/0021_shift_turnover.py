from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0020_salesinvoice_user"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ShiftTurnover",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("issued_on", models.DateField(verbose_name="datum")),
                (
                    "total_amount",
                    models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name="ukupno"),
                ),
                ("invoice_count", models.PositiveIntegerField(default=0, verbose_name="broj racuna")),
                ("invoice_ids", models.JSONField(blank=True, default=list, verbose_name="racuni")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="kreirano")),
                (
                    "pos",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="shift_turnovers",
                        to="pos.pos",
                        verbose_name="pos",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="shift_turnovers",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="konobar",
                    ),
                ),
                (
                    "warehouse",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="shift_turnovers",
                        to="stock.warehouseid",
                        verbose_name="skladiste",
                    ),
                ),
            ],
            options={
                "verbose_name": "Promet smjene",
                "verbose_name_plural": "Prometi smjena",
            },
        ),
        migrations.AddConstraint(
            model_name="shiftturnover",
            constraint=models.UniqueConstraint(
                fields=("issued_on", "user", "warehouse", "pos"),
                name="uniq_shift_turnover",
            ),
        ),
    ]
