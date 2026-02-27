from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("barion", "0019_item_modifiers"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="itemmodifiergroupassignment",
            name="sort_order",
        ),
    ]
