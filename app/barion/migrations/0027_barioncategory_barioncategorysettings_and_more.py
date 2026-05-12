from datetime import time
from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("artikli", "0028_rename_drinkcategory_to_category"),
        ("barion", "0026_itembundleoption_affects_stock_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="BarionCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="barion_categories",
                        to="artikli.category",
                    ),
                ),
            ],
            options={
                "verbose_name": "Barion category",
                "verbose_name_plural": "Barion categories",
                "ordering": ["sort_order", "category__name", "id"],
            },
        ),
        migrations.CreateModel(
            name="BarionCategorySettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("day_start", models.TimeField(default=time(7, 0))),
                ("day_end", models.TimeField(default=time(20, 0))),
                ("night_start", models.TimeField(default=time(20, 0))),
                ("night_end", models.TimeField(default=time(2, 0))),
                ("day_lookback_days", models.PositiveIntegerField(default=30)),
                ("night_lookback_days", models.PositiveIntegerField(default=30)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Barion category settings",
                "verbose_name_plural": "Barion category settings",
            },
        ),
        migrations.RenameField(
            model_name="productpopularitysnapshot",
            old_name="sold_qty_30d",
            new_name="sold_qty_day",
        ),
        migrations.RenameField(
            model_name="productpopularitysnapshot",
            old_name="sold_qty_night_weekend",
            new_name="sold_qty_night",
        ),
        migrations.RenameField(
            model_name="productpopularitysnapshot",
            old_name="window_days",
            new_name="day_lookback_days",
        ),
        migrations.AddField(
            model_name="productpopularitysnapshot",
            name="night_lookback_days",
            field=models.PositiveIntegerField(default=30),
        ),
        migrations.RemoveIndex(
            model_name="productpopularitysnapshot",
            name="idx_barion_pop_qty_desc",
        ),
        migrations.RemoveIndex(
            model_name="productpopularitysnapshot",
            name="idx_barion_pop_night_qty_desc",
        ),
        migrations.AddIndex(
            model_name="productpopularitysnapshot",
            index=models.Index(fields=["-sold_qty_day"], name="idx_barion_pop_day_qty_desc"),
        ),
        migrations.AddIndex(
            model_name="productpopularitysnapshot",
            index=models.Index(fields=["-sold_qty_night"], name="idx_barion_pop_night_qty_desc"),
        ),
        migrations.AddConstraint(
            model_name="barioncategory",
            constraint=models.UniqueConstraint(fields=("category",), name="uniq_barion_category_category"),
        ),
        migrations.AlterField(
            model_name="productpopularitysnapshot",
            name="sold_qty_day",
            field=models.DecimalField(decimal_places=4, default=Decimal("0.0000"), max_digits=14),
        ),
        migrations.AlterField(
            model_name="productpopularitysnapshot",
            name="sold_qty_night",
            field=models.DecimalField(decimal_places=4, default=Decimal("0.0000"), max_digits=14),
        ),
    ]
