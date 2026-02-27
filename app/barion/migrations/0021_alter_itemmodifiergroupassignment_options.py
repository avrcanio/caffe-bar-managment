from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("barion", "0020_remove_item_modifier_group_assignment_sort_order"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="itemmodifiergroupassignment",
            options={
                "ordering": ["artikl_id", "group_id"],
                "verbose_name": "Item modifier group assignment",
                "verbose_name_plural": "Item modifier group assignments",
            },
        ),
    ]
