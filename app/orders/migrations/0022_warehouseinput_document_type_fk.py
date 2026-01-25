from django.db import migrations, models
import django.db.models.deletion


def link_document_types(apps, schema_editor):
    DocumentType = apps.get_model("configuration", "DocumentType")
    WarehouseInput = apps.get_model("orders", "WarehouseInput")

    default_doc = (
        DocumentType.objects.filter(code="10").first()
        or DocumentType.objects.filter(code__iexact="PRIMKA").first()
        or DocumentType.objects.filter(name__iexact="Primka").first()
    )

    for entry in WarehouseInput.objects.all():
        code = (entry.document_type_code or "").strip()
        doc = None
        if code:
            doc = DocumentType.objects.filter(code=code).first()
            if not doc and code == "10":
                doc = default_doc
            if not doc:
                doc = DocumentType.objects.create(
                    code=code,
                    name=f"Tip {code}",
                    direction="in",
                    is_active=True,
                )
        else:
            doc = default_doc

        if doc and entry.document_type_id != doc.id:
            entry.document_type = doc
            entry.save(update_fields=["document_type"])


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0021_alter_purchaseorder_status"),
        ("configuration", "0009_account_remove_documenttype_counterpart_account_code_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="warehouseinput",
            old_name="document_type",
            new_name="document_type_code",
        ),
        migrations.AddField(
            model_name="warehouseinput",
            name="document_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="warehouse_inputs",
                to="configuration.documenttype",
                verbose_name="tip dokumenta",
            ),
        ),
        migrations.RunPython(link_document_types, migrations.RunPython.noop),
    ]
