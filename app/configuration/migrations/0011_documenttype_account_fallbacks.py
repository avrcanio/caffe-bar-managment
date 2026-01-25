from django.db import migrations


def _first_by_prefix(accounts, prefix):
    return accounts.filter(code__startswith=prefix).order_by("code").first()


def _find_by_name(accounts, *needles):
    qs = accounts
    for needle in needles:
        qs = qs.filter(name__icontains=needle)
    return qs.order_by("code").first()


def apply_account_fallbacks(apps, schema_editor):
    DocumentType = apps.get_model("configuration", "DocumentType")
    Account = apps.get_model("accounting", "Account")
    Ledger = apps.get_model("accounting", "Ledger")

    ledger = Ledger.objects.filter(id=1).first()
    if not ledger:
        return

    accounts = Account.objects.filter(ledger=ledger, is_postable=True, is_active=True)

    ar_fallback = (
        accounts.filter(code="1310").first()
        or _first_by_prefix(accounts, "13")
    )
    ap_fallback = (
        accounts.filter(code="2200").first()
        or _first_by_prefix(accounts, "22")
    )
    vat_output_fallback = (
        _find_by_name(accounts, "pdv", "obve")
        or _find_by_name(accounts, "pdv", "izlaz")
    )
    vat_input_fallback = (
        _find_by_name(accounts, "pretporez")
        or _find_by_name(accounts, "pdv", "ulaz")
    )

    for doc in DocumentType.objects.filter(ledger=ledger):
        changed = False
        if doc.ar_account_id is None and ar_fallback:
            doc.ar_account = ar_fallback
            changed = True
        if doc.ap_account_id is None and ap_fallback:
            doc.ap_account = ap_fallback
            changed = True
        if doc.vat_output_account_id is None and vat_output_fallback:
            doc.vat_output_account = vat_output_fallback
            changed = True
        if doc.vat_input_account_id is None and vat_input_fallback:
            doc.vat_input_account = vat_input_fallback
            changed = True
        if changed:
            doc.save(
                update_fields=[
                    "ar_account",
                    "ap_account",
                    "vat_output_account",
                    "vat_input_account",
                ]
            )


class Migration(migrations.Migration):

    dependencies = [
        ("configuration", "0010_documenttype_accounting_fks"),
    ]

    operations = [
        migrations.RunPython(apply_account_fallbacks, migrations.RunPython.noop),
    ]
