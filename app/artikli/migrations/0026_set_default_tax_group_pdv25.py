from decimal import Decimal

from django.db import migrations


def set_default_tax_group_pdv25(apps, schema_editor):
    TaxGroup = apps.get_model("configuration", "TaxGroup")
    Artikl = apps.get_model("artikli", "Artikl")

    tg = TaxGroup.objects.filter(code__iexact="PDV25").first()
    if not tg:
        tg = TaxGroup.objects.filter(rate=Decimal("0.2500")).order_by("id").first()
    if not tg:
        tg = TaxGroup.objects.create(
            name="Opća stopa 25%",
            rate=Decimal("0.2500"),
            code="PDV25",
            is_active=True,
        )

    Artikl.objects.filter(tax_group__isnull=True).update(tax_group_id=tg.id)


class Migration(migrations.Migration):
    dependencies = [
        ("configuration", "0016_companyprofile_fiscal_cert_filename_and_more"),
        ("artikli", "0025_alter_drinkcategory_options_and_more"),
    ]

    operations = [
        migrations.RunPython(set_default_tax_group_pdv25, migrations.RunPython.noop),
    ]

