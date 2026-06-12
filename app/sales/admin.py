from datetime import date, datetime, timedelta
import logging
from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.views.main import ChangeList
from django.db.models import Count, Exists, OuterRef, Q, Subquery, Sum
from django.db.models import CharField, Value
from django.db.models.functions import Cast, Concat
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.utils.html import format_html, format_html_join
from stock.models import StockMove, StockMoveLine, WarehouseTransfer, WarehouseTransferItem, WarehouseId
from django.utils import timezone
from mptt.admin import TreeRelatedFieldListFilter

from artikli.models import NormativItem
from sales.models import (
    FiscalReceipt,
    Representation,
    RepresentationItem,
    RepresentationReason,
    SalesInvoice,
    SalesInvoiceItem,
    SalesPriceItem,
    SalesPriceList,
    SalesPriceRule,
    SalesPriceRuleItem,
    ShiftTurnover,
    ShiftTurnoverClose,
    ShiftTurnoverExpense,
    ShiftCashHandover,
    SalesZPosting,
)
from sales.fiscal import fiscalize_sales_invoice
from sales.remaris_importer import import_sales_invoices, load_import_defaults
from sales.remaris_pricelist import (
    resolve_remaris_price_list_id,
    sync_sales_pricelist_to_remaris,
    transfer_sales_prices_to_pos,
)
from sales.services import create_sales_z, get_sales_z_summary, post_sales_items_stock_out, post_sales_z_posting, resolve_waiter_user, build_stock_in_lines_for_items
from stock.services import post_stock_in

logger = logging.getLogger(__name__)


def _store_z_results(request, *, title: str, results: list[dict]):
    request.session["z_batch_title"] = title
    request.session["z_batch_results"] = results


