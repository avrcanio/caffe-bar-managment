from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


def _copy_from_legacy_purchases_table(schema_editor):
    connection = schema_editor.connection
    existing_tables = set(connection.introspection.table_names())
    if "purchases_supplierinvoice" not in existing_tables:
        return

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO orders_supplierinvoice (
                id,
                invoice_number,
                invoice_date,
                received_at,
                due_date,
                payment_terms,
                payment_status,
                deposit_total,
                total_net,
                total_vat,
                total_gross,
                notes,
                paid_cash,
                paid_at,
                paid_amount,
                ap_account_id,
                cash_account_id,
                deposit_account_id,
                document_type_id,
                journal_entry_id,
                payment_account_id,
                supplier_id
            )
            SELECT
                id,
                invoice_number,
                invoice_date,
                received_at,
                due_date,
                payment_terms,
                payment_status,
                deposit_total,
                total_net,
                total_vat,
                total_gross,
                notes,
                paid_cash,
                paid_at,
                paid_amount,
                ap_account_id,
                cash_account_id,
                deposit_account_id,
                document_type_id,
                journal_entry_id,
                payment_account_id,
                supplier_id
            FROM purchases_supplierinvoice
            ON CONFLICT (id) DO NOTHING
            """
        )

        if "purchases_supplierinvoice_inputs" in existing_tables:
            cursor.execute(
                """
                INSERT INTO orders_supplierinvoice_inputs (
                    supplierinvoice_id,
                    warehouseinput_id
                )
                SELECT
                    supplierinvoice_id,
                    warehouseinput_id
                FROM purchases_supplierinvoice_inputs
                ON CONFLICT DO NOTHING
                """
            )

        if connection.vendor == "postgresql":
            cursor.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('orders_supplierinvoice', 'id'),
                    COALESCE((SELECT MAX(id) FROM orders_supplierinvoice), 1),
                    true
                )
                """
            )


def copy_supplier_invoices_from_purchases(apps, schema_editor):
    _copy_from_legacy_purchases_table(schema_editor)


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0027_warehouseinput_supplier_return_journal_entry_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierInvoice",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("invoice_number", models.CharField(max_length=50)),
                ("invoice_date", models.DateField()),
                ("received_at", models.DateField(blank=True, null=True)),
                ("due_date", models.DateField(blank=True, null=True)),
                (
                    "payment_terms",
                    models.CharField(
                        choices=[("cash", "Gotovina"), ("deferred", "Odgoda")],
                        default="cash",
                        max_length=20,
                    ),
                ),
                (
                    "payment_status",
                    models.CharField(
                        choices=[
                            ("unpaid", "Neplaceno"),
                            ("partial", "Djelomicno"),
                            ("paid", "Placeno"),
                        ],
                        default="unpaid",
                        max_length=20,
                    ),
                ),
                (
                    "deposit_total",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=12,
                    ),
                ),
                (
                    "total_net",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=12,
                    ),
                ),
                (
                    "total_vat",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=12,
                    ),
                ),
                (
                    "total_gross",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=12,
                    ),
                ),
                ("notes", models.TextField(blank=True, default="")),
                ("paid_cash", models.BooleanField(default=False)),
                ("paid_at", models.DateField(blank=True, null=True)),
                (
                    "paid_amount",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=12,
                    ),
                ),
                (
                    "ap_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.account",
                    ),
                ),
                (
                    "cash_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.account",
                    ),
                ),
                (
                    "deposit_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.account",
                    ),
                ),
                (
                    "document_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="supplier_invoices",
                        to="configuration.documenttype",
                    ),
                ),
                (
                    "journal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="supplier_invoice",
                        to="accounting.journalentry",
                    ),
                ),
                (
                    "payment_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.account",
                    ),
                ),
                (
                    "supplier",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="supplier_invoices",
                        to="contacts.supplier",
                    ),
                ),
                (
                    "inputs",
                    models.ManyToManyField(
                        blank=True,
                        related_name="supplier_invoices",
                        to="orders.warehouseinput",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ulazni račun",
                "verbose_name_plural": "Ulazni računi",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("supplier", "invoice_number"),
                        name="uq_orders_supplier_invoice_number",
                    )
                ],
            },
        ),
        migrations.RunPython(
            copy_supplier_invoices_from_purchases,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
