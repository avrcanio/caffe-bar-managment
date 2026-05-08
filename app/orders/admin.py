from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urljoin
import ast
import re
import json

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from email.utils import formataddr, parseaddr
from django.db import IntegrityError, models, transaction
from django.db.models import Sum
from django.core.mail import EmailMessage
from django.utils import timezone
from django.utils.html import format_html
from django.conf import settings
from django.urls import reverse, path
import requests

from configuration.models import CompanyProfile, OrderEmailTemplate
from accounting.services import (
    compute_purchase_totals_from_items,
    post_supplier_return_charge_from_input,
    post_warehouse_input_to_journal,
)
from artikli.remaris_connector import RemarisConnector
from stock.models import (
    SupplierReturn,
    WarehouseId,
    WarehouseStock,
    WarehouseTransfer,
    WarehouseTransferItem,
)
from stock.services import get_stock_accounting_config
from stock.services import (
    post_stock_out_multi_warehouse,
    post_warehouse_input_to_stock,
    record_supplier_return_for_primka_stock_move,
)

from .models import (
    PurchaseOrder,
    PurchaseOrderItem,
    SupplierInvoice,
    SupplierPriceItem,
    SupplierPriceList,
    WarehouseInput,
    WarehouseInputItem,
)
from . import supplier_invoice_admin  # noqa: F401

from .pdf import build_order_pdf


def _safe_format(template, context):
    try:
        return template.format_map(context)
    except KeyError:
        return template


def _fmt_decimal(value, places="0.00"):
    if value is None:
        return "0,00"
    dec = Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return f"{dec:.2f}".replace(".", ",")


def _fmt_date(value):
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%-d.%-m.%Y.")


def _fmt_datetime(value):
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%-d.%-m.%Y. %H:%M:%S")


def _fmt_date_time_zero(value):
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%-d.%-m.%Y. 0:00:00")


def _post_json_text(connector, path, payload, referer_path):
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/html,application/xhtml+xml",
        "X-Requested-With": "XMLHttpRequest",
        "ajax-request": "AJAX-REQUEST",
        "Origin": connector.base_url,
        "Referer": urljoin(connector.base_url + "/", referer_path.lstrip("/")),
    }
    if connector.raw_cookie_header:
        headers["Cookie"] = connector.raw_cookie_header
    response = connector.session.post(
        urljoin(connector.base_url + "/", path.lstrip("/")),
        json=payload,
        headers=headers,
    )
    connector._save_cookies()
    return response


def _extract_remaris_id(html_text):
    match = re.search(r'data-u-dialog-save="[^"]*KeyId\\&quot;:([0-9]+)', html_text)
    if match:
        return int(match.group(1))
    match = re.search(r'id="Id"[^>]*value="([0-9]+)"', html_text)
    if match:
        return int(match.group(1))
    return None


def _next_duplicate_supplier_invoice_number(supplier_id: int, base_number: str) -> str:
    base = (base_number or "").strip()
    if not base:
        return "AUTO-1"
    ordinal = 1
    while True:
        candidate = f"{base} ({ordinal})"
        if not SupplierInvoice.objects.filter(
            supplier_id=supplier_id,
            invoice_number=candidate,
        ).exists():
            return candidate
        ordinal += 1


class PurchaseOrderItemInlineForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrderItem
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unit_of_measure"].required = False
        if self.instance and self.instance.pk:
            quantity = self.instance.quantity
            price = self.instance.price
            if quantity is not None and price is not None:
                line_total = Decimal(price) * Decimal(quantity)
                self.fields["price"].widget.attrs["data-line-total"] = (
                    f"Iznos stavke: {_fmt_decimal(line_total)} EUR"
                )

    def clean(self):
        cleaned_data = super().clean()
        unit_of_measure = cleaned_data.get("unit_of_measure")
        artikl = cleaned_data.get("artikl")
        if not unit_of_measure and artikl:
            detail = getattr(artikl, "detail", None)
            default_uom = getattr(detail, "unit_of_measure", None) if detail else None
            if default_uom:
                cleaned_data["unit_of_measure"] = default_uom
            else:
                self.add_error(
                    "unit_of_measure",
                    "Odaberite jedinicu mjere ili postavite zadanu na artiklu.",
                )
        return cleaned_data


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0
    autocomplete_fields = ("artikl", "unit_of_measure")
    form = PurchaseOrderItemInlineForm
    formfield_overrides = {
        models.DecimalField: {"localize": True},
    }

    class Media:
        css = {
            "all": ("orders/css/purchase_order_item_inline.css",),
        }
        js = ("orders/js/purchase_order_item_inline.js",)


class WarehouseInputItemInline(admin.TabularInline):
    model = WarehouseInputItem
    extra = 0
    autocomplete_fields = ("artikl", "unit_of_measure")
    exclude = ("product_id", "product_name", "unit_name", "buying_price")
    formfield_overrides = {
        models.DecimalField: {"localize": True},
    }
    class Media:
        css = {
            "all": ("orders/css/warehouse_input_item_inline.css",),
        }


def _warehouse_input_payload(warehouse_input):
    now = timezone.now()
    is_update = bool(warehouse_input.remaris_id)
    app_context = {
        "OrganizationId": 2,
        "LocationId": "5",
        "WarehouseId": None,
        "RegimeId": None,
        "PriceListId": None,
        "ContactId": None,
        "DiscountId": None,
        "SalesGroupId": None,
        "ProductTags": None,
        "FiscalPaymentTypes": None,
        "SelectedCustomerIds": None,
        "PosId": None,
        "ShowFilter": None,
        "ShowDateRange": None,
        "DateFrom": None,
        "DateTo": None,
        "OnDate": None,
        "Year": str(now.year),
        "ReportYear": None,
        "ReportMonth": None,
        "CustomerId": None,
        "WaiterId": None,
        "PdvIraReportType": None,
        "TableTotalType": 0,
        "IncludeInvoices": False,
        "IncludeDeliveryNotes": False,
        "IncludeArchivedTables": False,
        "IncludeOpenOrders": False,
        "IncludeHotelOrders": False,
        "GroupByDiscountValue": False,
        "Billed": False,
        "NonBilled": False,
        "ShowInitialCustomer": False,
        "IncludeCanceled": False,
        "IncludeCancels": False,
        "WithBuyerOnly": False,
        "WithDiscountOnly": False,
        "LoginLogoutInvoice": 0,
        "PDV2014Margin": False,
        "AllBaseGroups": True,
        "ProductBaseGroupIds": None,
        "AllWarehouseOperationDocumentTypes": True,
        "WarehouseOperationDocumentTypes": None,
        "ProductId": None,
        "OrderCancelReasonId": None,
        "PointOfIssueId": None,
        "PaymentMethodId": None,
        "SupplyerId": None,
        "HotelGuestOrders": False,
        "HotelReceptionOrders": False,
        "NoGrouping": False,
        "NoProduction": False,
        "TableNumber": None,
        "TextSearch": None,
        "ByPaymentFilter": 0,
        "NotPayedByDate": None,
        "Currency": None,
        "IncludePivot": False,
    }

    items = []
    for idx, item in enumerate(warehouse_input.items.select_related("artikl", "unit_of_measure").all(), start=1):
        item_id = None
        guid = None
        if is_update and item.guid and str(item.guid).isdigit():
            item_id = int(item.guid)
            guid = str(item.guid)
        elif not is_update:
            guid = str(idx)
        items.append(
            {
                "Id": item_id,
                "Quantity": float(item.quantity) if item.quantity is not None else None,
                "Price": float(item.price) if item.price is not None else None,
                "Total": float(item.total) if item.total is not None else None,
                "Rebate": None,
                "Margin": None,
                "SalesPrice": float(item.sales_price) if item.sales_price is not None else None,
                "BuyingPrice": float(item.buying_price) if item.buying_price is not None else float(item.price or 0),
                "CalculateSpillage": None,
                "GrossPrice": float(item.gross_price) if item.gross_price is not None else None,
                "VATPrepayment": float(item.vat_prepayment) if item.vat_prepayment is not None else None,
                "Ordinal": str(item.ordinal or ""),
                "ProductId": item.product_id or (item.artikl.rm_id if item.artikl else None),
                "ProductName": item.product_name or (item.artikl.name if item.artikl else ""),
                "WarehouseId": warehouse_input.warehouse.rm_id if warehouse_input.warehouse else None,
                "WarehouseName": warehouse_input.warehouse.name if warehouse_input.warehouse else None,
                "UnitName": item.unit_name or (item.unit_of_measure.name if item.unit_of_measure else ""),
                "ParentGuid": None,
                "Guid": guid,
                "BaseQuantity": float(item.base_quantity) if item.base_quantity is not None else 1,
                "TaxRate": float(item.tax_rate) if item.tax_rate is not None else None,
                "CalculateTax": True if (item.calculate_tax or (item.tax_rate or 0) > 0) else False,
                "PriceOnStockCard": float(item.price_on_stock_card) if item.price_on_stock_card is not None else None,
                "LastInputPrice": float(item.last_input_price) if item.last_input_price is not None else None,
            }
        )

    payload = {
        "TypeName": "WarehouseInputViewModel",
        "Id": str(warehouse_input.remaris_id) if warehouse_input.remaris_id else "",
        "DateModified": _fmt_datetime(warehouse_input.date_modified or now) if is_update else "",
        "DocumentType": str(
            warehouse_input.document_type_code
            or (warehouse_input.document_type.code if warehouse_input.document_type else "10")
        ),
        "IsInPdvSystem": "True" if warehouse_input.is_in_pdv_system else "False",
        "ExportDocumentTypeRequired": "False",
        "WarehouseId": str(warehouse_input.warehouse.rm_id) if warehouse_input.warehouse else "",
        "PartnerId": str(warehouse_input.supplier.rm_id) if warehouse_input.supplier else "",
        "PaymentMethodId": str(warehouse_input.payment_type.rm_id) if warehouse_input.payment_type and warehouse_input.payment_type.rm_id else "",
        "Date": _fmt_date(warehouse_input.date),
        "IsInternalInput": bool(warehouse_input.is_internal_input),
        "ExportDocumentTypeId": warehouse_input.export_document_type_id if warehouse_input.export_document_type_id is not None else None,
        "InvoiceCode": warehouse_input.invoice_code or "",
        "IsRInvoice": bool(warehouse_input.is_r_invoice),
        "DeliveryNote": warehouse_input.delivery_note or "",
        "IsNonmaterialInput": bool(warehouse_input.is_nonmaterial_input),
        "PurchaseOrder": str(warehouse_input.purchase_order_id) if warehouse_input.purchase_order_id else "",
        "Description": warehouse_input.description or None,
        "Total": _fmt_decimal(warehouse_input.total),
        "IsCanceled": bool(warehouse_input.is_canceled),
        "submitCommand": warehouse_input.submit_command or "_save_",
        "AppContext": app_context,
        "WareHouseItems": items,
    }

    return payload


