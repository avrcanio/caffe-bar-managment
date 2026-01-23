from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urljoin
import ast
import re
import json

from django import forms
from django.contrib import admin, messages
from email.utils import formataddr, parseaddr
from django.db import models, transaction
from django.core.mail import EmailMessage
from django.utils import timezone
from django.utils.html import format_html
from django.conf import settings
from django.urls import reverse
import requests

from configuration.models import CompanyProfile, OrderEmailTemplate
from artikli.remaris_connector import RemarisConnector

from .models import (
    PurchaseOrder,
    PurchaseOrderItem,
    SupplierPriceItem,
    SupplierPriceList,
    WarehouseInput,
    WarehouseInputItem,
)
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
    return value.strftime("%-d.%-m.%Y.")


def _fmt_datetime(value):
    if not value:
        return ""
    return value.strftime("%-d.%-m.%Y. %H:%M:%S")


def _fmt_date_time_zero(value):
    if not value:
        return ""
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
    formfield_overrides = {
        models.DecimalField: {"localize": True},
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
        "DocumentType": str(warehouse_input.document_type or "10"),
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


@admin.register(WarehouseInput)
class WarehouseInputAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "supplier", "warehouse", "date", "document_type", "total", "is_canceled")
    list_filter = ("document_type", "is_canceled", "supplier", "warehouse")
    search_fields = ("id", "invoice_code", "delivery_note", "purchase_order__id")
    autocomplete_fields = ("order", "purchase_order", "supplier", "payment_type", "warehouse")
    inlines = [WarehouseInputItemInline]
    actions = ["send_warehouse_input_to_remaris"]

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

            WarehouseInputItem.objects.bulk_create(items)
            if not order.primka_created:
                order.primka_created = True
                order.status = PurchaseOrder.STATUS_RECEIVED
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


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "supplier", "ordered_at", "status_badge", "total_net", "total_gross", "payment_type", "primka_created")
    list_filter = ("supplier", "ordered_at", "status", "payment_type", "primka_created")
    search_fields = ("id", "supplier__name")
    autocomplete_fields = ("supplier",)
    inlines = [PurchaseOrderItemInline]
    actions = [send_order_email, create_warehouse_input, copy_purchase_order]
    fields = (
        "supplier",
        "ordered_at",
        "status",
        "payment_type",
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
        "primka_created",
        "confirmation_token",
        "confirmation_sent_at",
        "confirmed_at",
        "total_net",
        "tax_group_totals",
        "total_deposit",
        "total_gross",
    )

    class Media:
        css = {
            "all": ("orders/css/purchase_order_status.css",),
        }
        js = ("orders/js/purchase_order_status.js",)

    def status_badge(self, obj):
        label = obj.get_status_display()
        colors = {
            PurchaseOrder.STATUS_CREATED: "#d9ecff",
            PurchaseOrder.STATUS_SENT: "#ffe5cc",
            PurchaseOrder.STATUS_CONFIRMED: "#fff7cc",
            PurchaseOrder.STATUS_RECEIVED: "#d9f7d9",
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
    list_display = ("supplier", "created_at", "valid_from", "valid_to", "currency", "is_active")
    list_filter = ("supplier", "is_active")
    search_fields = ("supplier__name",)
    autocomplete_fields = ("supplier",)
    inlines = [SupplierPriceItemInline]
