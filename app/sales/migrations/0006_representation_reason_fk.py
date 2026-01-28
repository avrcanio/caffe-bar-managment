from django.db import migrations, models


def seed_reasons_and_map(apps, schema_editor):
    Representation = apps.get_model("sales", "Representation")
    RepresentationReason = apps.get_model("sales", "RepresentationReason")

    reasons = [
        ("waiters", "Konobari", 1),
        ("guests", "Gosti", 2),
        ("compliment", "Castilo se", 3),
        ("promo", "Promocija", 4),
        ("writeoff", "Otpis", 5),
        ("other", "Ostalo", 99),
    ]

    reason_by_code = {}
    for code, name, sort_order in reasons:
        obj, _ = RepresentationReason.objects.get_or_create(
            code=code,
            defaults={"name": name, "is_active": True, "sort_order": sort_order},
        )
        reason_by_code[code] = obj

    default_reason = reason_by_code.get("other")
    for rep in Representation.objects.all().only("id", "reason"):
        code = rep.reason or "other"
        reason = reason_by_code.get(code, default_reason)
        Representation.objects.filter(id=rep.id).update(reason_fk=reason)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0005_alter_representation_occurred_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="RepresentationReason",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=30, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "Razlog reprezentacije",
                "verbose_name_plural": "Razlozi reprezentacije",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.AddField(
            model_name="representation",
            name="reason_fk",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=models.PROTECT,
                related_name="representations",
                to="sales.representationreason",
                verbose_name="Razlog reprezentacije",
            ),
        ),
        migrations.RunPython(seed_reasons_and_map, noop_reverse),
        migrations.RemoveField(
            model_name="representation",
            name="reason",
        ),
        migrations.RenameField(
            model_name="representation",
            old_name="reason_fk",
            new_name="reason",
        ),
        migrations.AlterField(
            model_name="representation",
            name="reason",
            field=models.ForeignKey(
                on_delete=models.PROTECT,
                related_name="representations",
                to="sales.representationreason",
                verbose_name="Razlog reprezentacije",
            ),
        ),
    ]
