from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("artikli", "0027_alter_artikl_tax_group_required"),
        ("barion", "0018_simplify_runtimemode"),
    ]

    operations = [
        migrations.CreateModel(
            name="ItemModifierGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("code", models.CharField(max_length=60, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "type",
                    models.CharField(
                        choices=[("simple", "Simple"), ("bundle", "Bundle")],
                        default="simple",
                        max_length=20,
                    ),
                ),
                (
                    "selection_mode",
                    models.CharField(
                        choices=[("single", "Single"), ("multiple", "Multiple")],
                        default="multiple",
                        max_length=20,
                    ),
                ),
                ("min_select", models.PositiveIntegerField(default=0)),
                ("max_select", models.PositiveIntegerField(default=10)),
                ("allow_note", models.BooleanField(default=False)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Item modifier group",
                "verbose_name_plural": "Item modifier groups",
                "ordering": ["sort_order", "name", "id"],
            },
        ),
        migrations.CreateModel(
            name="ItemModifierGroupAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True)),
                ("is_required", models.BooleanField(default=False)),
                ("min_select_override", models.PositiveIntegerField(blank=True, null=True)),
                ("max_select_override", models.PositiveIntegerField(blank=True, null=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "artikl",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="barion_modifier_group_assignments",
                        to="artikli.artikl",
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="artikl_assignments",
                        to="barion.itemmodifiergroup",
                    ),
                ),
            ],
            options={
                "verbose_name": "Item modifier group assignment",
                "verbose_name_plural": "Item modifier group assignments",
                "ordering": ["artikl_id", "sort_order", "group_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("artikl", "group"),
                        name="uniq_barion_modifier_assignment_artikl_group",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ItemModifierOption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("code", models.CharField(max_length=60)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="options",
                        to="barion.itemmodifiergroup",
                    ),
                ),
            ],
            options={
                "verbose_name": "Item modifier option",
                "verbose_name_plural": "Item modifier options",
                "ordering": ["group_id", "sort_order", "name", "id"],
                "constraints": [
                    models.UniqueConstraint(fields=("group", "code"), name="uniq_barion_modifier_option_group_code"),
                    models.UniqueConstraint(fields=("group", "name"), name="uniq_barion_modifier_option_group_name"),
                ],
            },
        ),
        migrations.CreateModel(
            name="CheckItemModifierSelection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "check_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="modifier_selections",
                        to="barion.checkitem",
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="check_item_selections",
                        to="barion.itemmodifiergroup",
                    ),
                ),
                (
                    "option",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="check_item_selections",
                        to="barion.itemmodifieroption",
                    ),
                ),
            ],
            options={
                "verbose_name": "Check item modifier selection",
                "verbose_name_plural": "Check item modifier selections",
                "ordering": ["check_item_id", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("check_item", "option"),
                        name="uniq_barion_check_item_modifier_option",
                    )
                ],
            },
        ),
    ]
