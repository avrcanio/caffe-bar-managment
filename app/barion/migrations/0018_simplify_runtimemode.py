from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("barion", "0017_barionruntimemode"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="barionruntimemode",
            name="lock_clients",
        ),
        migrations.RemoveField(
            model_name="barionruntimemode",
            name="night_enabled",
        ),
        migrations.AlterModelOptions(
            name="barionruntimemode",
            options={"verbose_name": "Runtime mode", "verbose_name_plural": "Runtime mode"},
        ),
    ]