def _validate_warehouse_input(warehouse_input):
    errors = []
    if not warehouse_input.supplier or not warehouse_input.supplier.rm_id:
        errors.append("Nedostaje dobavljac (Supplier.rm_id).")
    if not warehouse_input.payment_type or not warehouse_input.payment_type.rm_id:
        errors.append("Nedostaje tip placanja (PaymentType.rm_id).")
    if not warehouse_input.warehouse or not warehouse_input.warehouse.rm_id:
        errors.append("Nedostaje skladiste (WarehouseId.rm_id).")
    if not (warehouse_input.invoice_code or warehouse_input.delivery_note):
        errors.append("Nedostaje broj racuna ili broj otpremnice.")
    if not warehouse_input.date:
        errors.append("Nedostaje datum.")
    if not warehouse_input.items.exists():
        errors.append("Nedostaju stavke primke.")
    for item in warehouse_input.items.select_related("artikl").all():
        if not item.artikl or item.artikl.rm_id is None:
            errors.append(f"Stavka bez ProductId (artikl.rm_id). (ID: {item.id})")
        if item.price is None:
            errors.append(f"Stavka bez cijene. (ID: {item.id})")
    return errors


def _get_latest_supplier_pricelist(supplier):
    return (
        SupplierPriceList.objects.filter(supplier=supplier)
        .order_by("-valid_from", "-created_at", "-id")
        .first()
    )


