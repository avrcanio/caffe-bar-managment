from decimal import Decimal, ROUND_HALF_UP

from django.contrib import admin, messages
from django.db.models import Sum, Count
from django.utils import timezone

from sales.models import SalesInvoice, SalesInvoiceItem
from artikli.models import DrinkCategory
from sales.remaris_importer import import_sales_invoices, load_import_defaults


@admin.action(description="Import promet (Remaris)", permissions=["change"])
def import_sales_invoices_action(modeladmin, request, queryset):
    date_from = timezone.localdate()
    date_to = date_from

    defaults = load_import_defaults()
    created, updated, skipped = import_sales_invoices(
        date_from=date_from,
        date_to=date_to,
        **defaults,
    )

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


@admin.register(SalesInvoice)
class SalesInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "rm_number",
        "issued_on",
        "issued_at",
        "location_name",
        "waiter_name",
        "buyer_name",
        "total_amount",
        "currency",
    )
    list_filter = ("issued_on", "waiter_name")
    search_fields = ("rm_number", "location_name", "waiter_name", "buyer_name")
    actions = [import_sales_invoices_action]
    change_list_template = "admin/sales/salesinvoice/change_list.html"

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            cl = response.context_data["cl"]
        except (AttributeError, KeyError):
            return response

        totals = cl.queryset.aggregate(total=Sum("total_amount"))
        total = totals.get("total") or Decimal("0.00")
        total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        response.context_data["grand_total_amount"] = f"{total:.2f}".replace(".", ",")
        return response


@admin.register(SalesInvoiceItem)
class SalesInvoiceItemAdmin(admin.ModelAdmin):
    list_display = ("invoice", "product_name", "artikl", "quantity", "amount")
    class DrinkCategoryTreeFilter(admin.SimpleListFilter):
        title = "kategorija napitaka"
        parameter_name = "drink_category"

        def lookups(self, request, model_admin):
            categories = list(DrinkCategory.objects.all().order_by("parent_id", "sort_order", "name"))
            base_qs = model_admin.get_queryset(request)
            date_filters = {}
            for key in (
                "invoice__issued_on__gte",
                "invoice__issued_on__lt",
                "invoice__issued_on__exact",
                "invoice__issued_on",
            ):
                if key in request.GET:
                    date_filters[key] = request.GET.get(key)
            if date_filters:
                base_qs = base_qs.filter(**date_filters)
            counts = {
                row["artikl__drink_category_id"]: row["c"]
                for row in base_qs
                .filter(artikl_id__isnull=False)
                .values("artikl__drink_category_id")
                .annotate(c=Count("id"))
            }
            children = {}
            total_counts = {}
            for cat in categories:
                children.setdefault(cat.parent_id, []).append(cat)

            def compute_total(cat_id):
                if cat_id in total_counts:
                    return total_counts[cat_id]
                total = counts.get(cat_id, 0)
                for child in children.get(cat_id, []):
                    total += compute_total(child.id)
                total_counts[cat_id] = total
                return total

            for cat in categories:
                compute_total(cat.id)

            def walk(parent_id=None, depth=0):
                for cat in children.get(parent_id, []):
                    indent = "-- " * depth
                    total = total_counts.get(cat.id, 0)
                    yield (str(cat.id), f"{indent}{cat.name} ({total})")
                    yield from walk(cat.id, depth + 1)

            return list(walk(None, 0))

        def queryset(self, request, queryset):
            if self.value():
                selected_id = int(self.value())
                categories = list(DrinkCategory.objects.all().only("id", "parent_id"))
                children = {}
                for cat in categories:
                    children.setdefault(cat.parent_id, []).append(cat.id)

                to_visit = [selected_id]
                all_ids = set()
                while to_visit:
                    current = to_visit.pop()
                    if current in all_ids:
                        continue
                    all_ids.add(current)
                    to_visit.extend(children.get(current, []))

                return queryset.filter(artikl__drink_category_id__in=all_ids)
            return queryset

    class ArtiklInSalesFilter(admin.SimpleListFilter):
        title = "artikl"
        parameter_name = "artikl"

        def lookups(self, request, model_admin):
            qs = (
                SalesInvoiceItem.objects
                .filter(artikl_id__isnull=False)
                .select_related("artikl")
                .values_list("artikl_id", "artikl__name")
                .distinct()
                .order_by("artikl__name")
            )
            return [(str(artikl_id), name) for artikl_id, name in qs]

        def queryset(self, request, queryset):
            if self.value():
                return queryset.filter(artikl_id=self.value())
            return queryset

    list_filter = (DrinkCategoryTreeFilter, ArtiklInSalesFilter, "invoice__issued_on")
    search_fields = ("product_name", "invoice__rm_number", "artikl__name", "artikl__code")
    autocomplete_fields = ("artikl",)
    change_list_template = "admin/sales/salesinvoiceitem/change_list.html"

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            cl = response.context_data["cl"]
        except (AttributeError, KeyError):
            return response

        totals = cl.queryset.aggregate(
            qty=Sum("quantity"),
            amt=Sum("amount"),
        )
        qty = totals.get("qty") or Decimal("0.0000")
        amt = totals.get("amt") or Decimal("0.00")

        qty = qty.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        amt = amt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        response.context_data["totals_quantity"] = f"{qty:.4f}".replace(".", ",")
        response.context_data["totals_amount"] = f"{amt:.2f}".replace(".", ",")
        return response
