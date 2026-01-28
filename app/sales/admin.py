from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import admin, messages
from django.db.models import Count, Sum
from django.utils import timezone
from mptt.admin import TreeRelatedFieldListFilter

from sales.models import (
    Representation,
    RepresentationItem,
    RepresentationReason,
    SalesInvoice,
    SalesInvoiceItem,
)
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
    class IssuedOnTotalFilter(admin.SimpleListFilter):
        title = "issued on"
        parameter_name = "issued_on_range"

        def lookups(self, request, model_admin):
            base_qs = model_admin.get_queryset(request)
            today = timezone.localdate()
            ranges = [
                ("today", "Danas", today, today),
                ("last7", "Prošlih 7 dana", today - timedelta(days=6), today),
                ("month", "Ovaj mjesec", today.replace(day=1), today),
                ("year", "Ova godina", date(today.year, 1, 1), today),
            ]
            lookups = [("any", "Bilo koji datum", None, None)]
            for key, label, start, end in ranges:
                total = (
                    base_qs.filter(issued_on__gte=start, issued_on__lte=end)
                    .aggregate(total=Sum("total_amount"))
                    .get("total")
                    or Decimal("0.00")
                )
                total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                lookups.append((key, f"{label} ({total:.2f})", start, end))
            return [(key, label) for key, label, _, _ in lookups]

        def queryset(self, request, queryset):
            value = self.value()
            if not value or value == "any":
                return queryset
            today = timezone.localdate()
            if value == "today":
                return queryset.filter(issued_on=today)
            if value == "last7":
                return queryset.filter(
                    issued_on__gte=today - timedelta(days=6),
                    issued_on__lte=today,
                )
            if value == "month":
                return queryset.filter(issued_on__gte=today.replace(day=1), issued_on__lte=today)
            if value == "year":
                return queryset.filter(
                    issued_on__gte=date(today.year, 1, 1),
                    issued_on__lte=today,
                )
            return queryset

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
    list_filter = (IssuedOnTotalFilter, "waiter_name")
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
    class DrinkCategoryTreeCountFilter(TreeRelatedFieldListFilter):
        title = "kategorija napitaka"

        def __init__(self, field, request, params, model, model_admin, field_path):
            super().__init__(field, request, params, model, model_admin, field_path)
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

            raw_counts = {
                row["artikl__drink_category_id"]: row["c"]
                for row in base_qs
                .filter(artikl__drink_category_id__isnull=False)
                .values("artikl__drink_category_id")
                .annotate(c=Count("id"))
            }

            categories = list(self.other_model.objects.all().only("id", "parent_id"))
            children = {}
            totals = {}
            for cat in categories:
                children.setdefault(cat.parent_id, []).append(cat.id)

            def compute_total(cat_id):
                if cat_id in totals:
                    return totals[cat_id]
                total = raw_counts.get(cat_id, 0)
                for child_id in children.get(cat_id, []):
                    total += compute_total(child_id)
                totals[cat_id] = total
                return total

            for cat in categories:
                compute_total(cat.id)

            self._counts = totals

        def choices(self, cl):
            yield {
                "selected": self.lookup_val is None and not self.lookup_val_isnull,
                "query_string": cl.get_query_string(
                    {}, [self.changed_lookup_kwarg, self.lookup_kwarg_isnull]
                ),
                "display": "Svi",
            }
            for pk_val, val, padding_style in self.lookup_choices:
                count = self._counts.get(pk_val, 0)
                yield {
                    "selected": self.lookup_val == str(pk_val),
                    "query_string": cl.get_query_string(
                        {self.changed_lookup_kwarg: pk_val},
                        [self.lookup_kwarg_isnull],
                    ),
                    "display": f"{val} ({count})",
                    "padding_style": padding_style,
                }
            if self.lookup_val_isnull:
                yield {
                    "selected": True,
                    "query_string": cl.get_query_string(
                        {self.lookup_kwarg_isnull: "True"},
                        [self.changed_lookup_kwarg],
                    ),
                    "display": "-",
                }

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

    list_filter = (("artikl__drink_category", DrinkCategoryTreeCountFilter), ArtiklInSalesFilter, "invoice__issued_on")
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


class RepresentationItemInline(admin.TabularInline):
    model = RepresentationItem
    extra = 0
    autocomplete_fields = ("artikl",)


@admin.register(Representation)
class RepresentationAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "warehouse", "user", "reason", "total_items", "total_quantity")
    list_filter = ("reason", "warehouse")
    search_fields = ("note", "user__username", "user__first_name", "user__last_name")
    fields = ("occurred_at", "warehouse", "user", "reason", "note")
    readonly_fields = ("occurred_at", "user")
    inlines = [RepresentationItemInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            _items_count=Count("items"),
            _items_qty=Sum("items__quantity"),
        )

    @admin.display(description="Stavke", ordering="_items_count")
    def total_items(self, obj):
        return obj._items_count or 0

    @admin.display(description="Kolicina", ordering="_items_qty")
    def total_quantity(self, obj):
        qty = obj._items_qty
        if qty is None:
            return "0,0000"
        return f"{qty:.4f}".replace(".", ",")

    def save_model(self, request, obj, form, change):
        if not obj.user_id:
            obj.user = request.user
        super().save_model(request, obj, form, change)


@admin.register(RepresentationReason)
class RepresentationReasonAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