@admin.register(WarehouseInput)
class WarehouseInputAdmin(admin.ModelAdmin):
    class WarehouseInputAdminForm(forms.ModelForm):
        date = forms.DateField(
            required=True,
            input_formats=[
                "%d.%m.%Y",
                "%Y-%m-%d",
            ],
            widget=forms.DateInput(
                format="%d.%m.%Y",
                attrs={"class": "js-flatpickr-date"},
            ),
        )
        date_modified = forms.DateTimeField(
            required=False,
            input_formats=[
                "%d.%m.%Y",
                "%d.%m.%Y %H:%M",
                "%d.%m.%Y %H.%M",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S",
            ],
            widget=forms.DateTimeInput(
                format="%d.%m.%Y %H:%M",
                attrs={"class": "js-flatpickr-datetime"},
            ),
        )

        class Meta:
            model = WarehouseInput
            fields = "__all__"

    form = WarehouseInputAdminForm
    list_display = (
        "id",
        "order",
        "supplier",
        "warehouse",
        "date",
        "document_type",
        "total",
        "is_canceled",
        "posted",
        "has_supplier_invoice",
    )
    list_filter = ("document_type", "is_canceled", "supplier", "warehouse", "supplier_invoices")
    search_fields = ("id", "invoice_code", "delivery_note", "purchase_order__id")
    autocomplete_fields = ("order", "purchase_order", "supplier", "payment_type", "warehouse", "document_type")
    inlines = [WarehouseInputItemInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        warehouse_input = form.instance
        warehouse_input.recalculate_total(persist=True)
    actions = [
        "send_warehouse_input_to_remaris",
        "post_warehouse_input_to_stock_action",
        "create_supplier_return_from_inputs",
        "create_supplier_invoice_from_inputs",
        "create_supplier_pricelist_from_input",
        "create_warehouse_transfer_from_inputs",
    ]

    @admin.display(boolean=True, description="proknjizeno", ordering="stock_move")
    def posted(self, obj):
        return bool(obj.stock_move_id)

    @admin.display(boolean=True, description="ulazni racun", ordering="supplier_invoices")
    def has_supplier_invoice(self, obj):
        return obj.supplier_invoices.exists()

    @admin.action(description="Kreiraj povrat dobavljacu", permissions=["change"])
    def create_supplier_return_from_inputs(self, request, queryset):
        input_ids = list(queryset.values_list("id", flat=True))
        if not input_ids:
            self.message_user(request, "Nema odabranih primki.", level=messages.WARNING)
            return None
        url = reverse("admin:orders_warehouseinput_supplier_return")
        return HttpResponseRedirect(f"{url}?ids={','.join(str(i) for i in input_ids)}")

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "supplier-return/",
                self.admin_site.admin_view(self.supplier_return_view),
                name="orders_warehouseinput_supplier_return",
            ),
        ]
        return custom + urls

    def supplier_return_view(self, request):
        ids_csv = (request.GET.get("ids") or request.POST.get("ids") or "").strip()
        input_ids: list[int] = []
        for token in ids_csv.split(","):
            token = token.strip()
            if token.isdigit():
                input_ids.append(int(token))

        if not input_ids:
            self.message_user(request, "Nema odabranih primki za povrat.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:orders_warehouseinput_changelist"))

        inputs = list(
            WarehouseInput.objects.filter(id__in=input_ids)
            .select_related("warehouse")
            .prefetch_related(
                "items__artikl",
                "supplier_invoices__document_type",
                "supplier_invoices__journal_entry",
                "supplier_invoices__ap_account",
                "supplier_invoices__cash_account",
                "supplier_invoices__deposit_account",
            )
            .order_by("id")
        )
        if not inputs:
            self.message_user(request, "Primke nisu pronađene.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:orders_warehouseinput_changelist"))

        form = CreateSupplierReturnSelectionForm(
            data=request.POST or None,
            inputs=inputs,
        )
        if request.method == "POST" and form.is_valid():
            self._execute_supplier_return_from_inputs(
                request=request,
                inputs=inputs,
                line_quantities_by_input_id=form.line_quantities_by_input_id,
                warehouse_quantities_by_input_id=form.warehouse_quantities_by_input_id,
            )
            return HttpResponseRedirect(reverse("admin:orders_warehouseinput_changelist"))

        rows_by_input: dict[int, list[dict]] = {}

        for row in form.rows:
            wi = row["warehouse_input"]
            rows_by_input.setdefault(wi.id, []).append(
                {
                    "item": row["item"],
                    "max_qty": row["max_qty"],
                    "stock_by_wh": row["stock_by_wh"],
                    "stock_total": row["stock_total"],
                    "warehouse_fields": [
                        {
                            "wh_name": w["wh_name"],
                            "available": w["available"],
                            "field": form[w["field_name"]],
                        }
                        for w in row["warehouse_fields"]
                    ],
                }
            )

        input_rows = [{"wi": wi, "rows": rows_by_input.get(wi.id, [])} for wi in inputs]

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Povrat dobavljaču - odabir količina",
            "form": form,
            "inputs": inputs,
            "input_rows": input_rows,
            "ids": ids_csv,
        }
        return TemplateResponse(
            request,
            "admin/orders/warehouseinput/supplier_return_form.html",
            context,
        )

    @staticmethod
    def _existing_supplier_return_for_primka(warehouse_input: WarehouseInput):
        """Posted supplier return row in stock (canonical); excludes cancelled."""
        sr = (
            SupplierReturn.objects.filter(source_warehouse_input_id=warehouse_input.pk)
            .exclude(status=SupplierReturn.Status.CANCELLED)
            .order_by("-id")
            .first()
        )
        if sr:
            return sr
        if warehouse_input.supplier_return_stock_move_id:
            return (
                SupplierReturn.objects.filter(
                    stock_move_id=warehouse_input.supplier_return_stock_move_id
                )
                .exclude(status=SupplierReturn.Status.CANCELLED)
                .first()
            )
        return None

    def _execute_supplier_return_from_inputs(
        self,
        *,
        request,
        inputs,
        line_quantities_by_input_id,
        warehouse_quantities_by_input_id,
    ):
        created_stock = 0
        created_finance = 0
        skipped = 0
        failed = 0

        for warehouse_input in inputs:
            existing_sr = self._existing_supplier_return_for_primka(warehouse_input)
            if warehouse_input.supplier_return_stock_move_id or existing_sr:
                skipped += 1
                if existing_sr:
                    self.message_user(
                        request,
                        f"Primka {warehouse_input.id}: povrat je već napravljen "
                        f"(Stock → Povrati dobavljaču, zapis #{existing_sr.id}).",
                        level=messages.WARNING,
                    )
                else:
                    self.message_user(
                        request,
                        f"Primka {warehouse_input.id}: već je vezano skladišno kretanje povrata "
                        f"(StockMove #{warehouse_input.supplier_return_stock_move_id}); "
                        f"provjeri Stock → Povrati dobavljaču ili administratora.",
                        level=messages.WARNING,
                    )
                continue
            if not warehouse_input.stock_move_id:
                skipped += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id}: nije proknjižena u skladište.",
                    level=messages.WARNING,
                )
                continue
            if not warehouse_input.warehouse_id:
                skipped += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id}: nema skladište.",
                    level=messages.WARNING,
                )
                continue

            input_quantities = line_quantities_by_input_id.get(warehouse_input.id) or {}
            input_wh_quantities = warehouse_quantities_by_input_id.get(warehouse_input.id) or {}
            item_map = {it.id: it for it in warehouse_input.items.all()}
            wh_ids = {
                wh_id
                for per_item in input_wh_quantities.values()
                for wh_id, qty in per_item.items()
                if qty and qty > 0
            }
            warehouses = {w.rm_id: w for w in WarehouseId.objects.filter(rm_id__in=wh_ids)}
            items_payload = []
            for item_id, per_wh in input_wh_quantities.items():
                it = item_map.get(item_id)
                if not it or not it.artikl_id:
                    continue
                for wh_id, qty in per_wh.items():
                    if not qty or qty <= 0:
                        continue
                    wh_obj = warehouses.get(wh_id)
                    if not wh_obj:
                        continue
                    items_payload.append(
                        {"warehouse": wh_obj, "artikl": it.artikl, "quantity": qty}
                    )
            if not items_payload:
                skipped += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id}: nema stavki za povrat.",
                    level=messages.WARNING,
                )
                continue

            posted_invoices = list(
                warehouse_input.supplier_invoices.filter(journal_entry__isnull=False).order_by("id")
            )
            if len(posted_invoices) > 1:
                failed += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id}: vezana je na više proknjiženih ulaznih računa.",
                    level=messages.ERROR,
                )
                continue

            try:
                with transaction.atomic():
                    move = post_stock_out_multi_warehouse(
                        items=items_payload,
                        move_date=timezone.now(),
                        reference=f"Povrat dobavljaču primka #{warehouse_input.id}",
                        note=f"Povrat dobavljaču za primku {warehouse_input.id}",
                    )
                    warehouse_input.supplier_return_stock_move = move
                    created_stock += 1

                    try:
                        record_supplier_return_for_primka_stock_move(
                            warehouse_input=warehouse_input,
                            stock_move=move,
                            created_by=request.user,
                        )
                    except Exception as exc:
                        self.message_user(
                            request,
                            f"Primka {warehouse_input.id}: skladišni povrat OK, "
                            f"ali zapis u Povrat dobavljaču nije kreiran ({exc}).",
                            level=messages.WARNING,
                        )

                    update_fields = ["supplier_return_stock_move"]
                    if posted_invoices:
                        entry = post_supplier_return_charge_from_input(
                            supplier_invoice=posted_invoices[0],
                            warehouse_input=warehouse_input,
                            line_quantities_by_item_id=input_quantities,
                            description=f"Financijsko terecenje povrata primke #{warehouse_input.id}",
                            posted_by=request.user,
                        )
                        warehouse_input.supplier_return_journal_entry = entry
                        update_fields.append("supplier_return_journal_entry")
                        created_finance += 1

                    warehouse_input.save(update_fields=update_fields)
            except Exception as exc:
                failed += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id}: greška kod povrata ({exc}).",
                    level=messages.ERROR,
                )

        if created_stock:
            self.message_user(
                request,
                f"Kreirano povrata: {created_stock}. Financijskih terećenja: {created_finance}.",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(request, f"Preskočeno: {skipped}.", level=messages.WARNING)
        if failed:
            self.message_user(request, f"Greške: {failed}.", level=messages.ERROR)

    @admin.action(description="Kreiraj međuskladišnicu iz primki", permissions=["change"])
    def create_warehouse_transfer_from_inputs(self, request, queryset):
        created = 0
        skipped = 0
        errors = 0

        for warehouse_input in queryset.select_related("warehouse").prefetch_related("items__artikl", "items__unit_of_measure"):
            if not warehouse_input.warehouse_id:
                skipped += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id} nema skladište.",
                    level=messages.WARNING,
                )
                continue
            warehouse = (
                WarehouseId.objects.filter(rm_id=warehouse_input.warehouse_id).first()
                or WarehouseId.objects.filter(id=warehouse_input.warehouse_id).first()
            )
            if not warehouse:
                skipped += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id} ima nepostojeće skladište (id/rm_id={warehouse_input.warehouse_id}).",
                    level=messages.WARNING,
                )
                continue

            items = list(warehouse_input.items.all())
            if not items:
                skipped += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id} nema stavki.",
                    level=messages.WARNING,
                )
                continue

            try:
                with transaction.atomic():
                    transfer = WarehouseTransfer.objects.create(
                        from_warehouse_id=warehouse.rm_id,
                        to_warehouse_id=None,
                        date=warehouse_input.date,
                        note=f"Primka {warehouse_input.id}",
                        created_by=request.user,
                    )
                    WarehouseTransferItem.objects.bulk_create(
                        [
                            WarehouseTransferItem(
                                transfer=transfer,
                                artikl=item.artikl,
                                quantity=item.quantity,
                                unit=item.unit_of_measure,
                            )
                            for item in items
                        ]
                    )
                created += 1
            except Exception as exc:
                errors += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id} greška: {exc}",
                    level=messages.ERROR,
                )

        if created:
            self.message_user(request, f"Kreirano međuskladišnica: {created}", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Preskočeno: {skipped}", level=messages.WARNING)
        if errors:
            self.message_user(request, f"Greške: {errors}", level=messages.ERROR)

    @admin.action(description="Send to Remaris", permissions=["change"])
    def send_warehouse_input_to_remaris(self, request, queryset):
        connector = RemarisConnector()
        connector.login()

        sent = 0
        skipped = 0
        updated_ids = 0
        failed = 0

        for warehouse_input in queryset.select_related("supplier", "payment_type", "warehouse"):
            errors = _validate_warehouse_input(warehouse_input)
            if errors:
                skipped += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id} preskocena: " + "; ".join(errors),
                    level=messages.WARNING,
                )
                continue

            payload = _warehouse_input_payload(warehouse_input)
            response = _post_json_text(
                connector,
                "WarehouseOperation/Edit?isc_dataFormat=json",
                payload,
                referer_path="/WarehouseOperation",
            )
            status = response.status_code
            html = response.text or ""
            if status >= 400:
                failed += 1
                warehouse_input.raw_payload = {
                    "payload": payload,
                    "error_status": status,
                    "error_response": html,
                    "error_headers": dict(response.headers),
                }
                warehouse_input.date_modified = timezone.now()
                warehouse_input.save(update_fields=["raw_payload", "date_modified"])
                continue

            parsed = None
            try:
                parsed = response.json()
            except json.JSONDecodeError:
                parsed = None

            remaris_id = _extract_remaris_id(html)
            if not remaris_id and parsed:
                remaris_id = (
                    parsed.get("KeyId")
                    or parsed.get("keyId")
                    or parsed.get("id")
                    or parsed.get("Id")
                )
            warehouse_input.raw_payload = payload
            warehouse_input.date_modified = timezone.now()
            if remaris_id:
                warehouse_input.remaris_id = remaris_id
                warehouse_input.save(update_fields=["raw_payload", "date_modified", "remaris_id"])
                updated_ids += 1

            else:
                warehouse_input.save(update_fields=["raw_payload", "date_modified"])
            sent += 1

        if sent:
            self.message_user(
                request,
                f"Poslano primki: {sent}. Preskoceno: {skipped}. Id update: {updated_ids}. Fail: {failed}.",
                level=messages.SUCCESS,
            )
        elif skipped:
            self.message_user(
                request,
                "Sve primke su preskocene jer nemaju stavke.",
                level=messages.WARNING,
            )
        elif failed:
            self.message_user(
                request,
                f"Slanje nije uspjelo. Fail: {failed}.",
                level=messages.ERROR,
            )

    @admin.action(description="Proknjizi primku", permissions=["change"])
    def post_warehouse_input_to_stock_action(self, request, queryset):
        posted = 0
        skipped = 0
        failed = 0

        already_posted = queryset.filter(stock_move__isnull=False).count()
        queryset = queryset.filter(stock_move__isnull=True)

        for warehouse_input in queryset.select_related("warehouse", "document_type", "supplier"):
            try:
                with transaction.atomic():
                    post_warehouse_input_to_stock(warehouse_input=warehouse_input)
                    post_warehouse_input_to_journal(
                        warehouse_input=warehouse_input,
                        user=request.user,
                    )
                    # If supplier has no pricelist yet, create one from this input.
                    if warehouse_input.supplier and not SupplierPriceList.objects.filter(supplier=warehouse_input.supplier).exists():
                        items_with_price = [
                            item
                            for item in warehouse_input.items.select_related("artikl", "unit_of_measure")
                            if item.price is not None
                        ]
                        if items_with_price:
                            new_list = SupplierPriceList.objects.create(
                                supplier=warehouse_input.supplier,
                                valid_from=warehouse_input.date,
                                valid_to=None,
                                is_active=True,
                            )
                            SupplierPriceItem.objects.bulk_create(
                                [
                                    SupplierPriceItem(
                                        price_list=new_list,
                                        artikl=wi_item.artikl,
                                        unit_of_measure=wi_item.unit_of_measure,
                                        price=wi_item.price,
                                    )
                                    for wi_item in items_with_price
                                ]
                            )
                posted += 1
            except ValidationError as exc:
                skipped += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id} preskocena: {exc}",
                    level=messages.WARNING,
                )
            except Exception as exc:
                failed += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id} greska: {exc}",
                    level=messages.ERROR,
                )

        if posted:
            self.message_user(request, f"Proknjizeno primki: {posted}", level=messages.SUCCESS)
        if already_posted:
            self.message_user(
                request,
                f"Preskoceno (vec proknjizeno): {already_posted}",
                level=messages.WARNING,
            )
        if skipped:
            self.message_user(request, f"Preskoceno primki: {skipped}", level=messages.WARNING)
        if failed:
            self.message_user(request, f"Greske: {failed}", level=messages.ERROR)

    @admin.action(description="Kreiraj novi cjenik iz primke (samo razlike)", permissions=["change"])
    def create_supplier_pricelist_from_input(self, request, queryset):
        created_lists = 0
        created_items = 0
        skipped = 0

        for warehouse_input in queryset.select_related("supplier"):
            supplier = warehouse_input.supplier
            if not supplier:
                skipped += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id} nema dobavljaca.",
                    level=messages.WARNING,
                )
                continue
            if not warehouse_input.date:
                skipped += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id} nema datum.",
                    level=messages.WARNING,
                )
                continue

            latest_list = _get_latest_supplier_pricelist(supplier)
            latest_items = {}
            if latest_list:
                latest_items = {
                    item.artikl_id: item
                    for item in latest_list.items.all()
                }

            items_to_create = []
            for item in warehouse_input.items.select_related("artikl", "unit_of_measure"):
                if item.price is None:
                    continue
                prev_item = latest_items.get(item.artikl_id)
                if prev_item is None or prev_item.price != item.price:
                    items_to_create.append(item)

            if not items_to_create:
                skipped += 1
                self.message_user(
                    request,
                    f"Primka {warehouse_input.id}: nema razlika u cijenama.",
                    level=messages.INFO,
                )
                continue

            with transaction.atomic():
                new_list = SupplierPriceList.objects.create(
                    supplier=supplier,
                    valid_from=warehouse_input.date,
                    valid_to=None,
                    is_active=True,
                )
                SupplierPriceItem.objects.bulk_create(
                    [
                        SupplierPriceItem(
                            price_list=new_list,
                            artikl=wi_item.artikl,
                            unit_of_measure=wi_item.unit_of_measure,
                            price=wi_item.price,
                        )
                        for wi_item in items_to_create
                    ]
                )
            created_lists += 1
            created_items += len(items_to_create)
            self.message_user(
                request,
                f"Primka {warehouse_input.id}: kreiran cjenik {new_list.id} sa {len(items_to_create)} stavki.",
                level=messages.SUCCESS,
            )

        if created_lists:
            self.message_user(
                request,
                f"Kreirano cjenika: {created_lists}, stavki: {created_items}. Preskoceno: {skipped}.",
                level=messages.SUCCESS,
            )
        elif skipped:
            self.message_user(
                request,
                "Nista nije kreirano. Sve primke su preskocene.",
                level=messages.WARNING,
            )

    @admin.action(description="Kreiraj ulazni racun iz primki", permissions=["change"])
    def create_supplier_invoice_from_inputs(self, request, queryset):
        inputs = queryset.select_related("supplier", "document_type").prefetch_related(
            "items__artikl__tax_group",
            "items__artikl__deposit",
        )
        if not inputs:
            self.message_user(request, "Nema odabranih primki.", level=messages.WARNING)
            return

        already_linked = queryset.filter(supplier_invoices__isnull=False).distinct()
        if already_linked.exists():
            pairs = list(
                already_linked.values_list("id", "supplier_invoices__invoice_number")
                .distinct()[:50]
            )
            self.message_user(
                request,
                f"Primke su vec vezane na racun: {pairs} (prikazano prvih 50).",
                level=messages.ERROR,
            )
            return

        suppliers = {inp.supplier_id for inp in inputs if inp.supplier_id}
        if len(suppliers) != 1:
            self.message_user(
                request,
                "Primke moraju imati istog dobavljaca.",
                level=messages.ERROR,
            )
            return

        invoice_codes = {inp.invoice_code for inp in inputs if inp.invoice_code}
        if len(invoice_codes) > 1:
            self.message_user(
                request,
                "Primke imaju razlicite brojeve racuna. Odaberi primke istog racuna.",
                level=messages.ERROR,
            )
            return

        supplier = inputs[0].supplier
        invoice_number = invoice_codes.pop() if invoice_codes else f"AUTO-{inputs[0].id}"
        if SupplierInvoice.objects.filter(
            supplier=supplier,
            invoice_number=invoice_number,
        ).exists():
            invoice_number = _next_duplicate_supplier_invoice_number(
                supplier.id,
                invoice_number,
            )
        invoice_date = max(inp.date for inp in inputs if inp.date)
        document_types = {inp.document_type_id for inp in inputs if inp.document_type_id}
        document_type = None
        if len(document_types) == 1:
            document_type = inputs[0].document_type
        force_cash = any(inp.payment_type_id == 3 for inp in inputs)
        document_type_id = 3 if force_cash else (document_type.id if document_type else None)
        cash_account_id = 379 if force_cash else None

        items = []
        for inp in inputs:
            items.extend(list(inp.items.all()))
        try:
            totals = compute_purchase_totals_from_items(items, deposit_total=None)
        except ValidationError as e:
            # Avoid 500 in admin: show actionable message and stop.
            self.message_user(
                request,
                f"Ne mogu izračunati iznose za ulazni račun: {e}. "
                "Provjeri da sve stavke imaju total i PDV (tax_group ili tax_rate).",
                level=messages.ERROR,
            )
            return

        cfg = None
        try:
            cfg = get_stock_accounting_config()
        except Exception:
            cfg = None

        try:
            invoice = SupplierInvoice.objects.create(
                supplier=supplier,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                deposit_total=totals.deposit_total,
                total_net=totals.net_total,
                total_vat=totals.vat_total,
                total_gross=totals.gross_total,
                document_type_id=document_type_id,
                cash_account_id=cash_account_id,
                paid_cash=force_cash,
            )
        except IntegrityError as exc:
            self.message_user(
                request,
                f"Ne mogu kreirati ulazni račun zbog duplikata broja ({invoice_number}): {exc}",
                level=messages.ERROR,
            )
            return
        if cfg:
            update_fields = []
            if not invoice.cash_account_id and cfg.default_cash_account_id:
                invoice.cash_account = cfg.default_cash_account
                update_fields.append("cash_account")
            if invoice.deposit_total > 0 and not invoice.deposit_account_id:
                if cfg.default_deposit_account_id:
                    invoice.deposit_account = cfg.default_deposit_account
                else:
                    invoice.deposit_account_id = 1318
                update_fields.append("deposit_account")
            if update_fields:
                invoice.save(update_fields=update_fields)
        invoice.inputs.add(*inputs)

        self.message_user(
            request,
            f"Ulazni racun kreiran (ID: {invoice.id}).",
            level=messages.SUCCESS,
        )
        url = reverse("admin:orders_supplierinvoice_change", args=[invoice.id])
        messages.success(
            request,
            format_html(
                'Kreiran ulazni racun: <a href="{}" target="_blank">#{}</a>',
                url,
                invoice.invoice_number,
            ),
        )


