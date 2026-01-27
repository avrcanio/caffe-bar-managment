from django.db import migrations


def seed_categories(apps, schema_editor):
    DrinkCategory = apps.get_model("artikli", "DrinkCategory")

    def get_or_create(name, parent=None, sort_order=0):
        obj, _ = DrinkCategory.objects.get_or_create(
            name=name,
            parent=parent,
            defaults={"sort_order": sort_order, "is_active": True},
        )
        obj.sort_order = sort_order
        obj.is_active = True
        obj.save(update_fields=["sort_order", "is_active"])
        return obj

    napitci = get_or_create("Napitci", None, 1)

    topli = get_or_create("Topli napici", napitci, 1)
    hladni = get_or_create("Hladni napici", napitci, 2)

    kave = get_or_create("Kave", topli, 1)
    cajevi = get_or_create("Cajevi", topli, 2)
    kakao = get_or_create("Kakao i cokolada", topli, 3)

    voda = get_or_create("Voda", hladni, 1)
    sokovi = get_or_create("Sokovi", hladni, 2)
    gazirano = get_or_create("Gazirano", hladni, 3)
    energetska = get_or_create("Energetska pica", hladni, 4)

    get_or_create("Espresso", kave, 1)
    get_or_create("Produzena", kave, 2)
    get_or_create("Cappuccino", kave, 3)

    get_or_create("Crni caj", cajevi, 1)
    get_or_create("Zeleni caj", cajevi, 2)
    get_or_create("Biljni caj", cajevi, 3)

    get_or_create("Negazirana voda", voda, 1)
    get_or_create("Gazirana voda", voda, 2)

    get_or_create("Cijedeni sokovi", sokovi, 1)
    get_or_create("Prirodni sokovi", sokovi, 2)


def unseed(apps, schema_editor):
    DrinkCategory = apps.get_model("artikli", "DrinkCategory")
    DrinkCategory.objects.filter(name="Napitci", parent__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("artikli", "0020_drinkcategory_artikl_drink_category_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed),
    ]
