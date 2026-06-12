from django.db import migrations, models

DEFAULT_REMARIS_PRICE_LIST_ID = 10
KONCERT_MOZART_PRICE_LIST_ID = 9
KONCERT_REMARIS_PRICE_LIST_ID = 9


def configure_remaris_price_list_mapping(apps, schema_editor):
    SalesPriceList = apps.get_model("sales", "SalesPriceList")

    SalesPriceList.objects.filter(pk=KONCERT_MOZART_PRICE_LIST_ID).update(
        name="Pivo Koncert",
        remaris_price_list_id=KONCERT_REMARIS_PRICE_LIST_ID,
        remaris_sync_transfer_pos=False,
    )

    SalesPriceList.objects.filter(remaris_price_list_id__isnull=True).update(
        remaris_price_list_id=DEFAULT_REMARIS_PRICE_LIST_ID,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0027_salespricelist_remaris_schedule_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="salespricelist",
            name="remaris_price_list_id",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Remaris priceListId (npr. 9=Koncert, 10=redovni). Prazno = 10.",
                null=True,
                verbose_name="Remaris cjenik ID",
            ),
        ),
        migrations.AddField(
            model_name="salespricelist",
            name="remaris_sync_transfer_pos",
            field=models.BooleanField(
                default=True,
                help_text="Nakon synca cjenika pozovi Transfer na POS (isključiti za Koncert).",
                verbose_name="Remaris sync: transfer na POS",
            ),
        ),
        migrations.RunPython(
            configure_remaris_price_list_mapping,
            migrations.RunPython.noop,
        ),
    ]
