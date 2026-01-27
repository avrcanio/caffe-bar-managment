from celery import shared_task
from django.utils import timezone

from sales.remaris_importer import import_sales_invoices, load_import_defaults


@shared_task
def import_sales_invoices_today() -> dict:
    today = timezone.localdate()
    defaults = load_import_defaults()
    created, updated, skipped = import_sales_invoices(
        date_from=today,
        date_to=today,
        **defaults,
    )
    return {"created": created, "updated": updated, "skipped": skipped}
