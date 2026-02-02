from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0021_shift_turnover"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ShiftTurnoverClose",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "cash_counted",
                    models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name="gotovina u novcaniku"),
                ),
                (
                    "card_total",
                    models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name="kartice"),
                ),
                ("note", models.TextField(blank=True, default="", verbose_name="napomena")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="kreirano")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="azurirano")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="shift_turnover_closes",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="korisnik",
                    ),
                ),
                (
                    "turnover",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="close",
                        to="sales.shiftturnover",
                        verbose_name="promet smjene",
                    ),
                ),
            ],
            options={
                "verbose_name": "Zatvaranje smjene",
                "verbose_name_plural": "Zatvaranja smjena",
            },
        ),
        migrations.CreateModel(
            name="ShiftTurnoverExpense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12, verbose_name="iznos")),
                ("note", models.CharField(blank=True, default="", max_length=255, verbose_name="opis")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="kreirano")),
                (
                    "close",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="expenses",
                        to="sales.shiftturnoverclose",
                        verbose_name="zatvaranje smjene",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="shift_turnover_expenses",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="korisnik",
                    ),
                ),
            ],
            options={
                "verbose_name": "Rashod smjene",
                "verbose_name_plural": "Rashodi smjena",
            },
        ),
    ]
