from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("configuration", "0012_documenttype_revenue_expense_fallbacks"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConsumptionTaxCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=30, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "PnP kategorija",
                "verbose_name_plural": "PnP kategorije",
            },
        ),
    ]
