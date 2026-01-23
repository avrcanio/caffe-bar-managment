from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("stock", "0017_warehousetransfer_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="inventory",
            name="status",
            field=models.CharField(
                choices=[("open", "Open"), ("counted", "Counted"), ("closed", "Closed")],
                default="open",
                max_length=20,
                verbose_name="Status",
            ),
        ),
    ]