@admin.action(description="Send order email", permissions=["change"])
def send_order_email(modeladmin, request, queryset):
    template = (
        OrderEmailTemplate.objects.filter(active=True).order_by("-id").first()
    )
    company = CompanyProfile.objects.order_by("-id").first()

    sent = 0
    skipped = 0

    orders = queryset.select_related("supplier").prefetch_related("items__artikl", "items__unit_of_measure")
    for order in orders:
        recipient = order.supplier.orders_email
        if not recipient:
            skipped += 1
            continue

        token = order.ensure_confirmation_token()
        confirmation_url = request.build_absolute_uri(
            reverse("orders:purchase-order-confirm", args=[token])
        )
        context = {
            "order_id": order.id,
            "supplier_name": order.supplier.name,
            "confirmation_url": confirmation_url,
            "confirmation_link": confirmation_url,
        }
        subject_template = template.subject_template if template else "Narudzba #{order_id}"
        body_template = template.body_template if template else "U prilogu se nalazi narudzba {order_id}."
        subject = _safe_format(subject_template, context)
        body = _safe_format(body_template, context)
        if "{confirmation_url}" not in body_template and "{confirmation_link}" not in body_template:
            body = f"{body}\n\nMolimo potvrdite primitak narudžbe klikom na sljedeći link: {confirmation_url}"

        pdf_bytes = build_order_pdf(order, company)
        from_email = None
        if settings.DEFAULT_FROM_EMAIL:
            name, addr = parseaddr(settings.DEFAULT_FROM_EMAIL)
            if addr:
                if name:
                    from_email = formataddr((name, addr))
                else:
                    from_email = formataddr(("Mozart Caffe Narudzbe", addr))
            else:
                from_email = settings.DEFAULT_FROM_EMAIL
        message = EmailMessage(
            subject=subject,
            body=body,
            to=[recipient],
            from_email=from_email,
        )
        message.attach(f"narudzba_{order.id}.pdf", pdf_bytes, "application/pdf")
        message.send()
        if order.status != PurchaseOrder.STATUS_CONFIRMED:
            order.status = PurchaseOrder.STATUS_SENT
            order.save(update_fields=["status"])
        sent += 1

    if sent:
        modeladmin.message_user(
            request,
            f"Poslano {sent} narudžbi. Preskočeno {skipped} (nema email).",
            level=messages.SUCCESS,
        )
    elif skipped:
        modeladmin.message_user(
            request,
            "Sve narudžbe su preskočene jer nema email adrese.",
            level=messages.WARNING,
        )


