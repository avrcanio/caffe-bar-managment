from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_runtime_mode(apps, schema_editor):
    RuntimeMode = apps.get_model("barion", "BarionRuntimeMode")
    RuntimeMode.objects.get_or_create(
        pk=1,
        defaults={"active_mode": "day", "night_enabled": False, "lock_clients": True},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("barion", "0016_productpopularitysnapshot_sold_qty_night_weekend"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BarionRuntimeMode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "active_mode",
                    models.CharField(
                        choices=[("day", "Day"), ("night", "Night")],
                        default="day",
                        max_length=10,
                    ),
                ),
                ("night_enabled", models.BooleanField(default=False)),
                ("lock_clients", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="barion_runtime_mode_updates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Barion runtime mode",
                "verbose_name_plural": "Barion runtime modes",
            },
        ),
        migrations.RunPython(code=create_runtime_mode, reverse_code=migrations.RunPython.noop),
    ]
