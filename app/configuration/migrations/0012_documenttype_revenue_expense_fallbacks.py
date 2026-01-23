from django.db import migrations


def _first_by_prefix(accounts, prefix):
    return accounts.filter(code__startswith=prefix).order_by("code").first()


def _first_by_prefixes(accounts, prefixes):
    for prefix in prefixes:
        acc = _first_by_prefix(accounts, prefix)
        if acc:
            return acc
    return None


def _find_by_name_contains(accounts, *needles):
    qs = accounts
    for needle in needles:
        qs = qs.filter(name__icontains=needle)
    return qs.order_by("code").first()


def apply_revenue_expense_fallbacks(apps, schema_editor):
    DocumentType = apps.get_model("configuration", "DocumentType")
    Account = apps.get_model("accounting", "Account")
    Ledger = apps.get_model("accounting", "Ledger")

    ledger = Ledger.objects.filter(id=1).first()
    if not ledger:
        return

    accounts = Account.objects.filter(ledger=ledger, is_postable=True, is_active=True)

    revenue_fallback = (
        _first_by_prefix(accounts, "6")
        or _find_by_name_contains(accounts, "prihod")
    )
    expense_fallback = (
        _first_by_prefixes(accounts, ["5", "4"])
        or _find_by_name_contains(accounts, "rashod")
        or _find_by_name_contains(accounts, "troš")
    )

    for doc in DocumentType.objects.filter(ledger=ledger):
        changed = False
        if doc.revenue_account_id is None and revenue_fallback:
            doc.revenue_account = revenue_fallback
            changed = True
        if doc.expense_account_id is None and expense_fallback:
            doc.expense_account = expense_fallback
            changed = True
        if changed:
            doc.save(update_fields=["revenue_account", "expense_account"])


class Migration(migrations.Migration):

    dependencies = [
        ("configuration", "0011_documenttype_account_fallbacks"),
    ]

    operations = [
        migrations.RunPython(apply_revenue_expense_fallbacks, migrations.RunPython.noop),
    ]
