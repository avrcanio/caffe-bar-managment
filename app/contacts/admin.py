from django.contrib import admin, messages
from django.db import transaction

from artikli.remaris_connector import RemarisConnector
from contacts.models import Stuff, Supplier


@admin.action(description="Import zaposlenici from Remaris", permissions=["change"])
def import_contacts_from_remaris(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    payload = {
        "dataSource": "contactGridDS",
        "operationType": "fetch",
        "startRow": 0,
        "endRow": 75,
        "sortBy": ["name"],
        "textMatchStyle": "exact",
        "componentId": "contactGrid",
        "oldValues": None,
        "data": {"type": 1, "activeFilter": 3},
    }

    response = connector.post_json(
        "Contact/GetData?isc_dataFormat=json",
        payload,
        referer_path="/Contact",
    )

    data = response.get("response", {}).get("data", [])

    created = 0
    updated = 0
    skipped = 0

    with transaction.atomic():
        for item in data:
            rm_id = item.get("id")
            name = item.get("name")
            if rm_id is None or name is None:
                skipped += 1
                continue

            defaults = {
                "name": name,
                "name2": item.get("name2", ""),
                "card_number": item.get("cardNumber", ""),
                "tax_number": item.get("taxNumber", ""),
            }

            _, was_created = Stuff.objects.update_or_create(
                rm_id=rm_id,
                defaults=defaults,
            )
            if was_created:
                created += 1
            else:
                updated += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


@admin.action(description="Import dobavljaci from Remaris", permissions=["change"])
def import_suppliers_from_remaris(modeladmin, request, queryset):
    connector = RemarisConnector()
    connector.login()

    payload = {
        "dataSource": "contactGridDS",
        "operationType": "fetch",
        "startRow": 0,
        "endRow": 75,
        "sortBy": ["name"],
        "textMatchStyle": "exact",
        "componentId": "contactGrid",
        "data": {
            "type": 3,
            "activeFilter": {"Class": "Number"},
        },
        "oldValues": None,
    }

    response = connector.post_json(
        "Contact/GetData?isc_dataFormat=json",
        payload,
        referer_path="/Contact",
    )

    data = response.get("response", {}).get("data", [])

    created = 0
    updated = 0
    skipped = 0

    with transaction.atomic():
        for item in data:
            rm_id = item.get("id")
            name = item.get("name")
            if rm_id is None or name is None:
                skipped += 1
                continue

            defaults = {
                "name": name,
                "town": item.get("town", "") or "",
                "street": item.get("street", "") or "",
                "tax_number": item.get("taxNumber", "") or "",
                "mobile_devices": item.get("mobileDevices") or [],
            }

            _, was_created = Supplier.objects.update_or_create(
                rm_id=rm_id,
                defaults=defaults,
            )
            if was_created:
                created += 1
            else:
                updated += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


@admin.register(Stuff)
class StuffAdmin(admin.ModelAdmin):
    list_display = ("rm_id", "name", "name2", "card_number", "tax_number")
    search_fields = ("rm_id", "name", "name2", "card_number", "tax_number")
    actions = [import_contacts_from_remaris]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = (
        "rm_id",
        "name",
        "orders_email",
        "show_prices_on_order",
        "town",
        "street",
        "tax_number",
    )
    search_fields = ("rm_id", "name", "orders_email", "town", "street", "tax_number")
    actions = [import_suppliers_from_remaris]
