from django.db import migrations, models


def _assign_default_warehouse(apps, schema_editor):
    Pos = apps.get_model("pos", "Pos")
    PosReceipt = apps.get_model("pos", "PosReceipt")
    SalesInvoice = apps.get_model("sales", "SalesInvoice")
    WarehouseId = apps.get_model("stock", "WarehouseId")

    try:
        ShiftTurnover = apps.get_model("sales", "ShiftTurnover")
    except LookupError:
        ShiftTurnover = None

    preferred_wh = WarehouseId.objects.filter(name="Šank Gornji").first()
    default_wh = preferred_wh or WarehouseId.objects.order_by("rm_id").first()
    if not default_wh:
        # Fresh installs / test DBs may not have warehouses yet; create a placeholder.
        default_wh = WarehouseId.objects.create(rm_id=1, name="Default")

    for pos in Pos.objects.all():
        warehouse = None

        receipt = (
            PosReceipt.objects.filter(pos_id=pos.id, warehouse__isnull=False)
            .order_by("-issued_at", "-id")
            .first()
        )
        if receipt:
            warehouse = receipt.warehouse

        if warehouse is None:
            if ShiftTurnover is not None:
                turnover = (
                    ShiftTurnover.objects.filter(pos_id=pos.id, warehouse__isnull=False)
                    .order_by("-issued_on", "-id")
                    .first()
                )
                if turnover:
                    warehouse = turnover.warehouse

        if warehouse is None:
            invoice = (
                SalesInvoice.objects.filter(pos_id=pos.id, warehouse__isnull=False)
                .order_by("-issued_at", "-id")
                .first()
            )
            if invoice:
                warehouse = invoice.warehouse

        if warehouse is None:
            warehouse = default_wh

        pos.warehouse = warehouse
        pos.save(update_fields=["warehouse"])


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0009_posdevice"),
        ("sales", "0014_restore_salesinvoice_columns"),
        ("stock", "0034_warehouseid_external_location_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="pos",
            name="warehouse",
            field=models.ForeignKey(
                null=True,
                on_delete=models.PROTECT,
                related_name="pos_list",
                to="stock.warehouseid",
                to_field="rm_id",
                verbose_name="Skladiste",
            ),
        ),
        migrations.RunPython(_assign_default_warehouse, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="pos",
            name="warehouse",
            field=models.ForeignKey(
                on_delete=models.PROTECT,
                related_name="pos_list",
                to="stock.warehouseid",
                to_field="rm_id",
                verbose_name="Skladiste",
            ),
        ),
    ]
