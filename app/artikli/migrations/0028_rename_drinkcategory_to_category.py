import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("artikli", "0027_alter_artikl_tax_group_required"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="DrinkCategory",
            new_name="Category",
        ),
        migrations.RenameField(
            model_name="artikl",
            old_name="drink_category",
            new_name="category",
        ),
        migrations.AlterModelOptions(
            name="category",
            options={
                "ordering": ["tree_id", "lft"],
                "verbose_name": "Kategorija",
                "verbose_name_plural": "Kategorije",
            },
        ),
        migrations.AlterField(
            model_name="artikl",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="artikli",
                to="artikli.category",
                verbose_name="Kategorija",
            ),
        ),
    ]
