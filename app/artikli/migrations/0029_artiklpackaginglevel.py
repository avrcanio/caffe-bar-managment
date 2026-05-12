from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("artikli", "0028_rename_drinkcategory_to_category"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArtiklPackagingLevel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=100, verbose_name="Razina pakiranja")),
                (
                    "contains_previous",
                    models.DecimalField(
                        blank=True,
                        decimal_places=4,
                        help_text="Za prvu razinu ostavi prazno. Za svaku sljedeću upiši koliko prethodnih jedinica sadrži.",
                        max_digits=12,
                        null=True,
                        verbose_name="Sadrži prethodnu razinu",
                    ),
                ),
                ("sort_order", models.PositiveIntegerField(default=0, verbose_name="Redoslijed")),
                (
                    "artikl",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="packaging_levels",
                        to="artikli.artikl",
                        verbose_name="Artikl",
                    ),
                ),
                (
                    "unit_of_measure",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="artikl_packaging_levels",
                        to="artikli.unitofmeasuredata",
                        verbose_name="Jedinica mjere",
                    ),
                ),
            ],
            options={
                "verbose_name": "Razina originalnog pakiranja",
                "verbose_name_plural": "Razine originalnih pakiranja",
                "ordering": ["sort_order", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("artikl", "sort_order"),
                        name="uniq_artikl_packaging_level_sort_order",
                    )
                ],
            },
        ),
    ]
