# Generated manually to match makemigrations output (supplier_return purpose choice).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stock", "0040_supplier_return"),
    ]

    operations = [
        migrations.AlterField(
            model_name="stockmove",
            name="purpose",
            field=models.CharField(
                blank=True,
                choices=[
                    ("sale", "Prodaja"),
                    ("consumption", "Utrošak"),
                    ("waste", "Otpis"),
                    ("adjustment", "Inventurna korekcija"),
                    ("supplier_return", "Povrat dobavljaču"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]