@admin.action(description="Kreiraj primku iz narudžbe", permissions=["change"])
def create_warehouse_input(modeladmin, request, queryset):
    created = 0
    skipped = 0

    orders = queryset.prefetch_related(
        "items__artikl__tax_group",
        "items__unit_of_measure",
    )

    with transaction.atomic():
        for order in orders:
            # If a primka was already created for this order, this bulk action
            # must not create another one. Use the split-primke flow instead.
            if order.primka_created or order.warehouse_inputs.exists():
                skipped += 1
                existing_ids = list(order.warehouse_inputs.values_list("id", flat=True)[:5])
                suffix = f" (postojeće primke: {existing_ids})" if existing_ids else ""
                modeladmin.message_user(
                    request,
                    f"Narudžba {order.id} je preskočena: primka je već kreirana.{suffix}",
                    level=messages.WARNING,
                )
                continue
            if not order.items.exists():
                skipped += 1
                continue

            warehouse_input = WarehouseInput.objects.create(
                order=order,
                supplier=order.supplier,
                payment_type=order.payment_type,
                date=order.ordered_at.date(),
                total=order.total_net,
                purchase_order=order,
                document_type_id=1,
                warehouse_id=2,
            )

            items = []
            for idx, item in enumerate(order.items.all(), start=1):
                price = item.price or Decimal("0")
                line_total = price * Decimal(item.quantity)
                tax_rate = (
                    item.artikl.tax_group.rate
                    if item.artikl and item.artikl.tax_group
                    else Decimal("0")
                )
                gross = line_total * (Decimal("1") + Decimal(tax_rate))

                items.append(
                    WarehouseInputItem(
                        warehouse_input=warehouse_input,
                        artikl=item.artikl,
                        product_id=item.artikl.rm_id,
                        product_name=item.artikl.name,
                        unit_of_measure=item.unit_of_measure,
                        unit_name=item.unit_of_measure.name if item.unit_of_measure else "",
                        quantity=item.quantity,
                        price=price,
                        total=line_total,
                        buying_price=price,
                        gross_price=gross,
                        tax_rate=tax_rate,
                        calculate_tax=True,
                        ordinal=idx,
                    )
                )

            for wi_item in items:
                wi_item.id = None
            WarehouseInputItem.objects.bulk_create(items)
            warehouse_input.recalculate_total(persist=True)
            if not order.primka_created:
                order.primka_created = True
                order.status = PurchaseOrder.STATUS_RECEIVED_ALL
                order.save(update_fields=["primka_created", "status"])
            created += 1

    if created:
        modeladmin.message_user(
            request,
            f"Kreirano primki: {created}. Preskočeno: {skipped}.",
            level=messages.SUCCESS,
        )
    elif skipped:
        modeladmin.message_user(
            request,
            "Sve narudžbe su preskočene jer nemaju stavke.",
            level=messages.WARNING,
        )


