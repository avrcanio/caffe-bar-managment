from django.db import migrations, models
import django.db.models.deletion


def map_default_accounts(apps, schema_editor):
    DocumentType = apps.get_model("configuration", "DocumentType")
    Ledger = apps.get_model("accounting", "Ledger")
    Account = apps.get_model("accounting", "Account")

    ledger = Ledger.objects.filter(id=1).first()
    if not ledger:
        return

    ar_acc = Account.objects.filter(ledger=ledger, code="1310").first()
    ap_acc = Account.objects.filter(ledger=ledger, code="2200").first()

    for doc in DocumentType.objects.all():
        if doc.ledger_id is None:
            doc.ledger = ledger
        if ar_acc and doc.ar_account_id is None:
            doc.ar_account = ar_acc
        if ap_acc and doc.ap_account_id is None:
            doc.ap_account = ap_acc
        doc.save(update_fields=["ledger", "ar_account", "ap_account"])


class Migration(migrations.Migration):

    dependencies = [
        ("configuration", "0009_account_remove_documenttype_counterpart_account_code_and_more"),
        ("accounting", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="documenttype",
            name="ledger",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="document_types",
                to="accounting.ledger",
                verbose_name="ledger",
            ),
        ),
        migrations.AddField(
            model_name="documenttype",
            name="ar_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                limit_choices_to={"is_postable": True},
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="accounting.account",
                verbose_name="konto kupaca",
            ),
        ),
        migrations.AddField(
            model_name="documenttype",
            name="ap_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                limit_choices_to={"is_postable": True},
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="accounting.account",
                verbose_name="konto dobavljaca",
            ),
        ),
        migrations.AddField(
            model_name="documenttype",
            name="vat_output_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                limit_choices_to={"is_postable": True},
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="accounting.account",
                verbose_name="konto PDV obveze",
            ),
        ),
        migrations.AddField(
            model_name="documenttype",
            name="vat_input_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                limit_choices_to={"is_postable": True},
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="accounting.account",
                verbose_name="konto pretporeza",
            ),
        ),
        migrations.AddField(
            model_name="documenttype",
            name="revenue_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                limit_choices_to={"is_postable": True},
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="accounting.account",
                verbose_name="konto prihoda",
            ),
        ),
        migrations.AddField(
            model_name="documenttype",
            name="expense_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                limit_choices_to={"is_postable": True},
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="accounting.account",
                verbose_name="konto rashoda",
            ),
        ),
        migrations.RunPython(map_default_accounts, migrations.RunPython.noop),
    ]
