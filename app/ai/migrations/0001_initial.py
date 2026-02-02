from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIQueryLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.TextField()),
                ("response_text", models.TextField(blank=True, default="")),
                ("tool_calls", models.JSONField(blank=True, default=list)),
                (
                    "status",
                    models.CharField(
                        choices=[("ok", "OK"), ("error", "Error")],
                        default="ok",
                        max_length=20,
                    ),
                ),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_queries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "AI upit",
                "verbose_name_plural": "AI upiti",
                "ordering": ["-created_at"],
            },
        ),
    ]