@admin.action(description="Copy purchase order", permissions=["add"])
def copy_purchase_order(modeladmin, request, queryset):
    created = 0
    skipped = 0

    orders = queryset.prefetch_related("items__artikl", "items__unit_of_measure")

    with transaction.atomic():
        for order in orders:
            if not order.items.exists():
                skipped += 1
                continue

            new_order = PurchaseOrder.objects.create(
                supplier=order.supplier,
                ordered_at=timezone.now(),
                status=PurchaseOrder.STATUS_CREATED,
                payment_type=order.payment_type,
                created_by=request.user,
                primka_created=False,
                confirmation_token=None,
                confirmation_sent_at=None,
                confirmed_at=None,
            )

            items = []
            for item in order.items.all():
                items.append(
                    PurchaseOrderItem(
                        order=new_order,
                        artikl=item.artikl,
                        quantity=item.quantity,
                        unit_of_measure=item.unit_of_measure,
                        price=item.price,
                    )
                )
            PurchaseOrderItem.objects.bulk_create(items)
            new_order.recalculate_totals()
            created += 1

    if created:
        modeladmin.message_user(
            request,
            f"Kreirano kopija narudžbi: {created}. Preskočeno: {skipped}.",
            level=messages.SUCCESS,
        )
    elif skipped:
        modeladmin.message_user(
            request,
            "Sve narudžbe su preskočene jer nemaju stavke.",
            level=messages.WARNING,
        )


def _po_received_by_artikl(order: PurchaseOrder) -> dict[int, Decimal]:
    rows = (
        WarehouseInputItem.objects.filter(warehouse_input__purchase_order_id=order.id)
        .values("artikl_id")
        .annotate(q=Sum("quantity"))
    )
    return {r["artikl_id"]: (r["q"] or Decimal("0")) for r in rows if r["artikl_id"]}


def _po_item_remaining_map(
    items: list[PurchaseOrderItem], received_by_artikl: dict[int, Decimal]
) -> dict[int, dict[str, Decimal]]:
    """
    Greedy allocation of already-received qty per artikl across PO lines.
    This avoids over/under-counting when the same artikl appears multiple times.
    """
    received_left = {k: Decimal(v) for k, v in received_by_artikl.items()}
    out: dict[int, dict[str, Decimal]] = {}
    for it in items:
        ordered = it.quantity or Decimal("0")
        a_id = it.artikl_id
        left = received_left.get(a_id, Decimal("0"))
        received_line = min(ordered, left) if ordered > 0 and left > 0 else Decimal("0")
        remaining = ordered - received_line
        if a_id:
            received_left[a_id] = max(left - received_line, Decimal("0"))
        out[it.id] = {
            "ordered": ordered,
            "received": received_line,
            "remaining": max(remaining, Decimal("0")),
        }
    return out


