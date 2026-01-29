from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Exists, OuterRef, Sum
from django.utils import timezone
from mptt.admin import TreeRelatedFieldListFilter

from sales.models import (
    Representation,
    RepresentationItem,
    RepresentationReason,
    SalesInvoice,
    SalesInvoiceItem,
    SalesZPosting,
)
from sales.remaris_importer import import_sales_invoices, load_import_defaults
from sales.services import create_sales_z, get_sales_z_summary, post_sales_z_posting


def _store_z_results(request, *, title: str, results: list[dict]):
    request.session["z_batch_title"] = title
    request.session["z_batch_results"] = results


class SalesInvoiceItemInline(admin.TabularInline):
    model = SalesInvoiceItem
    extra = 0
    max_num = 0
    can_delete = False
    readonly_fields = (
        "product_name",
        "artikl",
        "quantity",
        "amount",
        "discount_value",
        "discount_percent",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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


@admin.action(description="Pripremi Z zapis (dnevno)", permissions=["change"])
def post_sales_z_action(modeladmin, request, queryset):
    combos = set(queryset.values_list("issued_on", "location_id", "pos_id"))
    created = 0
    skipped = 0
    results: list[dict] = []
    for issued_on, location_id, pos_id in sorted(combos):
        summary = get_sales_z_summary(
            issued_on=issued_on,
            location_id=location_id,
            pos_id=pos_id,
        )
        try:
            create_sales_z(
                issued_on=issued_on,
                location_id=location_id,
                pos_id=pos_id,
            )
            created += 1
            status = "created"
            note = ""
        except Exception as exc:
            skipped += 1
            status = "skipped"
            note = str(exc)

        results.append(
            {
                "issued_on": str(summary["issued_on"]),
                "location_id": summary["location_id"],
                "pos_id": summary["pos_id"],
                "net_amount": f"{summary['net_amount']:.2f}",
                "vat_amount": f"{summary['vat_amount']:.2f}",
                "total_amount": f"{summary['total_amount']:.2f}",
                "status": status,
                "note": note,
            }
        )

    modeladmin.message_user(
        request,
        f"Z zapis kreiran. created={created} skipped={skipped}",
        level=messages.SUCCESS,
    )
    if results:
        _store_z_results(request, title="Rezultat Z knjiženja (akcija)", results=results)



@admin.register(SalesInvoice)
class SalesInvoiceAdmin(admin.ModelAdmin):
    class SalesInvoiceAdminForm(forms.ModelForm):
        issued_on = forms.DateField(
            required=False,
            input_formats=["%d.%m.%Y", "%Y-%m-%d"],
            widget=forms.DateInput(format="%d.%m.%Y"),
        )
        issued_at = forms.DateTimeField(
            required=False,
            input_formats=["%d.%m.%Y %H:%M", "%d.%m.%Y %H.%M", "%Y-%m-%d %H:%M:%S"],
            widget=forms.DateTimeInput(format="%d.%m.%Y %H:%M"),
        )

        class Meta:
            model = SalesInvoice
            fields = "__all__"

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
                totals = base_qs.filter(issued_on__gte=start, issued_on__lte=end).aggregate(
                    total=Sum("total_amount"),
                    net=Sum("net_amount"),
                    vat=Sum("vat_amount"),
                )
                total = (totals.get("total") or Decimal("0.00")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                net = (totals.get("net") or Decimal("0.00")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                vat = (totals.get("vat") or Decimal("0.00")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                lookups.append((key, f"{label} (net {net:.2f} | PDV {vat:.2f} | bruto {total:.2f})", start, end))
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
        "issued_on_display",
        "issued_at_display",
        "location_name",
        "waiter_name",
        "buyer_name",
        "net_amount",
        "vat_amount",
        "total_amount",
        "currency",
        "z_included",
        "z_posted",
    )
    list_display_links = ("rm_number",)
    readonly_fields = ("issued_on", "issued_at")
    list_filter = (IssuedOnTotalFilter, "issued_on", "waiter_name")
    search_fields = ("rm_number", "location_name", "waiter_name", "buyer_name", "issued_on__exact")
    actions = [import_sales_invoices_action, post_sales_z_action]
    change_list_template = "admin/sales/salesinvoice/change_list.html"
    inlines = [SalesInvoiceItemInline]
    form = SalesInvoiceAdminForm

    @admin.display(description="issued on", ordering="issued_on")
    def issued_on_display(self, obj):
        return obj.issued_on.strftime("%d.%m.%Y") if obj.issued_on else ""

    @admin.display(description="issued at", ordering="issued_at")
    def issued_at_display(self, obj):
        return obj.issued_at.strftime("%d.%m.%Y %H:%M") if obj.issued_at else ""

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
        response.context_data["z_batch_title"] = request.session.pop("z_batch_title", None)
        response.context_data["z_batch_results"] = request.session.pop("z_batch_results", None)
        return response

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        z_qs = SalesZPosting.objects.filter(
            issued_on=OuterRef("issued_on"),
            location_id=OuterRef("location_id"),
            pos_id=OuterRef("pos_id"),
        )
        return qs.annotate(
            _z_included=Exists(z_qs),
            _z_posted=Exists(z_qs.filter(journal_entry__isnull=False)),
        )

    @admin.display(boolean=True, description="u Z", ordering="_z_included")
    def z_included(self, obj):
        return getattr(obj, "_z_included", False)

    @admin.display(boolean=True, description="Z → journal", ordering="_z_posted")
    def z_posted(self, obj):
        return getattr(obj, "_z_posted", False)


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


@admin.register(SalesZPosting)
class SalesZPostingAdmin(admin.ModelAdmin):
    list_display = (
        "issued_on_display",
        "location_id",
        "pos_id",
        "net_amount",
        "vat_amount",
        "total_amount",
        "cash_account",
        "revenue_account",
        "vat_account",
        "journal_entry",
        "posted_at",
        "posted_by",
    )
    list_filter = ("issued_on", "location_id", "pos_id")
    search_fields = ("issued_on", "location_id", "pos_id")
    autocomplete_fields = ("cash_account", "revenue_account", "vat_account")
    actions = ["post_z_to_journal_action"]

    @admin.action(description="Post Z u Journal", permissions=["change"])
    def post_z_to_journal_action(self, request, queryset):
        created = 0
        skipped = 0
        results: list[dict] = []
        for posting in queryset:
            try:
                post_sales_z_posting(posting=posting, posted_by=request.user)
                created += 1
                status = "posted"
                note = ""
            except Exception as exc:
                skipped += 1
                status = "skipped"
                note = str(exc)
            results.append(
                {
                    "issued_on": str(posting.issued_on),
                    "location_id": posting.location_id,
                    "pos_id": posting.pos_id,
                    "net_amount": f"{posting.net_amount:.2f}",
                    "vat_amount": f"{posting.vat_amount:.2f}",
                    "total_amount": f"{posting.total_amount:.2f}",
                    "status": status,
                    "note": note,
                }
            )

        self.message_user(
            request,
            f"Post Z završeno. posted={created} skipped={skipped}",
            level=messages.SUCCESS,
        )
        if results:
            _store_z_results(request, title="Post Z rezultati", results=results)

    @admin.display(description="issued on", ordering="issued_on")
    def issued_on_display(self, obj):
        return obj.issued_on.strftime("%d.%m.%Y") if obj.issued_on else ""


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