def _parse_datetime_local(value: str):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed:
        return parsed
    for fmt in (
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y %H.%M",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


class _IgnoreIssuedAtParamsChangeList(ChangeList):
    def get_filters_params(self, params=None):
        params = super().get_filters_params(params)
        for key in (
            "issued_at__gte",
            "issued_at__lte",
            "invoice__issued_at__gte",
            "invoice__issued_at__lte",
        ):
            params.pop(key, None)
        return params


@admin.action(description="Fiskaliziraj odabrane racune", permissions=["change"])
def fiscalize_sales_invoices_action(modeladmin, request, queryset):
    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    for invoice in queryset:
        try:
            receipt, was_created = FiscalReceipt.objects.get_or_create(invoice=invoice)
            if receipt.status == FiscalReceipt.Status.SUCCESS:
                skipped += 1
                continue
            fiscalize_sales_invoice(invoice, user=request.user)
            if was_created:
                created += 1
            else:
                updated += 1
        except Exception as exc:
            errors.append(f"Racun {invoice.rm_number}: {exc}")

    modeladmin.message_user(
        request,
        f"Fiskalizacija: created={created} updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )
    for msg in errors[:20]:
        modeladmin.message_user(request, msg, level=messages.ERROR)


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
    try:
        created, updated, skipped = import_sales_invoices(
            date_from=date_from,
            date_to=date_to,
            **defaults,
        )
    except Exception as exc:
        modeladmin.message_user(
            request,
            f"Import nije uspio: {exc}",
            level=messages.ERROR,
        )
        return
    mapped = 0
    for invoice in SalesInvoice.objects.filter(issued_on__gte=date_from, issued_on__lte=date_to, user__isnull=True):
        user = resolve_waiter_user(invoice.waiter_name)
        if user:
            invoice.user = user
            invoice.save(update_fields=["user"])
            mapped += 1

    modeladmin.message_user(
        request,
        f"Import complete. created={created} updated={updated} skipped={skipped} mapped={mapped}",
        level=messages.SUCCESS,
    )


@admin.action(description="Pripremi Z zapis (dnevno)", permissions=["change"])
def post_sales_z_action(modeladmin, request, queryset):
    from stock.models import WarehouseId
    from pos.models import Pos
    combos = set(queryset.values_list("issued_on", "warehouse_id", "pos_id"))
    created = 0
    skipped = 0
    results: list[dict] = []
    for issued_on, warehouse_id, pos_id in sorted(combos):
        summary = get_sales_z_summary(
            issued_on=issued_on,
            warehouse_id=warehouse_id,
            pos_id=pos_id,
        )
        try:
            create_sales_z(
                issued_on=issued_on,
                warehouse_id=warehouse_id,
                pos_id=pos_id,
            )
            created += 1
            status = "created"
            note = ""
        except Exception as exc:
            skipped += 1
            status = "skipped"
            note = str(exc)

        warehouse_label = WarehouseId.objects.filter(id=warehouse_id).values_list("name", flat=True).first() or str(warehouse_id or "")
        pos_label = Pos.objects.filter(id=pos_id).values_list("name", flat=True).first() or str(pos_id or "")
        results.append(
            {
                "issued_on": str(summary["issued_on"]),
                "warehouse": warehouse_label,
                "pos": pos_label,
                "net_amount": f"{summary['net_amount']:.2f}",
                "vat_amount": f"{summary['vat_amount']:.2f}",
                "pnp_amount": f"{summary.get('pnp_amount', 0):.2f}",
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


@admin.action(description="Kreiraj promet smjene", permissions=["change"])
def create_shift_turnover_action(modeladmin, request, queryset):
    created = 0
    skipped = 0
    results: list[str] = []
    groups = {}
    for invoice in queryset:
        key = (invoice.issued_on, invoice.user_id, invoice.warehouse_id, invoice.pos_id)
        groups.setdefault(key, []).append(invoice)

    for (issued_on, user_id, warehouse_id, pos_id), invoices in groups.items():
        if ShiftTurnover.objects.filter(
            issued_on=issued_on,
            user_id=user_id,
            warehouse_id=warehouse_id,
            pos_id=pos_id,
        ).exists():
            skipped += 1
            continue
        cash_invoices = [inv for inv in invoices if not getattr(inv, "is_card", False)]
        total = sum((inv.total_amount or Decimal("0.00")) for inv in cash_invoices)
        ShiftTurnover.objects.create(
            issued_on=issued_on,
            user_id=user_id,
            warehouse_id=warehouse_id,
            pos_id=pos_id,
            total_amount=total,
            invoice_count=len(cash_invoices),
            invoice_ids=[inv.id for inv in cash_invoices],
        )
        created += 1
        results.append(f"{issued_on} user={user_id} wh={warehouse_id} pos={pos_id}")

    modeladmin.message_user(
        request,
        f"Promet smjene: created={created} skipped={skipped}",
        level=messages.SUCCESS,
    )

@admin.action(description="Mapiraj konobara (waiter_name -> user)", permissions=["change"])
def map_waiter_user_action(modeladmin, request, queryset):
    updated = 0
    skipped = 0
    for invoice in queryset:
        if invoice.user_id:
            skipped += 1
            continue
        user = resolve_waiter_user(invoice.waiter_name)
        if not user:
            skipped += 1
            continue
        invoice.user = user
        invoice.save(update_fields=["user"])
        updated += 1
    modeladmin.message_user(
        request,
        f"Mapiranje konobara gotovo. updated={updated} skipped={skipped}",
        level=messages.SUCCESS,
    )


@admin.action(description="Označi kao kartica", permissions=["change"])
def mark_invoices_as_card_action(modeladmin, request, queryset):
    updated = queryset.exclude(is_card=True).update(is_card=True)
    modeladmin.message_user(
        request,
        f"Oznaceno kao kartica: {updated}",
        level=messages.SUCCESS,
    )


@admin.register(SalesInvoice)
class SalesInvoiceAdmin(admin.ModelAdmin):
    class SalesInvoiceAdminForm(forms.ModelForm):
        issued_on = forms.DateField(
            required=False,
            input_formats=["%d.%m.%Y", "%Y-%m-%d"],
            widget=forms.DateInput(format="%d.%m.%Y", attrs={"class": "js-flatpickr-date"}),
        )
        issued_at = forms.DateTimeField(
            required=False,
            input_formats=["%d.%m.%Y %H:%M", "%d.%m.%Y %H.%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"],
            widget=forms.DateTimeInput(format="%d.%m.%Y %H:%M", attrs={"class": "js-flatpickr-datetime"}),
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
        "report_from_display",
        "issued_on_display",
        "issued_at_display",
        "location_name",
        "waiter_name",
        "user",
        "buyer_name",
        "net_amount",
        "vat_amount",
        "total_amount",
        "currency",
        "is_card",
        "z_included",
        "z_posted",
        "stock_out_done",
    )
    list_display_links = ("rm_number",)
    readonly_fields = ("report_from", "issued_on", "issued_at")
    list_filter = (IssuedOnTotalFilter, "report_from", "issued_on", "waiter_name", "user")
    search_fields = ("rm_number", "location_name", "waiter_name", "buyer_name", "issued_on__exact", "user__username")
    inlines = [SalesInvoiceItemInline]
    actions = [
        import_sales_invoices_action,
        post_sales_z_action,
        fiscalize_sales_invoices_action,
        map_waiter_user_action,
        mark_invoices_as_card_action,
        create_shift_turnover_action,
    ]
    change_list_template = "admin/sales/salesinvoice/change_list.html"

    def get_changelist(self, request, **kwargs):
        return _IgnoreIssuedAtParamsChangeList

    def lookup_allowed(self, lookup, value):
        if lookup in ("issued_at__gte", "issued_at__lte"):
            return True
        return super().lookup_allowed(lookup, value)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        from django.utils import timezone

        issued_from_raw = request.GET.get("issued_at__gte")
        issued_to_raw = request.GET.get("issued_at__lte")

        if issued_from_raw:
            issued_from = _parse_datetime_local(issued_from_raw)
            if issued_from and timezone.is_naive(issued_from):
                issued_from = timezone.make_aware(issued_from)
            if issued_from:
                qs = qs.filter(issued_at__gte=issued_from)

        if issued_to_raw:
            issued_to = _parse_datetime_local(issued_to_raw)
            if issued_to and timezone.is_naive(issued_to):
                issued_to = timezone.make_aware(issued_to)
            if issued_to:
                qs = qs.filter(issued_at__lte=issued_to)

        z_qs = SalesZPosting.objects.filter(
            issued_on=OuterRef("issued_on"),
            warehouse_id=OuterRef("warehouse_id"),
            pos_id=OuterRef("pos_id"),
            ledger_id=OuterRef("ledger_id"),
        )
        move_qs = StockMove.objects.filter(
            move_type=StockMove.MoveType.OUT,
            reference=Concat(Value("POS racun "), Cast(OuterRef("rm_number"), output_field=CharField())),
        )
        return qs.annotate(
            _z_included=Exists(z_qs),
            _z_posted=Exists(z_qs.filter(journal_entry__isnull=False)),
            _stock_out_done=Exists(move_qs),
        )

    @admin.display(description="report from", ordering="report_from")
    def report_from_display(self, obj):
        return obj.report_from.strftime("%d.%m.%Y") if obj.report_from else ""

    @admin.display(description="issued on", ordering="issued_on")
    def issued_on_display(self, obj):
        return obj.issued_on.strftime("%d.%m.%Y") if obj.issued_on else ""

    @admin.display(description="issued at", ordering="issued_at")
    def issued_at_display(self, obj):
        if not obj.issued_at:
            return ""
        return timezone.localtime(obj.issued_at).strftime("%d.%m.%Y %H:%M")

    @admin.display(boolean=True, description="u Z", ordering="_z_included")
    def z_included(self, obj):
        return getattr(obj, "_z_included", False)

    @admin.display(boolean=True, description="Z → journal", ordering="_z_posted")
    def z_posted(self, obj):
        return getattr(obj, "_z_posted", False)

    @admin.display(boolean=True, description="robno", ordering="_stock_out_done")
    def stock_out_done(self, obj):
        return getattr(obj, "_stock_out_done", False)


@admin.register(ShiftTurnover)
class ShiftTurnoverAdmin(admin.ModelAdmin):
    list_display = (
        "issued_on",
        "user",
        "warehouse",
        "pos",
        "invoice_count",
        "total_amount",
        "created_at",
    )
    list_filter = ("issued_on", "warehouse", "pos", "user")
    search_fields = ("user__username",)
    readonly_fields = ("created_at",)


@admin.register(ShiftTurnoverClose)
class ShiftTurnoverCloseAdmin(admin.ModelAdmin):
    list_display = ("turnover", "cash_counted", "card_total", "created_by", "created_at")
    list_filter = ("created_at",)
    search_fields = ("turnover__user__username",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ShiftTurnoverExpense)
class ShiftTurnoverExpenseAdmin(admin.ModelAdmin):
    list_display = ("close", "amount", "note", "created_by", "created_at")
    list_filter = ("created_at",)
    search_fields = ("note", "close__turnover__user__username")
    readonly_fields = ("created_at",)


@admin.register(ShiftCashHandover)
class ShiftCashHandoverAdmin(admin.ModelAdmin):
    list_display = (
        "turnover",
        "kind",
        "expected_amount",
        "counted_amount",
        "difference_amount",
        "journal_entry_link",
        "created_by",
        "created_at",
    )
    list_filter = ("kind", "created_by", "created_at")
    search_fields = ("note", "turnover__user__username")
    readonly_fields = ("created_at", "difference_amount", "expected_amount")

    def journal_entry_link(self, obj):
        if not obj.journal_entry_id:
            return "-"
        url = reverse("admin:accounting_journalentry_change", args=[obj.journal_entry_id])
        return format_html('<a href="{}">#{}</a>', url, obj.journal_entry_id)

    journal_entry_link.short_description = "Temeljnica"


@admin.register(SalesInvoiceItem)
class SalesInvoiceItemAdmin(admin.ModelAdmin):
    list_display = ("invoice", "product_name", "artikl", "quantity", "amount", "stock_out_done", "stock_move_link")
    class CategoryTreeCountFilter(TreeRelatedFieldListFilter):
        title = "kategorija"

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
                row["artikl__category_id"]: row["c"]
                for row in base_qs
                .filter(artikl__category_id__isnull=False)
                .values("artikl__category_id")
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

    class StockOutDoneFilter(admin.SimpleListFilter):
        title = "robno"
        parameter_name = "stock_out_done"

        def lookups(self, request, model_admin):
            return (("1", "Da"), ("0", "Ne"))

        def queryset(self, request, queryset):
            value = self.value()
            if value == "1":
                return queryset.filter(
                    Q(stock_out_posted_at__isnull=False) | Q(_stock_out_done=True)
                )
            if value == "0":
                return queryset.filter(
                    stock_out_posted_at__isnull=True
                ).exclude(_stock_out_done=True)
            return queryset

    list_filter = (
        "invoice__issued_on",
        ("artikl__category", CategoryTreeCountFilter),
        ArtiklInSalesFilter,
        StockOutDoneFilter,
    )
    search_fields = ("product_name", "invoice__rm_number", "artikl__name", "artikl__code")
    autocomplete_fields = ("artikl",)
    change_list_template = "admin/sales/salesinvoiceitem/change_list.html"
    actions = ["post_sales_items_stock_out_action", "post_sales_items_stock_in_storno_action"]

    def get_changelist(self, request, **kwargs):
        return _IgnoreIssuedAtParamsChangeList

    def lookup_allowed(self, lookup, value):
        if lookup in ("invoice__issued_at__gte", "invoice__issued_at__lte"):
            return True
        return super().lookup_allowed(lookup, value)

    @admin.action(description="Robno razduži (stavke)", permissions=["change"])
    def post_sales_items_stock_out_action(self, request, queryset):
        created = 0
        skipped = 0
        errors: list[str] = []
        warnings: list[str] = []

        items_by_invoice = {}
        for item in queryset.select_related("invoice", "invoice__warehouse", "artikl"):
            if item.stock_out_posted_at:
                skipped += 1
                warnings.append(f"Stavka {item.id} već je razdužena.")
                continue
            if not item.invoice_id:
                skipped += 1
                errors.append(f"Stavka {item.id}: nema racun.")
                continue
            items_by_invoice.setdefault(item.invoice_id, {"invoice": item.invoice, "items": []})
            items_by_invoice[item.invoice_id]["items"].append(item)

        for data in items_by_invoice.values():
            invoice = data["invoice"]
            items = data["items"]
            try:
                move, skipped_items = post_sales_items_stock_out(
                    invoice=invoice,
                    items=items,
                    user=request.user,
                )
                created += 1
                SalesInvoiceItem.objects.filter(id__in=[i.id for i in items]).update(
                    stock_out_posted_at=timezone.now()
                )
                for msg in skipped_items:
                    warnings.append(f"Racun {invoice.rm_number}: {msg}")
            except Exception as exc:
                skipped += 1
                errors.append(f"Racun {invoice.rm_number}: {exc}")

        self.message_user(
            request,
            f"Razduzenje gotovo. created={created} skipped={skipped}",
            level=messages.SUCCESS,
        )
        for msg in warnings[:20]:
            self.message_user(request, msg, level=messages.WARNING)
        for msg in errors[:20]:
            self.message_user(request, msg, level=messages.ERROR)

    @admin.action(description="Storno razduži (stavke)", permissions=["change"])
    def post_sales_items_stock_in_storno_action(self, request, queryset):
        created = 0
        skipped = 0
        errors: list[str] = []
        warnings: list[str] = []

        items_by_invoice = {}
        for item in queryset.select_related("invoice", "invoice__warehouse", "artikl"):
            if item.stock_out_posted_at:
                skipped += 1
                warnings.append(f"Stavka {item.id} već je razdužena.")
                continue
            if not item.invoice_id:
                skipped += 1
                errors.append(f"Stavka {item.id}: nema racun.")
                continue
            items_by_invoice.setdefault(item.invoice_id, {"invoice": item.invoice, "items": []})
            items_by_invoice[item.invoice_id]["items"].append(item)

        for data in items_by_invoice.values():
            invoice = data["invoice"]
            items = data["items"]
            if not invoice.warehouse:
                skipped += 1
                errors.append(f"Racun {invoice.rm_number}: Racun nema vezano skladiste (warehouse).")
                continue
            try:
                lines, skipped_items = build_stock_in_lines_for_items(items)
                for msg in skipped_items:
                    warnings.append(f"Racun {invoice.rm_number}: {msg}")
                if not lines:
                    skipped += 1
                    continue
                post_stock_in(
                    warehouse=invoice.warehouse,
                    items=lines,
                    move_date=invoice.issued_at,
                    reference=f"Storno racun {invoice.rm_number}",
                    note="Storno razduzenje",
                )
                created += 1
                SalesInvoiceItem.objects.filter(id__in=[i.id for i in items]).update(
                    stock_out_posted_at=timezone.now()
                )
            except Exception as exc:
                skipped += 1
                errors.append(f"Racun {invoice.rm_number}: {exc}")

        self.message_user(
            request,
            f"Storno razduzenje gotovo. created={created} skipped={skipped}",
            level=messages.SUCCESS,
        )
        for msg in warnings[:20]:
            self.message_user(request, msg, level=messages.WARNING)
        for msg in errors[:20]:
            self.message_user(request, msg, level=messages.ERROR)

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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        from django.utils import timezone

        issued_from_raw = request.GET.get("invoice__issued_at__gte")
        issued_to_raw = request.GET.get("invoice__issued_at__lte")

        if issued_from_raw:
            issued_from = _parse_datetime_local(issued_from_raw)
            if issued_from and timezone.is_naive(issued_from):
                issued_from = timezone.make_aware(issued_from)
            if issued_from:
                qs = qs.filter(invoice__issued_at__gte=issued_from)

        if issued_to_raw:
            issued_to = _parse_datetime_local(issued_to_raw)
            if issued_to and timezone.is_naive(issued_to):
                issued_to = timezone.make_aware(issued_to)
            if issued_to:
                qs = qs.filter(invoice__issued_at__lte=issued_to)

        move_qs = StockMove.objects.filter(
            move_type=StockMove.MoveType.OUT,
            purpose=StockMove.Purpose.SALE,
            reference=Concat(
                Value("POS racun "),
                Cast(OuterRef("invoice__rm_number"), output_field=CharField()),
            ),
        ).values("id")[:1]
        ingredient_rm_ids = NormativItem.objects.filter(
            normativ__product_id=OuterRef("artikl_id"),
            normativ__is_active=True,
        ).values("ingredient__rm_id")
        move_line_qs = StockMoveLine.objects.filter(
            move__move_type=StockMove.MoveType.OUT,
            move__purpose=StockMove.Purpose.SALE,
            move__reference=Concat(
                Value("POS racun "),
                Cast(OuterRef("invoice__rm_number"), output_field=CharField()),
            ),
            warehouse_id=OuterRef("invoice__warehouse__rm_id"),
        ).filter(
            Q(artikl_id=OuterRef("artikl__rm_id")) | Q(artikl_id__in=Subquery(ingredient_rm_ids))
        )
        return qs.annotate(
            _stock_out_done=Exists(move_line_qs),
            _stock_move_id=Subquery(move_qs),
        )

    @admin.display(boolean=True, description="robno", ordering="_stock_out_done")
    def stock_out_done(self, obj):
        if getattr(obj, "stock_out_posted_at", None):
            return True
        return getattr(obj, "_stock_out_done", False)

    @admin.display(description="stock move", ordering="_stock_move_id")
    def stock_move_link(self, obj):
        move_id = getattr(obj, "_stock_move_id", None)
        if not move_id:
            return "-"
        url = reverse("admin:stock_stockmove_change", args=[move_id])
        return format_html('<a href="{}">#{}</a>', url, move_id)


@admin.register(SalesZPosting)
class SalesZPostingAdmin(admin.ModelAdmin):
    list_display = (
        "issued_on_display",
        "warehouse",
        "pos",
        "net_amount",
        "vat_amount",
        "pnp_amount",
        "total_amount",
        "cash_account",
        "revenue_account",
        "vat_account",
        "pnp_account",
        "journal_entry",
        "posted_at",
        "posted_by",
    )
    list_filter = ("issued_on", "warehouse", "pos")
    search_fields = ("issued_on", "warehouse__name", "pos__name")
    autocomplete_fields = ("cash_account", "revenue_account", "vat_account", "pnp_account")
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
                    "warehouse": posting.warehouse.name if posting.warehouse_id else "",
                    "pos": posting.pos.name if posting.pos_id else "",
                    "net_amount": f"{posting.net_amount:.2f}",
                    "vat_amount": f"{posting.vat_amount:.2f}",
                    "pnp_amount": f"{posting.pnp_amount:.2f}",
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


@admin.register(FiscalReceipt)
class FiscalReceiptAdmin(admin.ModelAdmin):
    list_display = ("invoice", "status", "zki", "jir", "payment_type", "sent_at", "updated_at")
    list_filter = ("status", "payment_type")
    search_fields = ("invoice__rm_number", "zki", "jir")
    readonly_fields = ("created_at", "updated_at", "sent_at", "xml_request", "xml_response", "qr_payload", "error_message")


class RepresentationItemInline(admin.TabularInline):
    model = RepresentationItem
    extra = 0
    autocomplete_fields = ("artikl",)


@admin.register(Representation)
class RepresentationAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "warehouse", "user", "reason", "total_items", "total_quantity")
    list_filter = ("reason", "warehouse")
    search_fields = ("note", "user__username", "user__first_name", "user__last_name")
    inlines = [RepresentationItemInline]

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("warehouse", "reason", "note")
        return ("occurred_at", "warehouse", "user", "reason", "note")

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return ("occurred_at", "user")

    def save_model(self, request, obj, form, change):
        if not obj.user_id:
            obj.user = request.user
        super().save_model(request, obj, form, change)

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


@admin.register(RepresentationItem)
class RepresentationItemAdmin(admin.ModelAdmin):
    list_display = ("representation", "artikl", "quantity", "price", "transfer_done")
    list_filter = ("representation__warehouse", "representation__occurred_at")
    search_fields = ("artikl__name", "artikl__code", "representation__note")
    actions = ["create_transfer_to_rep_warehouse"]

    @admin.action(description="Međuskladišnica za reprezentaciju → skladište Pomoćno (rm_id=8)", permissions=["change"])
    def create_transfer_to_rep_warehouse(self, request, queryset):
        created = 0
        skipped = 0
        errors: list[str] = []

        target_warehouse = WarehouseId.objects.filter(rm_id=8).first()
        if not target_warehouse:
            self.message_user(request, "Ne postoji WarehouseId rm_id=8 (Pomoćno).", level=messages.ERROR)
            return

        by_rep = {}
        for item in queryset.select_related("representation", "representation__warehouse", "artikl"):
            if item.transfer_posted_at:
                skipped += 1
                errors.append(f"Stavka {item.id} već je prebačena.")
                continue
            if not item.representation_id:
                skipped += 1
                errors.append(f"Stavka {item.id}: nema reprezentacije.")
                continue
            by_rep.setdefault(item.representation_id, {"rep": item.representation, "items": []})
            by_rep[item.representation_id]["items"].append(item)

        for data in by_rep.values():
            rep = data["rep"]
            items = data["items"]
            if not rep.warehouse_id:
                skipped += 1
                errors.append(f"Reprezentacija {rep.id}: nema skladište.")
                continue
            payload = {}
            for item in items:
                if not item.artikl_id:
                    continue
                if item.quantity <= 0:
                    continue
                normativ = getattr(item.artikl, "normativ", None)
                if normativ and normativ.items.exists():
                    for norm_item in normativ.items.select_related("ingredient"):
                        if not norm_item.ingredient_id:
                            continue
                        qty = norm_item.qty * item.quantity
                        if qty <= 0:
                            continue
                        entry = payload.setdefault(norm_item.ingredient_id, {"artikl": norm_item.ingredient, "quantity": 0})
                        entry["quantity"] += qty
                else:
                    entry = payload.setdefault(item.artikl_id, {"artikl": item.artikl, "quantity": 0})
                    entry["quantity"] += item.quantity
            if not payload:
                skipped += 1
                errors.append(f"Reprezentacija {rep.id}: nema stavki za transfer.")
                continue

            transfer = WarehouseTransfer.objects.create(
                from_warehouse=rep.warehouse,
                to_warehouse=target_warehouse,
                date=rep.occurred_at,
                dont_change_inventory_quantity=False,
                status=WarehouseTransfer.Status.DRAFT,
                created_by=request.user,
                note=f"Reprezentacija {rep.id} (FIFO)",
            )
            created_items = 0
            for entry in payload.values():
                artikl = entry["artikl"]
                quantity = entry["quantity"]
                if quantity <= 0:
                    continue
                WarehouseTransferItem.objects.create(
                    transfer=transfer,
                    artikl=artikl,
                    quantity=quantity,
                    unit=getattr(getattr(artikl, "detail", None), "unit_of_measure", None),
                )
                created_items += 1
            for item in items:
                item.transfer_posted_at = timezone.now()
                item.save(update_fields=["transfer_posted_at"])
            created += 1
            self.message_user(
                request,
                f"Reprezentacija {rep.id}: kreirano {created_items} stavki (normativno prošireno).",
                level=messages.INFO,
            )

        if created:
            self.message_user(request, f"Kreirano međuskladišnica: {created}", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Preskočeno: {skipped}", level=messages.WARNING)
        for msg in errors[:20]:
            self.message_user(request, msg, level=messages.ERROR)

    @admin.display(boolean=True, description="transfer", ordering="transfer_posted_at")
    def transfer_done(self, obj):
        return bool(obj.transfer_posted_at)

    def save_model(self, request, obj, form, change):
        if not obj.user_id:
            obj.user = request.user
        super().save_model(request, obj, form, change)


@admin.register(RepresentationReason)
class RepresentationReasonAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "code")


class SalesPriceItemInline(admin.TabularInline):
    class SalesPriceItemInlineForm(forms.ModelForm):
        unit_price_gross = forms.DecimalField(
            required=True,
            max_digits=12,
            decimal_places=2,
            localize=True,
        )

        class Meta:
            model = SalesPriceItem
            fields = "__all__"

        def clean_unit_price_gross(self):
            raw = self.data.get(self.add_prefix("unit_price_gross"), "")
            raw = raw.replace(",", ".").strip()
            if raw == "":
                return self.cleaned_data.get("unit_price_gross")
            try:
                value = Decimal(raw)
            except Exception:
                return self.cleaned_data.get("unit_price_gross")
            return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    model = SalesPriceItem
    extra = 0
    autocomplete_fields = ("artikl",)
    form = SalesPriceItemInlineForm


@admin.action(description="Sync price list items to Remaris", permissions=["change"])
def sync_sales_pricelist_to_remaris_action(modeladmin, request, queryset):
    if queryset.count() != 1:
        modeladmin.message_user(
            request,
            "Odaberi tocno jedan cjenik.",
            level=messages.ERROR,
        )
        return

    price_list = queryset.first()
    def _write_line(msg: str) -> None:
        level = messages.INFO
        if msg.startswith("ERROR"):
            level = messages.ERROR
        elif msg.startswith("SKIP"):
            level = messages.WARNING
        modeladmin.message_user(request, msg, level=level)

    try:
        remaris_price_list_id = resolve_remaris_price_list_id(price_list)
        sent, skipped, errors = sync_sales_pricelist_to_remaris(
            price_list=price_list,
            remaris_price_list_id=remaris_price_list_id,
            include_inactive=False,
            dry_run=False,
            write_line=_write_line,
        )
    except Exception as exc:
        modeladmin.message_user(
            request,
            f"Remaris sync nije uspio: {exc}",
            level=messages.ERROR,
        )
        return

    transfer_msg = ""
    if errors == 0 and price_list.remaris_sync_transfer_pos:
        try:
            transfer_sales_prices_to_pos()
            transfer_msg = " POS transfer OK."
        except Exception as exc:
            modeladmin.message_user(
                request,
                f"Remaris sync OK, ali POS transfer nije uspio: {exc}",
                level=messages.WARNING,
            )
            return

    modeladmin.message_user(
        request,
        f"Remaris sync (priceListId={remaris_price_list_id}): "
        f"sent={sent} skipped={skipped} errors={errors}.{transfer_msg}",
        level=messages.SUCCESS if errors == 0 else messages.WARNING,
    )


@admin.action(description="Transfer prices to POS (Remaris)", permissions=["change"])
def transfer_sales_prices_to_pos_action(modeladmin, request, queryset):
    if queryset.count() != 1:
        modeladmin.message_user(
            request,
            "Odaberi tocno jedan cjenik.",
            level=messages.ERROR,
        )
        return

    try:
        response = transfer_sales_prices_to_pos()
    except Exception as exc:
        modeladmin.message_user(
            request,
            f"Remaris transfer nije uspio: {exc}",
            level=messages.ERROR,
        )
        return

    modeladmin.message_user(
        request,
        f"Remaris transfer OK: {response}",
        level=messages.SUCCESS,
    )


def _sales_price_items_table(obj: SalesPriceList) -> str:
    items = (
        obj.items.select_related("artikl")
        .order_by("artikl__name")
    )
    if not items:
        return format_html("<p class=\"help\">Nema stavki.</p>")

    rows = format_html_join(
        "",
        "<tr><td>{}</td><td>{}</td><td style=\"text-align:right\">{}</td><td>{}</td></tr>",
        (
            (
                item.artikl.code or "—",
                item.artikl.name,
                f"{item.unit_price_gross:.2f}".replace(".", ","),
                "Da" if item.is_active else "Ne",
            )
            for item in items
        ),
    )
    return format_html(
        "<table class=\"adminlist\" style=\"width:100%;max-width:960px\">"
        "<thead><tr>"
        "<th>Šifra</th><th>Artikl</th><th style=\"text-align:right\">Cijena (bruto)</th><th>Aktivno</th>"
        "</tr></thead><tbody>{}</tbody></table>",
        rows,
    )


@admin.register(SalesPriceList)
class SalesPriceListAdmin(admin.ModelAdmin):
    class SalesPriceListAdminForm(forms.ModelForm):
        valid_from = forms.DateTimeField(
            required=True,
            input_formats=[
                "%d.%m.%Y",
                "%d.%m.%Y %H:%M",
                "%d.%m.%Y %H.%M",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S",
            ],
            widget=forms.DateTimeInput(format="%d.%m.%Y %H:%M", attrs={"class": "js-flatpickr-datetime"}),
        )
        valid_to = forms.DateTimeField(
            required=False,
            input_formats=[
                "%d.%m.%Y",
                "%d.%m.%Y %H:%M",
                "%d.%m.%Y %H.%M",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S",
            ],
            widget=forms.DateTimeInput(format="%d.%m.%Y %H:%M", attrs={"class": "js-flatpickr-datetime"}),
        )

        class Meta:
            model = SalesPriceList
            fields = "__all__"

    form = SalesPriceListAdminForm
    list_display = ("name", "is_active", "is_default", "valid_from", "valid_to", "warehouse", "pos")
    list_filter = ("is_active", "is_default", "warehouse", "pos")
    search_fields = ("name",)
    inlines = [SalesPriceItemInline]
    actions = [sync_sales_pricelist_to_remaris_action, transfer_sales_prices_to_pos_action]

    def get_fieldsets(self, request, obj=None):
        main = {
            "fields": (
                "name",
                "is_active",
                "is_default",
                "valid_from",
                "valid_to",
                "warehouse",
                "pos",
                "note",
            ),
        }
        if not obj:
            return ((None, main),)
        return (
            (None, main),
            (
                "Cijene",
                {
                    "fields": ("prices_table",),
                    "description": "Pregled stavki (uređivanje ispod u inline tablici).",
                },
            ),
            (
                "Remaris",
                {
                    "fields": (
                        "remaris_price_list_id",
                        "remaris_sync_transfer_pos",
                        "remaris_applied_at",
                        "remaris_reverted_at",
                    ),
                    "classes": ("collapse",),
                },
            ),
            (
                "Meta",
                {
                    "fields": ("created_at", "updated_at"),
                    "classes": ("collapse",),
                },
            ),
        )

    def get_readonly_fields(self, request, obj=None):
        readonly = ("created_at", "updated_at")
        if obj:
            readonly = (
                "prices_table",
                "remaris_applied_at",
                "remaris_reverted_at",
                "created_at",
                "updated_at",
            )
        return readonly

    @admin.display(description="Stavke cjenika")
    def prices_table(self, obj):
        return _sales_price_items_table(obj)


class SalesPriceRuleItemInline(admin.TabularInline):
    model = SalesPriceRuleItem
    extra = 0
    autocomplete_fields = ("artikl",)


@admin.register(SalesPriceRule)
class SalesPriceRuleAdmin(admin.ModelAdmin):
    class SalesPriceRuleAdminForm(forms.ModelForm):
        valid_from = forms.DateTimeField(
            required=True,
            input_formats=[
                "%d.%m.%Y",
                "%d.%m.%Y %H:%M",
                "%d.%m.%Y %H.%M",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S",
            ],
            widget=forms.DateTimeInput(format="%d.%m.%Y %H:%M", attrs={"class": "js-flatpickr-datetime"}),
        )
        valid_to = forms.DateTimeField(
            required=False,
            input_formats=[
                "%d.%m.%Y",
                "%d.%m.%Y %H:%M",
                "%d.%m.%Y %H.%M",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S",
            ],
            widget=forms.DateTimeInput(format="%d.%m.%Y %H:%M", attrs={"class": "js-flatpickr-datetime"}),
        )

        class Meta:
            model = SalesPriceRule
            fields = "__all__"

    form = SalesPriceRuleAdminForm
    list_display = ("name", "price_list", "rule_type", "adjust_type", "value", "valid_from", "valid_to", "is_active", "priority")
    list_filter = ("rule_type", "adjust_type", "is_active", "price_list")
    search_fields = ("name",)
    inlines = [SalesPriceRuleItemInline]
