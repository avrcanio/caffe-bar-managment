from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("stock", "0016_warehousetransfer_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="warehousetransfer",
            name="note",
            field=models.TextField(blank=True, default=""),
        ),
    ]