class CreateWarehouseInputFromPoSelectionForm(forms.Form):
    date = forms.DateField(required=True, initial=timezone.localdate)
    invoice_code = forms.CharField(required=False, label="Broj računa")
    delivery_note = forms.CharField(required=False, label="Broj otpremnice")

    def __init__(self, *args, order: PurchaseOrder, items: list[PurchaseOrderItem], **kwargs):
        super().__init__(*args, **kwargs)
        self.order = order
        self.items = items
        # item_id -> new ordered quantity (when user receives more than ordered)
        self.bump_order_qty_by_item_id: dict[int, Decimal] = {}

        received_by_artikl = _po_received_by_artikl(order)
        self.qty_info_by_item_id = _po_item_remaining_map(items, received_by_artikl)

        for it in items:
            info = self.qty_info_by_item_id[it.id]
            self.fields[f"sel_{it.id}"] = forms.BooleanField(required=False)
            self.fields[f"qty_{it.id}"] = forms.DecimalField(
                required=False,
                min_value=Decimal("0"),
                decimal_places=4,
                max_digits=12,
                initial=info["remaining"],
                localize=True,
            )

    def clean(self):
        cleaned = super().clean()
        any_selected = False
        self.bump_order_qty_by_item_id = {}

        for it in self.items:
            sel = bool(cleaned.get(f"sel_{it.id}"))
            qty = cleaned.get(f"qty_{it.id}") or Decimal("0")
            info = self.qty_info_by_item_id[it.id]
            max_qty = info["remaining"]

            if not sel:
                continue
            any_selected = True
            if qty <= 0:
                self.add_error(None, f"Stavka '{it.artikl}': odabrana je, ali količina je 0.")
                continue
            if qty > max_qty:
                # If user enters more than remaining, bump the PO line's ordered
                # quantity so the received qty becomes valid.
                received = info.get("received") or Decimal("0")
                new_ordered = (received + qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                self.bump_order_qty_by_item_id[it.id] = new_ordered

        if any_selected:
            inv = (cleaned.get("invoice_code") or "").strip()
            dn = (cleaned.get("delivery_note") or "").strip()
            if not inv and not dn:
                self.add_error(None, "Unesi broj računa ili broj otpremnice (bar jedno).")
        else:
            self.add_error(None, "Odaberi barem jednu stavku za primku.")

        return cleaned

    def create_input(self) -> WarehouseInput | None:
        try:
            cfg = get_stock_accounting_config()
        except Exception:
            cfg = None
        default_wh = getattr(cfg, "default_purchase_warehouse", None) if cfg else None
        fallback_wh = WarehouseId.objects.order_by("id").first()
        warehouse_id = getattr(default_wh, "id", None) or (fallback_wh.id if fallback_wh else None)

        lines: list[WarehouseInputItem] = []
        ordinal = 0

        # Apply any "over-received" quantities by increasing PO item quantities.
        # This keeps business rules consistent: you cannot receive more than ordered
        # unless the order line is updated to match.
        if self.bump_order_qty_by_item_id:
            changed = False
            for it in self.items:
                new_qty = self.bump_order_qty_by_item_id.get(it.id)
                if new_qty is None:
                    continue
                if it.quantity is None or Decimal(it.quantity) != new_qty:
                    PurchaseOrderItem.objects.filter(pk=it.id).update(quantity=new_qty)
                    it.quantity = new_qty
                    changed = True
            if changed:
                self.order.recalculate_totals()

        for it in self.items:
            if not self.cleaned_data.get(f"sel_{it.id}"):
                continue
            qty = self.cleaned_data.get(f"qty_{it.id}") or Decimal("0")
            if qty <= 0:
                continue
            ordinal += 1
            price = it.price or Decimal("0")
            line_total = (price * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            tax_rate = (
                it.artikl.tax_group.rate
                if it.artikl and getattr(it.artikl, "tax_group", None)
                else Decimal("0")
            )
            gross = (line_total * (Decimal("1") + Decimal(tax_rate))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            lines.append(
                WarehouseInputItem(
                    artikl=it.artikl,
                    product_id=it.artikl.rm_id if it.artikl else None,
                    product_name=it.artikl.name if it.artikl else "",
                    unit_of_measure=it.unit_of_measure,
                    unit_name=it.unit_of_measure.name if it.unit_of_measure else "",
                    quantity=qty,
                    price=price,
                    total=line_total,
                    buying_price=price,
                    gross_price=gross,
                    tax_rate=tax_rate,
                    calculate_tax=True,
                    ordinal=ordinal,
                )
            )

        if not lines:
            return None

        wi = WarehouseInput.objects.create(
            order=self.order,
            supplier=self.order.supplier,
            payment_type=self.order.payment_type,
            date=self.cleaned_data["date"],
            total=Decimal("0.00"),
            purchase_order=self.order,
            document_type_id=1,
            warehouse_id=warehouse_id,
            invoice_code=(self.cleaned_data.get("invoice_code") or "").strip(),
            delivery_note=(self.cleaned_data.get("delivery_note") or "").strip(),
        )
        for li in lines:
            li.warehouse_input = wi
        WarehouseInputItem.objects.bulk_create(lines)
        wi.recalculate_total(persist=True)
        return wi


class CreateSupplierReturnSelectionForm(forms.Form):
    def __init__(self, *args, inputs: list[WarehouseInput], **kwargs):
        super().__init__(*args, **kwargs)
        self.inputs = inputs
        self.rows: list[dict] = []
        self.line_quantities_by_input_id: dict[int, dict[int, Decimal]] = {}
        self.warehouse_quantities_by_input_id: dict[int, dict[int, dict[int, Decimal]]] = {}

        artikl_rm_ids = {
            it.artikl.rm_id
            for wi in inputs
            for it in wi.items.select_related("artikl").all()
            if it.artikl_id and getattr(it.artikl, "rm_id", None) is not None
        }
        stock_rows = (
            WarehouseStock.objects.filter(product_id__in=artikl_rm_ids)
            .values("product_id", "warehouse_id_id", "warehouse_id__name", "internal_quantity")
            .order_by("product_id", "warehouse_id__name", "warehouse_id_id")
        )
        stock_by_rm: dict[int, list[dict]] = {}
        stock_total_by_rm: dict[int, Decimal] = {}
        for sr in stock_rows:
            product_id = sr["product_id"]
            wh_id = sr["warehouse_id_id"]
            if product_id is None or wh_id is None:
                continue
            wh_name = sr["warehouse_id__name"] or f"Skladište {wh_id}"
            qty = sr["internal_quantity"] or Decimal("0.0000")
            stock_by_rm.setdefault(product_id, []).append(
                {"wh_id": wh_id, "wh_name": wh_name, "available": qty}
            )
            stock_total_by_rm[product_id] = stock_total_by_rm.get(product_id, Decimal("0.0000")) + qty

        for wi in inputs:
            wi_items = list(wi.items.select_related("artikl", "unit_of_measure").order_by("id"))
            for it in wi_items:
                if not it.artikl_id:
                    continue
                max_qty = Decimal(str(it.quantity or Decimal("0.0000")))
                artikl_rm_id = getattr(it.artikl, "rm_id", None)
                wh_defs = stock_by_rm.get(artikl_rm_id, [])
                warehouse_fields: list[dict] = []
                for wh in wh_defs:
                    field_name = f"qty_{it.id}_wh_{wh['wh_id']}"
                    max_wh_qty = Decimal(str(wh["available"] or Decimal("0.0000")))
                    self.fields[field_name] = forms.DecimalField(
                        required=False,
                        min_value=Decimal("0.0000"),
                        max_value=max_wh_qty,
                        decimal_places=4,
                        max_digits=12,
                        initial=Decimal("0.0000"),
                        localize=True,
                    )
                    warehouse_fields.append(
                        {
                            "field_name": field_name,
                            "wh_id": wh["wh_id"],
                            "wh_name": wh["wh_name"],
                            "available": max_wh_qty,
                        }
                    )
                self.rows.append(
                    {
                        "warehouse_input": wi,
                        "item": it,
                        "max_qty": max_qty,
                        "stock_by_wh": [(w["wh_name"], w["available"]) for w in wh_defs],
                        "stock_total": stock_total_by_rm.get(artikl_rm_id, Decimal("0.0000")),
                        "warehouse_fields": warehouse_fields,
                    }
                )

    def clean(self):
        cleaned = super().clean()
        out: dict[int, dict[int, Decimal]] = {}
        out_wh: dict[int, dict[int, dict[int, Decimal]]] = {}
        has_any = False

        for row in self.rows:
            wi = row["warehouse_input"]
            it = row["item"]
            max_qty = row["max_qty"]
            total_qty = Decimal("0.0000")
            item_wh: dict[int, Decimal] = {}

            for whf in row["warehouse_fields"]:
                field_name = whf["field_name"]
                qty = cleaned.get(field_name)
                if qty is None:
                    qty = Decimal("0.0000")
                qty = Decimal(str(qty))
                if qty < Decimal("0.0000"):
                    self.add_error(field_name, "Količina ne može biti negativna.")
                    continue
                if qty > whf["available"]:
                    self.add_error(field_name, f"Maksimalno {whf['available']}.")
                    continue
                if qty > 0:
                    item_wh[whf["wh_id"]] = qty
                total_qty += qty

            if total_qty > max_qty:
                self.add_error(None, f"Stavka '{it.artikl}': zbroj po skladištima ne može biti veći od {max_qty}.")
                continue
            if total_qty <= Decimal("0.0000"):
                continue

            has_any = True
            out.setdefault(wi.id, {})[it.id] = total_qty
            out_wh.setdefault(wi.id, {})[it.id] = item_wh

        if not has_any:
            self.add_error(None, "Unesi barem jednu količinu za povrat (veću od 0).")

        self.line_quantities_by_input_id = out
        self.warehouse_quantities_by_input_id = out_wh
        return cleaned


@admin.action(description="Rastavi narudžbu u više primki", permissions=["change"])
def split_purchase_order_into_three_inputs(modeladmin, request, queryset):
    if queryset.count() != 1:
        modeladmin.message_user(
            request,
            "Odaberi točno jednu narudžbu za rastavljanje u primke.",
            level=messages.ERROR,
        )
        return
    order = queryset.first()
    if order.status == PurchaseOrder.STATUS_RECEIVED_ALL:
        modeladmin.message_user(
            request,
            "Sve stavke s narudžbe su zaprimljene i ne može se raditi nova primka.",
            level=messages.ERROR,
        )
        return
    url = reverse("admin:orders_purchaseorder_split_primke", args=[order.id])
    return HttpResponseRedirect(url)


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    class PurchaseOrderAdminForm(forms.ModelForm):
        ordered_at = forms.DateTimeField(
            required=True,
            input_formats=[
                "%d.%m.%Y",
                "%d.%m.%Y %H:%M",
                "%d.%m.%Y %H.%M",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S",
            ],
            widget=forms.DateTimeInput(
                format="%d.%m.%Y %H:%M",
                attrs={"class": "js-flatpickr-datetime"},
            ),
        )

        class Meta:
            model = PurchaseOrder
            fields = "__all__"

    form = PurchaseOrderAdminForm
    list_display = ("id", "supplier", "ordered_at", "status_badge", "total_net", "total_gross", "payment_type", "primka_created", "created_by")
    list_filter = ("supplier", "ordered_at", "status", "payment_type", "primka_created", "created_by")
    search_fields = ("id", "supplier__name", "created_by__username")
    autocomplete_fields = ("supplier",)
    inlines = [PurchaseOrderItemInline]
    actions = [
        send_order_email,
        create_warehouse_input,
        split_purchase_order_into_three_inputs,
        copy_purchase_order,
    ]
    fields = (
        "supplier",
        "ordered_at",
        "status",
        "payment_type",
        "created_by",
        "primka_created",
        "confirmation_token",
        "confirmation_sent_at",
        "confirmed_at",
        "total_net",
        "tax_group_totals",
        "total_deposit",
        "total_gross",
    )
    readonly_fields = (
        "created_by",
        "primka_created",
        "confirmation_token",
        "confirmation_sent_at",
        "confirmed_at",
        "total_net",
        "tax_group_totals",
        "total_deposit",
        "total_gross",
    )

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status in (PurchaseOrder.STATUS_RECEIVED, PurchaseOrder.STATUS_RECEIVED_ALL):
            return False
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        # Keep fully received orders in Django's built-in view-only mode.
        if obj and obj.status == PurchaseOrder.STATUS_RECEIVED_ALL:
            return False
        return super().has_change_permission(request, obj)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<path:object_id>/split-primke/",
                self.admin_site.admin_view(self.split_primke_view),
                name="orders_purchaseorder_split_primke",
            ),
        ]
        return custom + urls

    def split_primke_view(self, request, object_id):
        order = self.get_object(request, object_id)
        if not order:
            self.message_user(request, "Narudžba ne postoji.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:orders_purchaseorder_changelist"))
        if order.status == PurchaseOrder.STATUS_RECEIVED_ALL:
            self.message_user(
                request,
                "Sve stavke s narudžbe su zaprimljene i ne može se raditi nova primka.",
                level=messages.ERROR,
            )
            return HttpResponseRedirect(reverse("admin:orders_purchaseorder_change", args=[order.id]))

        items = list(
            order.items.select_related("artikl__tax_group", "unit_of_measure").order_by("id")
        )
        if not items:
            self.message_user(request, "Narudžba nema stavke.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:orders_purchaseorder_change", args=[order.id]))

        form = CreateWarehouseInputFromPoSelectionForm(
            data=request.POST or None,
            order=order,
            items=items,
        )
        if request.method == "POST" and form.is_valid():
            with transaction.atomic():
                wi = form.create_input()
                if wi and form.bump_order_qty_by_item_id:
                    changed_lines = []
                    for it in items:
                        new_qty = form.bump_order_qty_by_item_id.get(it.id)
                        if new_qty is None:
                            continue
                        changed_lines.append(f"{it.artikl}: {new_qty}")
                    if changed_lines:
                        self.message_user(
                            request,
                            "Količine na narudžbi su povećane zbog većih zaprimljenih količina: "
                            + "; ".join(changed_lines[:10]),
                            level=messages.INFO,
                        )
                if wi and not order.primka_created:
                    order.primka_created = True
                    order.save(update_fields=["primka_created"])

                # Mark as received only if everything is received (after this primka).
                if wi:
                    received_by_artikl = _po_received_by_artikl(order)
                    remaining_map = _po_item_remaining_map(items, received_by_artikl)
                    if all(v["remaining"] == Decimal("0") for v in remaining_map.values()):
                        order.status = PurchaseOrder.STATUS_RECEIVED_ALL
                        order.save(update_fields=["status"])
                    elif order.status not in (PurchaseOrder.STATUS_RECEIVED, PurchaseOrder.STATUS_RECEIVED_ALL):
                        # Partial deliveries: mark STATUS_RECEIVED and still allow
                        # creating additional primke until fully received.
                        order.status = PurchaseOrder.STATUS_RECEIVED
                        order.save(update_fields=["status"])

            if not wi:
                self.message_user(
                    request,
                    "Nije kreirana primka (nema odabranih stavki ili su sve količine 0).",
                    level=messages.ERROR,
                )
                return HttpResponseRedirect(request.path)

            url = reverse("admin:orders_warehouseinput_change", args=[wi.id])
            self.message_user(
                request,
                format_html('Kreirana primka: <a href="{}" target="_blank">#{}</a>', url, wi.id),
                level=messages.SUCCESS,
            )
            return HttpResponseRedirect(request.path)

        rows = []
        for it in items:
            info = form.qty_info_by_item_id.get(it.id) if hasattr(form, "qty_info_by_item_id") else None
            rows.append(
                {
                    "item": it,
                    "sel": form[f"sel_{it.id}"],
                    "qty": form[f"qty_{it.id}"],
                    "ordered": (info or {}).get("ordered"),
                    "received": (info or {}).get("received"),
                    "remaining": (info or {}).get("remaining"),
                }
            )

        ctx = dict(
            self.admin_site.each_context(request),
            title=f"Rastavi narudžbu #{order.id} u više primki",
            order=order,
            rows=rows,
            form=form,
            opts=self.model._meta,
        )
        return TemplateResponse(request, "admin/orders/purchaseorder/split_primke.html", ctx)

    class Media:
        css = {
            "all": ("orders/css/purchase_order_status.css",),
        }
        js = ("orders/js/purchase_order_status.js",)

    def save_model(self, request, obj, form, change):
        if change:
            if obj.created_by_id:
                obj.created_by_id = PurchaseOrder.objects.values_list(
                    "created_by_id",
                    flat=True,
                ).get(pk=obj.pk)
            else:
                obj.created_by = request.user
        else:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def status_badge(self, obj):
        label = obj.get_status_display()
        colors = {
            PurchaseOrder.STATUS_CREATED: "#d9ecff",
            PurchaseOrder.STATUS_SENT: "#ffe5cc",
            PurchaseOrder.STATUS_CONFIRMED: "#fff7cc",
            PurchaseOrder.STATUS_RECEIVED: "#d9f7d9",
            PurchaseOrder.STATUS_RECEIVED_ALL: "#c2f0c2",
            PurchaseOrder.STATUS_CANCELED: "#ffd6d6",
        }
        color = colors.get(obj.status)
        if color:
            return format_html(
                '<span style="background:{};padding:2px 6px;border-radius:4px;">{}</span>',
                color,
                label,
            )
        return label

    status_badge.short_description = "status"

    def tax_group_totals(self, obj):
        totals = obj.get_tax_group_totals()
        if not totals:
            return "-"
        lines = []
        for item in totals:
            rate = Decimal(item["rate"]) * Decimal("100")
            rate_label = _fmt_decimal(rate)
            tax_label = _fmt_decimal(item["tax"])
            lines.append(f"{item['tax_group'].name} ({rate_label}%): {tax_label} EUR")
        return format_html("<br>".join(lines))

    tax_group_totals.short_description = "PDV po stopama"


