from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("artikli", "0029_artiklpackaginglevel"),
    ]

    operations = [
        migrations.AlterField(
            model_name="artiklpackaginglevel",
            name="unit_of_measure",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="artikl_packaging_levels",
                to="artikli.unitofmeasuredata",
                verbose_name="Jedinica mjere",
            ),
        ),
        migrations.RemoveField(
            model_name="artiklpackaginglevel",
            name="label",
        ),
    ]
