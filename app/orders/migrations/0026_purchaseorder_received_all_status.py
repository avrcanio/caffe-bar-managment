from decimal import Decimal

from django.db import migrations
from django.db.models import Sum


def set_received_all_status(apps, schema_editor):
    PurchaseOrder = apps.get_model("orders", "PurchaseOrder")
    PurchaseOrderItem = apps.get_model("orders", "PurchaseOrderItem")
    WarehouseInputItem = apps.get_model("orders", "WarehouseInputItem")

    for po in PurchaseOrder.objects.filter(status="received").only("id"):
        ordered_rows = (
            PurchaseOrderItem.objects.filter(order_id=po.id)
            .values("artikl_id")
            .annotate(q=Sum("quantity"))
        )
        if not ordered_rows:
            continue
        received_rows = (
            WarehouseInputItem.objects.filter(warehouse_input__purchase_order_id=po.id)
            .values("artikl_id")
            .annotate(q=Sum("quantity"))
        )
        received_by_artikl = {r["artikl_id"]: (r["q"] or Decimal("0")) for r in received_rows}

        fully = True
        for r in ordered_rows:
            a_id = r["artikl_id"]
            ordered = r["q"] or Decimal("0")
            rec = received_by_artikl.get(a_id, Decimal("0"))
            if rec < ordered:
                fully = False
                break
        if fully:
            PurchaseOrder.objects.filter(id=po.id).update(status="received_all")


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0025_purchaseorder_created_by"),
    ]

    operations = [
        migrations.RunPython(set_received_all_status, migrations.RunPython.noop),
    ]