def _eval_decimal_expr(node):
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left = _eval_decimal_expr(node.left)
        right = _eval_decimal_expr(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_decimal_expr(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Decimal(str(node.value))
    if isinstance(node, ast.Num):
        return Decimal(str(node.n))
    raise ValueError("invalid expr")


class SupplierPriceItemAdminForm(forms.ModelForm):
    price = forms.CharField()

    class Meta:
        model = SupplierPriceItem
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        unit_of_measure = cleaned_data.get("unit_of_measure")
        artikl = cleaned_data.get("artikl")
        if not unit_of_measure and artikl:
            detail = getattr(artikl, "detail", None)
            default_uom = getattr(detail, "unit_of_measure", None) if detail else None
            if default_uom:
                cleaned_data["unit_of_measure"] = default_uom
            else:
                self.add_error(
                    "unit_of_measure",
                    "Odaberite jedinicu mjere ili postavite zadanu na artiklu.",
                )
        return cleaned_data

    def clean_price(self):
        value = self.cleaned_data.get("price")
        if value is None:
            return value
        if isinstance(value, Decimal):
            return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            expr = raw[1:] if raw.startswith("=") else raw
            expr = expr.replace(",", ".")
            if not re.fullmatch(r"[0-9+\-*/().\s]+", expr):
                raise forms.ValidationError("Neispravan izraz za cijenu.")
            try:
                node = ast.parse(expr, mode="eval")
                result = _eval_decimal_expr(node.body)
            except Exception:
                raise forms.ValidationError("Neispravan izraz za cijenu.")
            return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return value


class SupplierPriceItemInline(admin.TabularInline):
    model = SupplierPriceItem
    form = SupplierPriceItemAdminForm
    extra = 0
    autocomplete_fields = ("artikl", "unit_of_measure")
    formfield_overrides = {
        models.DecimalField: {"localize": True},
    }


@admin.register(SupplierPriceList)
class SupplierPriceListAdmin(admin.ModelAdmin):
    class SupplierPriceListAdminForm(forms.ModelForm):
        valid_from = forms.DateField(
            required=False,
            input_formats=[
                "%d.%m.%Y",
                "%Y-%m-%d",
            ],
            widget=forms.DateInput(
                format="%d.%m.%Y",
                attrs={"class": "js-flatpickr-date"},
            ),
        )
        valid_to = forms.DateField(
            required=False,
            input_formats=[
                "%d.%m.%Y",
                "%Y-%m-%d",
            ],
            widget=forms.DateInput(
                format="%d.%m.%Y",
                attrs={"class": "js-flatpickr-date"},
            ),
        )

        class Meta:
            model = SupplierPriceList
            fields = "__all__"

    form = SupplierPriceListAdminForm
    list_display = ("supplier", "name", "created_at", "valid_from", "valid_to", "currency", "is_active")
    list_filter = ("supplier", "is_active")
    search_fields = ("supplier__name", "name")
    autocomplete_fields = ("supplier",)
    inlines = [SupplierPriceItemInline]
