import hashlib
import os
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Case, DecimalField, F, IntegerField, Max, OuterRef, Q, Subquery, Value, When
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.http import parse_etags, quote_etag
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework.views import APIView

from artikli.models import Artikl, Category, Normativ
from pos.fiscal import fiscalize_pos_receipt
from pos.models import Pos, PosDevice
from pos.print_bridge import send_bar_ticket_to_print_bridge, send_receipt_pdf_to_print_bridge
from pos.security import is_recent_pin_verified, pin_verify_ttl_seconds
from pos.services import create_pos_receipt
from sales.models import SalesPriceItem, ShiftCashHandover, ShiftTurnover
from stock.models import StockMove
from stock.services import post_stock_out

from .catalog_sync import collect_delta_ids, earliest_catalog_event_version, get_catalog_version, get_product_sync_state
from .models import (
    BarionCategory,
    BarionCatalogSyncEvent,
    BarionRuntimeMode,
    CheckItemModifierSelection,
    Check,
    CheckItem,
    ItemBundleOption,
    ItemModifierGroupAssignment,
    ItemModifierOption,
    Layout,
    LayoutTable,
    SettlementPart,
    Table,
    TableState,
    UserLayoutAccess,
)


class ErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


class RuntimeModeSerializer(serializers.Serializer):
    active_mode = serializers.ChoiceField(choices=BarionRuntimeMode.Mode.choices)
    updated_at = serializers.DateTimeField()
    updated_by_id = serializers.IntegerField(allow_null=True)


class RuntimeModeUpdateRequestSerializer(serializers.Serializer):
    active_mode = serializers.ChoiceField(choices=BarionRuntimeMode.Mode.choices, required=True)


class ActiveLayoutLayoutSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    updated_at = serializers.DateTimeField()


class ActiveLayoutZoneSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    order = serializers.IntegerField()


class ActiveLayoutTableSerializer(serializers.Serializer):
    table_id = serializers.IntegerField()
    label = serializers.CharField()
    shape = serializers.CharField()
    capacity = serializers.IntegerField()
    is_vip = serializers.BooleanField()
    x = serializers.IntegerField()
    y = serializers.IntegerField()
    w = serializers.IntegerField()
    h = serializers.IntegerField()
    rotation = serializers.IntegerField()
    zone_id = serializers.IntegerField()


class AllowedLayoutItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_default = serializers.BooleanField()


class ActiveLayoutResponseSerializer(serializers.Serializer):
    resolved_by = serializers.CharField(required=False)
    layout = ActiveLayoutLayoutSerializer()
    zones = ActiveLayoutZoneSerializer(many=True)
    tables = ActiveLayoutTableSerializer(many=True)
    allowed_layouts = AllowedLayoutItemSerializer(many=True, required=False)


class AllowedLayoutsResponseSerializer(serializers.Serializer):
    layouts = AllowedLayoutItemSerializer(many=True)


class TableStatusItemSerializer(serializers.Serializer):
    table_id = serializers.IntegerField()
    open_check_id = serializers.IntegerField(allow_null=True)
    status = serializers.CharField()


class CheckSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    table_id = serializers.IntegerField()
    status = serializers.CharField()
    settlement_status = serializers.CharField(required=False)
    payment_status = serializers.CharField(required=False)
    pos_receipt_id = serializers.IntegerField(allow_null=True)
    opened_at = serializers.DateTimeField(allow_null=True)
    closed_at = serializers.DateTimeField(allow_null=True)


class CreateCheckRequestSerializer(serializers.Serializer):
    table_id = serializers.IntegerField()


class CreateCheckResponseSerializer(serializers.Serializer):
    created = serializers.BooleanField()
    check = CheckSerializer()


class CloseCheckResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    table_id = serializers.IntegerField()
    closed_at = serializers.DateTimeField(allow_null=True)


class CheckItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    check_id = serializers.IntegerField()
    artikl_id = serializers.IntegerField()
    artikl_name = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=4)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=4)
    vat_rate = serializers.DecimalField(max_digits=5, decimal_places=4)
    net_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    vat_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    round_number = serializers.IntegerField(
        allow_null=True,
        help_text="Broj runde na šank; null dok stavka nije poslana.",
    )
    sent_to_bar = serializers.BooleanField(help_text="True ako je stavka poslana na šank.")
    line_type = serializers.ChoiceField(
        choices=CheckItem.LineType.choices,
        help_text=(
            "Tip stavke: NORMAL (standardna prodaja), "
            "STORNO (negativna količina), GRATIS (cijena 0), OTPIS (otpis/waste)."
        ),
    )
    sent_at = serializers.DateTimeField(
        allow_null=True,
        help_text="Vrijeme slanja stavke na šank; null dok nije poslana.",
    )
    note = serializers.CharField()
    modifiers = serializers.ListField(child=serializers.JSONField(), required=False)
    display_lines = serializers.ListField(child=serializers.CharField(), required=False)
    modifiers_auto_applied = serializers.BooleanField(required=False)


class CheckItemsTotalsSerializer(serializers.Serializer):
    items_count = serializers.IntegerField()
    net_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    vat_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class CheckItemsResponseSerializer(serializers.Serializer):
    check_id = serializers.IntegerField()
    status = serializers.CharField()
    items = CheckItemSerializer(many=True)
    totals = CheckItemsTotalsSerializer()


def _ensure_whole_piece_quantity(value: Decimal) -> Decimal:
    qty = Decimal(str(value)).quantize(Decimal("0.0001"))
    if qty != qty.quantize(Decimal("1")):
        raise serializers.ValidationError("quantity mora biti cijeli broj komada.")
    return qty


class CreateCheckItemRequestSerializer(serializers.Serializer):
    artikl_id = serializers.IntegerField(required=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0.0001"))
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0.0000"))
    vat_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        required=False,
        min_value=Decimal("0.0000"),
        max_value=Decimal("0.9999"),
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")
    modifiers = serializers.ListField(child=serializers.JSONField(), required=False, default=list)

    def validate_quantity(self, value):
        return _ensure_whole_piece_quantity(value)


class UpdateCheckItemRequestSerializer(serializers.Serializer):
    artikl_id = serializers.IntegerField(required=False)
    quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=4,
        required=False,
        min_value=Decimal("0.0001"),
    )
    unit_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=4,
        required=False,
        min_value=Decimal("0.0000"),
    )
    vat_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        required=False,
        min_value=Decimal("0.0000"),
        max_value=Decimal("0.9999"),
    )
    note = serializers.CharField(required=False, allow_blank=True)
    modifiers = serializers.ListField(child=serializers.JSONField(), required=False)

    def validate_quantity(self, value):
        return _ensure_whole_piece_quantity(value)


class CheckItemActionRequestSerializer(serializers.Serializer):
    quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=4,
        required=False,
        min_value=Decimal("0.0001"),
        help_text="Optional partial quantity. If omitted, applies to full available quantity.",
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Opcionalni razlog akcije (audit napomena).",
    )

    def validate_quantity(self, value):
        return _ensure_whole_piece_quantity(value)


class PosProductSearchItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    rm_id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField()
    code = serializers.CharField(allow_null=True, allow_blank=True)
    image_46x75 = serializers.CharField(allow_null=True)
    thumbnail_url = serializers.CharField(allow_null=True)
    image_url = serializers.CharField(allow_null=True)
    image_version = serializers.IntegerField()
    modifier_version = serializers.IntegerField()
    category_id = serializers.IntegerField(allow_null=True)
    category_name = serializers.CharField(allow_null=True)
    category_sort_order = serializers.IntegerField(allow_null=True)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=4, allow_null=True)
    popularity_score = serializers.DecimalField(max_digits=14, decimal_places=4, allow_null=True)


class PosCategoryDisplayItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    parent_id = serializers.IntegerField(allow_null=True)
    sort_order = serializers.IntegerField()
    popularity_score = serializers.DecimalField(max_digits=14, decimal_places=4, allow_null=True)


class PosCategoryDisplayResponseSerializer(serializers.Serializer):
    root_id = serializers.IntegerField()
    display_level = serializers.IntegerField()
    categories = PosCategoryDisplayItemSerializer(many=True)


class PosBootstrapResponseSerializer(serializers.Serializer):
    catalog_version = serializers.IntegerField()
    active_mode = serializers.ChoiceField(choices=BarionRuntimeMode.Mode.choices)
    root_id = serializers.IntegerField(allow_null=True)
    display_level = serializers.IntegerField()
    categories = PosCategoryDisplayItemSerializer(many=True)
    selected_category_id = serializers.IntegerField(allow_null=True)
    products = PosProductSearchItemSerializer(many=True)


class ProductModifierOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    option_type = serializers.ChoiceField(choices=["simple", "bundle"])
    name = serializers.CharField()
    code = serializers.CharField()
    sort_order = serializers.IntegerField()
    artikl_id = serializers.IntegerField(allow_null=True, required=False)
    artikl_name = serializers.CharField(allow_null=True, required=False)
    price_delta = serializers.DecimalField(max_digits=12, decimal_places=4, required=False)
    is_default = serializers.BooleanField(required=False)
    default_quantity = serializers.IntegerField(required=False, allow_null=True)


class ProductModifierGroupSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()
    type = serializers.CharField()
    selection_mode = serializers.CharField()
    min_select = serializers.IntegerField()
    max_select = serializers.IntegerField()
    is_required = serializers.BooleanField()
    allow_note = serializers.BooleanField()
    options = ProductModifierOptionSerializer(many=True)


class ProductModifiersResponseSerializer(serializers.Serializer):
    artikl_id = serializers.IntegerField()
    modifier_version = serializers.IntegerField()
    modifier_groups = ProductModifierGroupSerializer(many=True)


class CatalogChangesEntitySerializer(serializers.Serializer):
    updated = serializers.ListField(child=serializers.JSONField())
    deleted = serializers.ListField(child=serializers.IntegerField())


class CatalogChangesResponseSerializer(serializers.Serializer):
    requiresFullSync = serializers.BooleanField()
    baseVersion = serializers.IntegerField()
    appliedThroughVersion = serializers.IntegerField()
    targetVersion = serializers.IntegerField()
    catalogVersion = serializers.IntegerField()
    layouts = CatalogChangesEntitySerializer()
    categories = CatalogChangesEntitySerializer()
    products = CatalogChangesEntitySerializer()
    hasMore = serializers.BooleanField()


class ProductBundlePriceRequestSerializer(serializers.Serializer):
    modifiers = serializers.ListField(child=serializers.JSONField(), required=False, default=list)


class ProductBundlePriceResponseSerializer(serializers.Serializer):
    artikl_id = serializers.IntegerField()
    base_unit_price = serializers.DecimalField(max_digits=12, decimal_places=4)
    mixers_delta = serializers.DecimalField(max_digits=12, decimal_places=4)
    final_unit_price = serializers.DecimalField(max_digits=12, decimal_places=4)
    mixers = serializers.ListField(child=serializers.JSONField(), required=False)


class IssueCheckReceiptRequestSerializer(serializers.Serializer):
    office_code = serializers.CharField(required=False, allow_blank=True)
    device_code = serializers.CharField(required=False, allow_blank=True)
    payment_type = serializers.CharField(required=False, allow_blank=True)
    pos_id = serializers.IntegerField(required=False)
    warehouse_id = serializers.IntegerField(required=False)
    device_id = serializers.CharField(required=False, allow_blank=True)
    fiscalize = serializers.BooleanField(required=False, default=True)


class IssueCheckReceiptResponseSerializer(serializers.Serializer):
    check_id = serializers.IntegerField()
    check_status = serializers.CharField(required=False)
    settlement_status = serializers.CharField(required=False)
    payment_status = serializers.CharField(required=False)
    receipt_id = serializers.IntegerField()
    receipt_number = serializers.IntegerField()
    status = serializers.CharField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    zki = serializers.CharField()
    jir = serializers.CharField()
    qr = serializers.CharField()
    parts = serializers.JSONField(required=False)
    totals = serializers.JSONField(required=False)
    actions = serializers.JSONField(required=False)


class SendCheckToBarResponseSerializer(serializers.Serializer):
    check_id = serializers.IntegerField()
    round_number = serializers.IntegerField()
    sent_items_count = serializers.IntegerField()
    sent_at = serializers.DateTimeField()
    ticket = serializers.JSONField()
    printed = serializers.BooleanField(required=False)
    print_error = serializers.CharField(required=False, allow_blank=True)


class SettlementPartRequestSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=SettlementPart.Method.choices)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    tip_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=Decimal("0.00"))


class PrepareSettlementRequestSerializer(serializers.Serializer):
    parts = SettlementPartRequestSerializer(many=True)
    ready_for_issue = serializers.BooleanField(required=False, default=False)


class SettlementPartResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    method = serializers.ChoiceField(choices=SettlementPart.Method.choices)
    method_display = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    tip_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_charged = serializers.DecimalField(max_digits=12, decimal_places=2)
    fiscal_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    status = serializers.ChoiceField(choices=SettlementPart.Status.choices)
    provider = serializers.CharField(allow_blank=True)
    provider_ref = serializers.CharField(allow_blank=True)
    card_masked_pan = serializers.CharField(allow_blank=True)
    card_brand = serializers.CharField(allow_blank=True)
    card_type = serializers.CharField(allow_blank=True)
    card_auth_code = serializers.CharField(allow_blank=True)
    card_rrn = serializers.CharField(allow_blank=True)
    card_bank_id = serializers.CharField(allow_blank=True)
    card_aid = serializers.CharField(allow_blank=True)
    card_application_label = serializers.CharField(allow_blank=True)
    provider_reference_number = serializers.CharField(allow_blank=True)
    provider_tid = serializers.CharField(allow_blank=True)
    provider_order_code = serializers.CharField(allow_blank=True)
    provider_short_order_code = serializers.CharField(allow_blank=True)
    provider_transaction_date = serializers.CharField(allow_blank=True)
    provider_payment_method = serializers.CharField(allow_blank=True)
    provider_account_number = serializers.CharField(allow_blank=True)
    provider_verification_method = serializers.CharField(allow_blank=True)
    provider_transaction_type_id = serializers.IntegerField(allow_null=True)
    provider_transaction_event_id = serializers.IntegerField(allow_null=True)
    provider_surcharge_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    provider_customer_trns = serializers.CharField(allow_blank=True)
    provider_status = serializers.CharField(allow_blank=True)
    provider_action = serializers.CharField(allow_blank=True)
    provider_message = serializers.CharField(allow_blank=True)
    provider_payload = serializers.JSONField(required=False)


class SettlementTotalsResponseSerializer(serializers.Serializer):
    check_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    allocated_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    confirmed_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    remaining_total = serializers.DecimalField(max_digits=12, decimal_places=2)


class SettlementActionsResponseSerializer(serializers.Serializer):
    can_confirm_card = serializers.BooleanField()
    can_issue_receipt = serializers.BooleanField()
    can_close_check = serializers.BooleanField()


class PrepareSettlementResponseSerializer(serializers.Serializer):
    check_id = serializers.IntegerField()
    settlement_status = serializers.CharField()
    payment_status = serializers.CharField()
    parts = SettlementPartResponseSerializer(many=True)
    totals = SettlementTotalsResponseSerializer()
    actions = SettlementActionsResponseSerializer()


class SettlementStateResponseSerializer(serializers.Serializer):
    check_id = serializers.IntegerField()
    check_status = serializers.CharField()
    settlement_status = serializers.CharField()
    payment_status = serializers.CharField()
    pos_receipt_id = serializers.IntegerField(allow_null=True)
    pos_receipt_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    receipts = serializers.JSONField(required=False)
    issued_receipt_id = serializers.IntegerField(allow_null=True)
    receipt_pdf_url = serializers.URLField(allow_null=True)
    parts = SettlementPartResponseSerializer(many=True)
    items = serializers.JSONField(required=False)
    totals = SettlementTotalsResponseSerializer()
    actions = SettlementActionsResponseSerializer()
    updated_at = serializers.DateTimeField()


class RoundStatePaidLineSerializer(serializers.Serializer):
    line_type = serializers.CharField()
    quantity = serializers.CharField()
    unit_price = serializers.CharField()
    total_amount = serializers.CharField()
    ui_color = serializers.CharField()


class RoundStateItemSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    check_id = serializers.IntegerField()
    artikl_id = serializers.IntegerField()
    artikl_name = serializers.CharField()
    round_number = serializers.IntegerField(allow_null=True)
    source_quantity = serializers.CharField()
    sold_quantity = serializers.CharField()
    storno_quantity = serializers.CharField()
    gratis_quantity = serializers.CharField()
    otpis_quantity = serializers.CharField()
    remaining_quantity = serializers.CharField()
    strike_main = serializers.BooleanField()
    paid_line = RoundStatePaidLineSerializer(allow_null=True)


class RoundStateResponseSerializer(serializers.Serializer):
    check_id = serializers.IntegerField()
    status = serializers.CharField()
    items = RoundStateItemSerializer(many=True)
    updated_at = serializers.DateTimeField()


class PayCardConfirmRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=Decimal("0.01"))
    external_txn_id = serializers.CharField(required=False, allow_blank=True, max_length=100)
    issue_receipt = serializers.BooleanField(required=False, default=False)


class SettlementPartPayCashItemSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(required=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0.0001"))

    def validate_quantity(self, value):
        return _ensure_whole_piece_quantity(value)


class SettlementPartPayCashRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal("0.00"),
    )
    items = SettlementPartPayCashItemSerializer(many=True, required=False)

    def validate(self, attrs):
        amount = attrs.get("amount")
        items = attrs.get("items")
        if amount is None and not items:
            raise serializers.ValidationError("Potrebno je poslati amount ili items.")
        if amount is not None and amount <= Decimal("0.00"):
            if items:
                attrs["amount"] = None
            else:
                raise serializers.ValidationError({"amount": "amount mora biti veći od 0.00."})
        return attrs


class SettlementPartPayCardConfirmRequestSerializer(serializers.Serializer):
    approved = serializers.BooleanField(required=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=Decimal("0.01"))
    tip_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=Decimal("0.00"))
    provider = serializers.CharField(required=False, allow_blank=True, max_length=20)
    external_txn_id = serializers.CharField(required=False, allow_blank=True, max_length=100)
    provider_ref = serializers.CharField(required=False, allow_blank=True, max_length=100)
    card_masked_pan = serializers.CharField(required=False, allow_blank=True, max_length=32)
    card_brand = serializers.CharField(required=False, allow_blank=True, max_length=50)
    card_type = serializers.CharField(required=False, allow_blank=True, max_length=50)
    card_auth_code = serializers.CharField(required=False, allow_blank=True, max_length=50)
    card_rrn = serializers.CharField(required=False, allow_blank=True, max_length=50)
    card_bank_id = serializers.CharField(required=False, allow_blank=True, max_length=50)
    card_aid = serializers.CharField(required=False, allow_blank=True, max_length=64)
    card_application_label = serializers.CharField(required=False, allow_blank=True, max_length=100)
    rrn = serializers.CharField(required=False, allow_blank=True, max_length=50)
    reference_number = serializers.CharField(required=False, allow_blank=True, max_length=50)
    authorisation_code = serializers.CharField(required=False, allow_blank=True, max_length=50)
    tid = serializers.CharField(required=False, allow_blank=True, max_length=50)
    order_code = serializers.CharField(required=False, allow_blank=True, max_length=100)
    short_order_code = serializers.CharField(required=False, allow_blank=True, max_length=50)
    transaction_date = serializers.CharField(required=False, allow_blank=True, max_length=64)
    payment_method = serializers.CharField(required=False, allow_blank=True, max_length=50)
    account_number = serializers.CharField(required=False, allow_blank=True, max_length=64)
    verification_method = serializers.CharField(required=False, allow_blank=True, max_length=100)
    aid = serializers.CharField(required=False, allow_blank=True, max_length=64)
    bank_id = serializers.CharField(required=False, allow_blank=True, max_length=50)
    transaction_type_id = serializers.IntegerField(required=False, allow_null=True)
    transaction_event_id = serializers.IntegerField(required=False, allow_null=True)
    surcharge_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=Decimal("0.00"))
    customer_trns = serializers.CharField(required=False, allow_blank=True)
    provider_status = serializers.CharField(required=False, allow_blank=True, max_length=30)
    provider_action = serializers.CharField(required=False, allow_blank=True, max_length=30)
    provider_message = serializers.CharField(required=False, allow_blank=True, max_length=255)
    provider_payload = serializers.JSONField(required=False)
    issue_receipt = serializers.BooleanField(required=False, default=False)

    def validate_provider(self, value):
        provider = str(value or "").strip().upper()
        if not provider:
            return ""
        allowed = {SettlementPart.Provider.VIVA}
        if provider not in allowed:
            raise serializers.ValidationError("provider mora biti jedan od: VIVA.")
        return provider


class PayCardConfirmResponseSerializer(serializers.Serializer):
    check_id = serializers.IntegerField()
    settlement_status = serializers.CharField()
    payment_status = serializers.CharField()
    card_confirmed = serializers.BooleanField()
    issued_receipt_id = serializers.IntegerField(allow_null=True)
    pos_receipt_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    receipts = serializers.JSONField(required=False)
    receipt_pdf_url = serializers.URLField(allow_null=True)
    remaining_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    check_closed = serializers.BooleanField()
    action = serializers.CharField()
    parts = SettlementPartResponseSerializer(many=True, required=False)
    totals = SettlementTotalsResponseSerializer(required=False)
    actions = SettlementActionsResponseSerializer(required=False)


def _resolve_effective_mode(*, requested_mode: str | None) -> tuple[str, BarionRuntimeMode]:
    _ = requested_mode  # Client-provided mode is intentionally ignored; backend runtime mode is authoritative.
    runtime_mode = BarionRuntimeMode.get_solo()
    effective_mode = runtime_mode.active_mode or BarionRuntimeMode.Mode.DAY
    return effective_mode, runtime_mode


def _category_subtree_q(category: Category, *, prefix: str = "category") -> Q:
    return Q(
        **{
            f"{prefix}__tree_id": category.tree_id,
            f"{prefix}__lft__gte": category.lft,
            f"{prefix}__rght__lte": category.rght,
        }
    )


def _is_category_within_subtree(node: Category, ancestor: Category, *, include_self: bool = True) -> bool:
    left_ok = node.lft >= ancestor.lft if include_self else node.lft > ancestor.lft
    right_ok = node.rght <= ancestor.rght if include_self else node.rght < ancestor.rght
    return node.tree_id == ancestor.tree_id and left_ok and right_ok


def _active_barion_category_nodes_for_subtree(root: Category) -> list[Category]:
    return list(
        Category.objects.filter(
            barion_categories__is_active=True,
            is_active=True,
            tree_id=root.tree_id,
            lft__gte=root.lft,
            rght__lte=root.rght,
        )
        .only("id", "name", "parent_id", "tree_id", "lft", "rght", "level")
        .distinct()
        .order_by("lft")
    )


def _delegated_barion_descendants(category: Category, *, active_barion_nodes: list[Category]) -> list[Category]:
    return [
        node
        for node in active_barion_nodes
        if node.id != category.id and _is_category_within_subtree(node, category, include_self=False)
    ]


def _is_in_delegated_subtree(node: Category, delegated_nodes: list[Category]) -> bool:
    return any(_is_category_within_subtree(node, delegated, include_self=True) for delegated in delegated_nodes)


def _resolve_root_category(*, raw_root_id: str | None) -> Category | None:
    if raw_root_id in (None, ""):
        return None
    try:
        root_id = int(raw_root_id)
    except (TypeError, ValueError):
        raise serializers.ValidationError("root_id mora biti broj.")
    root = Category.objects.filter(id=root_id, is_active=True).first()
    if not root:
        return None
    return root


def _active_modifier_assignments_for_artikl(artikl_id: int):
    return (
        ItemModifierGroupAssignment.objects.select_related("group")
        .prefetch_related(
            "group__options",
            "group__bundle_options__artikl",
            "default_selections__option",
            "default_selections__bundle_option__artikl",
        )
        .filter(
            artikl_id=artikl_id,
            is_active=True,
            group__is_active=True,
        )
        .order_by("group__sort_order", "group__name", "id")
    )


def _absolute_artikl_image_url(*, request, artikl: Artikl, size: str) -> str | None:
    if not artikl.image or artikl.rm_id is None:
        return None
    path = f"/api/artikli/{artikl.rm_id}/{size}/"
    return request.build_absolute_uri(path)


def _product_versions_for_artikl(artikl: Artikl) -> tuple[int, int]:
    sync_state = get_product_sync_state(artikl_id=artikl.id)
    if not sync_state:
        return 1, 1
    return int(sync_state.image_version), int(sync_state.modifier_version)


def _serialize_product_row(*, request, artikl: Artikl) -> dict:
    image_46x75 = _absolute_artikl_image_url(request=request, artikl=artikl, size="image-46x75")
    image_url = _absolute_artikl_image_url(request=request, artikl=artikl, size="image-125x200")
    image_version, modifier_version = _product_versions_for_artikl(artikl)
    return {
        "id": artikl.id,
        "rm_id": artikl.rm_id,
        "name": artikl.name,
        "code": artikl.code,
        "image_46x75": image_46x75,
        "thumbnail_url": image_46x75,
        "image_url": image_url,
        "image_version": image_version,
        "modifier_version": modifier_version,
        "category_id": artikl.category_id,
        "category_name": artikl.category.name if artikl.category_id else None,
        "category_sort_order": artikl.category.sort_order if artikl.category_id else None,
        "unit_price": artikl.active_unit_price,
        "tax_rate": artikl.tax_group.rate if artikl.tax_group_id else None,
        "popularity_score": artikl.popularity_score,
    }


def _serialize_layout_snapshot(*, layout: Layout) -> dict:
    zones = list(layout.zones.order_by("order", "id").values("id", "name", "order"))
    placements = (
        LayoutTable.objects.select_related("table")
        .filter(layout=layout, is_enabled=True)
        .order_by("z_index", "id")
    )
    tables = [
        {
            "table_id": placement.table_id,
            "label": placement.table.label,
            "shape": placement.table.shape,
            "capacity": placement.table.capacity,
            "is_vip": placement.table.is_vip,
            "x": placement.x,
            "y": placement.y,
            "w": placement.w,
            "h": placement.h,
            "rotation": placement.rotation,
            "zone_id": placement.zone_id,
        }
        for placement in placements
    ]
    return {
        "id": layout.id,
        "name": layout.name,
        "is_active": layout.is_active,
        "updated_at": layout.updated_at.isoformat(),
        "zones": zones,
        "tables": tables,
    }


def _default_modifier_ids_for_artikl(artikl_id: int) -> list[tuple[str, int, int]]:
    assignments = list(_active_modifier_assignments_for_artikl(artikl_id))
    normalized: list[tuple[str, int, int]] = []
    simple_seen: set[int] = set()
    bundle_qty: dict[int, int] = {}

    for assignment in assignments:
        for selection in assignment.default_selections.all().order_by("id"):
            if selection.option_id:
                if not selection.option.is_active:
                    continue
                option_id = int(selection.option_id)
                if option_id in simple_seen:
                    continue
                normalized.append(("simple", option_id, 1))
                simple_seen.add(option_id)
                continue
            if not selection.bundle_option_id:
                continue
            if not selection.bundle_option.is_active:
                continue
            option_id = int(selection.bundle_option_id)
            bundle_qty[option_id] = bundle_qty.get(option_id, 0) + int(selection.quantity or 1)

    for option_id, quantity in bundle_qty.items():
        normalized.append(("bundle", option_id, quantity))
    return normalized


def _resolve_group_min_max(assignment: ItemModifierGroupAssignment) -> tuple[int, int]:
    group = assignment.group
    min_select = assignment.min_select_override if assignment.min_select_override is not None else group.min_select
    max_select = assignment.max_select_override if assignment.max_select_override is not None else group.max_select
    if group.selection_mode == group.SelectionMode.SINGLE:
        max_select = 1
    return int(min_select), int(max_select)


def _normalize_modifier_ids(raw_modifier_ids) -> list[tuple[str, int, int]]:
    if raw_modifier_ids is None:
        return []
    normalized: list[tuple[str, int, int]] = []
    simple_seen = set()
    bundle_qty: dict[int, int] = {}
    for raw in raw_modifier_ids:
        if isinstance(raw, dict):
            option_type = str(raw.get("type") or "simple").strip().lower()
            raw_id = raw.get("id")
            raw_qty = raw.get("quantity", 1)
        else:
            option_type = "simple"
            raw_id = raw
            raw_qty = 1
        if option_type not in {"simple", "bundle"}:
            raise serializers.ValidationError("Modifier type mora biti simple ili bundle.")
        try:
            option_id = int(raw_id)
        except (TypeError, ValueError):
            raise serializers.ValidationError("Modifier id mora biti broj.")
        if option_id <= 0:
            raise serializers.ValidationError("Modifier id mora biti >= 1.")
        try:
            quantity = int(raw_qty)
        except (TypeError, ValueError):
            raise serializers.ValidationError("Modifier quantity mora biti broj.")
        if quantity <= 0:
            raise serializers.ValidationError("Modifier quantity mora biti >= 1.")
        if option_type == "simple":
            key = ("simple", option_id, 1)
            if option_id in simple_seen:
                continue
            normalized.append(key)
            simple_seen.add(option_id)
        else:
            bundle_qty[option_id] = bundle_qty.get(option_id, 0) + quantity
    for option_id, quantity in bundle_qty.items():
        normalized.append(("bundle", option_id, quantity))
    return normalized


def _validate_modifier_ids_for_artikl(*, artikl_id: int, modifier_ids: list[tuple[str, int, int]]) -> dict:
    assignments = list(_active_modifier_assignments_for_artikl(artikl_id))
    allowed_option_to_assignment: dict[tuple[str, int], ItemModifierGroupAssignment] = {}
    group_selected_count: dict[int, int] = {}

    for assignment in assignments:
        for option in assignment.group.options.all():
            if not option.is_active:
                continue
            allowed_option_to_assignment[("simple", option.id)] = assignment
        for bundle_option in assignment.group.bundle_options.all():
            if not bundle_option.is_active:
                continue
            allowed_option_to_assignment[("bundle", bundle_option.id)] = assignment

    for option_type, option_id, quantity in modifier_ids:
        assignment = allowed_option_to_assignment.get((option_type, option_id))
        if not assignment:
            raise serializers.ValidationError(f"Modifier option {option_type}:{option_id} nije dozvoljen za ovaj artikl.")
        group_selected_count[assignment.group_id] = group_selected_count.get(assignment.group_id, 0) + int(quantity)

    for assignment in assignments:
        min_select, max_select = _resolve_group_min_max(assignment)
        selected = group_selected_count.get(assignment.group_id, 0)
        if assignment.is_required and selected == 0:
            raise serializers.ValidationError(f"Grupa '{assignment.group.name}' je obavezna.")
        if selected < min_select:
            raise serializers.ValidationError(
                f"Grupa '{assignment.group.name}' zahtijeva barem {min_select} odabira."
            )
        if selected > max_select:
            raise serializers.ValidationError(
                f"Grupa '{assignment.group.name}' dopušta najviše {max_select} odabira."
            )

    return allowed_option_to_assignment


def _enforce_qty_customization_rule(*, quantity: Decimal, note: str, modifier_ids: list[tuple[str, int, int]]):
    qty = Decimal(str(quantity)).quantize(Decimal("0.0001"))
    has_customization = bool((note or "").strip()) or bool(modifier_ids)
    if has_customization and qty != Decimal("1.0000"):
        raise serializers.ValidationError("Ako stavka ima opciju ili napomenu, quantity mora biti 1.")


def _set_check_item_modifiers(
    *,
    check_item: CheckItem,
    modifier_ids: list[tuple[str, int, int]],
    allowed_option_to_assignment: dict[tuple[str, int], ItemModifierGroupAssignment],
):
    CheckItemModifierSelection.objects.filter(check_item=check_item).delete()
    if not modifier_ids:
        return
    rows = []
    for option_type, option_id, quantity in modifier_ids:
        assignment = allowed_option_to_assignment[(option_type, option_id)]
        rows.append(
            CheckItemModifierSelection(
                check_item=check_item,
                group_id=assignment.group_id,
                option_id=option_id if option_type == "simple" else None,
                bundle_option_id=option_id if option_type == "bundle" else None,
                quantity=int(quantity),
            )
        )
    CheckItemModifierSelection.objects.bulk_create(rows)


def _serialize_check_item_modifiers(item: CheckItem) -> list[dict]:
    selections = (
        item.modifier_selections.select_related("group", "option", "bundle_option__artikl")
        .all()
        .order_by("group__sort_order", "group__name", "id")
    )
    rows = []
    for sel in selections:
        if sel.option_id:
            rows.append(
                {
                    "group_id": sel.group_id,
                    "group_name": sel.group.name,
                    "group_code": sel.group.code,
                    "option_type": "simple",
                    "option_id": sel.option_id,
                    "option_name": sel.option.name,
                    "option_code": sel.option.code,
                    "quantity": 1,
                    "artikl_id": None,
                    "artikl_name": None,
                    "price_delta": "0.0000",
                }
            )
            continue
        rows.append(
            {
                "group_id": sel.group_id,
                "group_name": sel.group.name,
                "group_code": sel.group.code,
                "option_type": "bundle",
                "option_id": sel.bundle_option_id,
                "option_name": sel.bundle_option.artikl.name,
                "option_code": sel.bundle_option.artikl.code or str(sel.bundle_option.artikl_id),
                "quantity": int(sel.quantity),
                "artikl_id": sel.bundle_option.artikl_id,
                "artikl_name": sel.bundle_option.artikl.name,
                "price_delta": str((Decimal(str(sel.bundle_option.price_delta)) * Decimal(str(sel.quantity))).quantize(Decimal("0.0000"))),
            }
        )
    return rows


def _bundle_options_total_delta(modifier_ids: list[tuple[str, int, int]]) -> Decimal:
    bundle_ids = [option_id for option_type, option_id, _qty in modifier_ids if option_type == "bundle"]
    if not bundle_ids:
        return Decimal("0.0000")
    option_map = {
        row.id: Decimal(str(row.price_delta)).quantize(Decimal("0.0001"))
        for row in ItemBundleOption.objects.filter(id__in=bundle_ids, is_active=True)
    }
    total = Decimal("0.0000")
    for option_type, option_id, qty in modifier_ids:
        if option_type != "bundle":
            continue
        total += option_map.get(option_id, Decimal("0.0000")) * Decimal(str(qty))
    return total.quantize(Decimal("0.0001"))


def _build_check_item_display_lines(item: CheckItem) -> list[str]:
    lines = []
    for row in _serialize_check_item_modifiers(item):
        qty = int(row.get("quantity") or 1)
        if qty > 1:
            lines.append(f"• {row['option_name']} x{qty}")
        else:
            lines.append(f"• {row['option_name']}")
    note = (item.note or "").strip()
    if note:
        lines.append(f"• Napomena: {note}")
    return lines


def _active_sales_unit_price_for_artikl(artikl_id: int) -> Decimal | None:
    now = timezone.now()
    unit_price = (
        SalesPriceItem.objects.filter(
            artikl_id=artikl_id,
            is_active=True,
            price_list__is_active=True,
            price_list__valid_from__lte=now,
        )
        .filter(Q(price_list__valid_to__isnull=True) | Q(price_list__valid_to__gte=now))
        .order_by("-price_list__valid_from", "-price_list__created_at", "-id")
        .values_list("unit_price_gross", flat=True)
        .first()
    )
    if unit_price is None:
        return None
    return Decimal(str(unit_price)).quantize(Decimal("0.0001"))


def _has_bundle_modifiers(modifier_ids: list[tuple[str, int, int]]) -> bool:
    return any(option_type == "bundle" for option_type, _option_id, _qty in modifier_ids)


def _resolve_effective_unit_price_for_item(
    *,
    artikl_id: int,
    requested_unit_price: Decimal | None,
    current_unit_price: Decimal | None,
    modifier_ids: list[tuple[str, int, int]],
) -> Decimal:
    if _has_bundle_modifiers(modifier_ids):
        base_unit_price = _active_sales_unit_price_for_artikl(artikl_id)
        if base_unit_price is None:
            raise serializers.ValidationError("Za bundle artikl nema aktivne prodajne cijene.")
        return (base_unit_price + _bundle_options_total_delta(modifier_ids)).quantize(Decimal("0.0001"))
    if requested_unit_price is not None:
        return Decimal(str(requested_unit_price)).quantize(Decimal("0.0001"))
    if current_unit_price is not None:
        return Decimal(str(current_unit_price)).quantize(Decimal("0.0001"))
    raise serializers.ValidationError("unit_price je obavezan kada nema bundle modifera.")


def _serialize_bundle_breakdown(modifier_ids: list[tuple[str, int, int]]) -> list[dict]:
    bundle_map: dict[int, int] = {}
    for option_type, option_id, qty in modifier_ids:
        if option_type != "bundle":
            continue
        bundle_map[option_id] = bundle_map.get(option_id, 0) + int(qty)
    if not bundle_map:
        return []
    options = ItemBundleOption.objects.select_related("artikl").filter(id__in=list(bundle_map.keys()), is_active=True)
    rows: list[dict] = []
    for option in options:
        qty = bundle_map.get(option.id, 0)
        unit_delta = Decimal(str(option.price_delta)).quantize(Decimal("0.0000"))
        total_delta = (unit_delta * Decimal(str(qty))).quantize(Decimal("0.0000"))
        rows.append(
            {
                "bundle_option_id": option.id,
                "artikl_id": option.artikl_id,
                "artikl_name": option.artikl.name,
                "quantity": qty,
                "price_delta_unit": str(unit_delta),
                "price_delta_total": str(total_delta),
            }
        )
    rows.sort(key=lambda row: (str(row["artikl_name"]).lower(), int(row["bundle_option_id"])))
    return rows


def _add_stock_line(lines_by_artikl: dict[int, dict], *, artikl: Artikl, quantity: Decimal) -> None:
    qty = Decimal(str(quantity)).quantize(Decimal("0.0001"))
    if qty <= Decimal("0.0000"):
        return
    line = lines_by_artikl.get(artikl.id)
    if not line:
        line = {"artikl": artikl, "quantity": Decimal("0.0000")}
        lines_by_artikl[artikl.id] = line
    line["quantity"] = (Decimal(str(line["quantity"])) + qty).quantize(Decimal("0.0001"))


def _build_stock_out_lines_for_check_items(items: list[CheckItem]) -> tuple[list[dict], list[str]]:
    lines_by_artikl: dict[int, dict] = {}
    skipped: list[str] = []

    for item in items:
        if item.line_type != CheckItem.LineType.NORMAL:
            continue
        artikl = item.artikl
        if not artikl:
            skipped.append(f"Stavka {item.id} nema artikl.")
            continue

        qty = Decimal(str(item.quantity or "0.0000")).quantize(Decimal("0.0001"))
        if qty <= Decimal("0.0000"):
            continue

        if artikl.is_stock_item:
            _add_stock_line(lines_by_artikl, artikl=artikl, quantity=qty)
        else:
            normativ = Normativ.objects.filter(product=artikl, is_active=True).first()
            if normativ:
                for nitem in normativ.items.select_related("ingredient").all():
                    ingredient = nitem.ingredient
                    ing_qty = (Decimal(str(nitem.qty or "0.0000")) * qty).quantize(Decimal("0.0001"))
                    if not ingredient or ing_qty <= Decimal("0.0000"):
                        continue
                    _add_stock_line(lines_by_artikl, artikl=ingredient, quantity=ing_qty)
            else:
                skipped.append(f"Artikl {artikl} nije skladisni i nema normativ.")

        selections = item.modifier_selections.select_related("bundle_option__artikl").all()
        for selection in selections:
            if not selection.bundle_option_id:
                continue
            bundle = selection.bundle_option
            if not bundle.affects_stock:
                continue
            if Decimal(str(bundle.stock_ratio or "0.0000")) <= Decimal("0.0000"):
                continue
            stock_artikl = bundle.artikl
            if not stock_artikl or not stock_artikl.is_stock_item:
                skipped.append(
                    f"Bundle option {bundle.id} za item {item.id} nema validan skladisni artikl."
                )
                continue
            extra_qty = (
                qty
                * Decimal(str(selection.quantity or 1))
                * Decimal(str(bundle.stock_ratio or "0.0000"))
            ).quantize(Decimal("0.0001"))
            _add_stock_line(lines_by_artikl, artikl=stock_artikl, quantity=extra_qty)

    return list(lines_by_artikl.values()), skipped


def _allowed_layout_assignments_qs(user):
    return UserLayoutAccess.objects.select_related("layout").filter(
        user=user,
        is_active=True,
        layout__is_active=True,
    )


def _serialize_allowed_layouts(assignments):
    return [
        {
            "id": access.layout_id,
            "name": access.layout.name,
            "is_default": bool(access.is_default),
        }
        for access in assignments
    ]


def _resolve_layout_for_user(user, requested_layout_id: int | None):
    assignments = list(_allowed_layout_assignments_qs(user).order_by("-is_default", "layout__name", "layout_id"))
    if not assignments:
        return None, None, Response(
            {"detail": "Korisnik nema dodijeljen nijedan aktivan layout."},
            status=status.HTTP_409_CONFLICT,
        )

    if requested_layout_id is not None:
        for access in assignments:
            if access.layout_id == requested_layout_id:
                return access.layout, "selected", None
        return None, None, Response(
            {"detail": "Nemate pristup traženom layoutu."},
            status=status.HTTP_403_FORBIDDEN,
        )

    default_assignment = next((a for a in assignments if a.is_default), None)
    if default_assignment:
        return default_assignment.layout, "default", None
    return assignments[0].layout, "fallback", None


def _check_total_amount(check: Check) -> Decimal:
    total = Decimal("0.00")
    for item in check.items.all():
        if item.line_type != CheckItem.LineType.NORMAL:
            continue
        chargeable_qty = _chargeable_qty_for_item(item)
        if chargeable_qty <= Decimal("0.0000"):
            continue
        line_total = (chargeable_qty * Decimal(str(item.unit_price or "0.0000"))).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        total = (total + line_total).quantize(Decimal("0.01"))
    return total


def _check_paid_amount(check: Check) -> Decimal:
    paid_parts_total = (
        check.settlement_parts.filter(status=SettlementPart.Status.PAID)
        .aggregate(total=Sum("amount"))
        .get("total")
    )
    if paid_parts_total is not None:
        return Decimal(str(paid_parts_total)).quantize(Decimal("0.01"))
    paid_items_total = (
        check.items.filter(line_type=CheckItem.LineType.NORMAL)
        .aggregate(total=Sum("paid_amount"))
        .get("total")
    )
    return Decimal(str(paid_items_total or "0.00")).quantize(Decimal("0.01"))


def _check_remaining_amount(check: Check) -> Decimal:
    remaining = (_check_total_amount(check) - _check_paid_amount(check)).quantize(Decimal("0.01"))
    if remaining < Decimal("0.00"):
        return Decimal("0.00")
    return remaining


def _money_str(value: Decimal | str | int | float) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _qty_str(value: Decimal | str | int | float) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.0001")))


def _applied_qty_by_marker(*, check_id: int, item_id: int, line_type: str, marker_prefix: str) -> Decimal:
    marker = f"[{marker_prefix}_of:{item_id}]"
    applied_sum = (
        CheckItem.objects.filter(
            barion_check_id=check_id,
            line_type=line_type,
            note__startswith=marker,
        ).aggregate(total=Sum("quantity"))["total"]
        or Decimal("0.0000")
    )
    return abs(Decimal(str(applied_sum)).quantize(Decimal("0.0001")))


def _storno_applied_qty_for_item(*, check_id: int, item_id: int) -> Decimal:
    return _applied_qty_by_marker(
        check_id=check_id,
        item_id=item_id,
        line_type=CheckItem.LineType.STORNO,
        marker_prefix="storno",
    )


def _gratis_applied_qty_for_item(*, check_id: int, item_id: int) -> Decimal:
    return _applied_qty_by_marker(
        check_id=check_id,
        item_id=item_id,
        line_type=CheckItem.LineType.GRATIS,
        marker_prefix="gratis",
    )


def _otpis_applied_qty_for_item(*, check_id: int, item_id: int) -> Decimal:
    return _applied_qty_by_marker(
        check_id=check_id,
        item_id=item_id,
        line_type=CheckItem.LineType.OTPIS,
        marker_prefix="otpis",
    )


def _source_qty_for_item(*, check_id: int, item_id: int, stored_qty: Decimal | str | int | float) -> Decimal:
    # Source quantity must stay equal to stored NORMAL quantity.
    # Deductions are applied via STORNO/GRATIS/OTPIS/PAID against this base.
    return Decimal(str(stored_qty)).quantize(Decimal("0.0001"))


def _chargeable_qty_for_item(item: CheckItem) -> Decimal:
    if item.line_type != CheckItem.LineType.NORMAL:
        return Decimal("0.0000")
    source_qty = _source_qty_for_item(
        check_id=item.barion_check_id,
        item_id=item.id,
        stored_qty=item.quantity,
    )
    chargeable_qty = (
        source_qty
        - _storno_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
        - _gratis_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
        - _otpis_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
    ).quantize(Decimal("0.0001"))
    if chargeable_qty < Decimal("0.0000"):
        return Decimal("0.0000")
    return chargeable_qty


def _payment_remaining_for_item(item: CheckItem) -> tuple[Decimal, Decimal]:
    if item.line_type != CheckItem.LineType.NORMAL:
        return Decimal("0.0000"), Decimal("0.00")

    chargeable_qty = _chargeable_qty_for_item(item)
    remaining_qty = (chargeable_qty - item.paid_quantity).quantize(Decimal("0.0001"))
    if remaining_qty < Decimal("0.0000"):
        remaining_qty = Decimal("0.0000")

    unit_price = Decimal(str(item.unit_price or "0.0000"))
    if unit_price <= Decimal("0.0000") or remaining_qty <= Decimal("0.0000"):
        return remaining_qty, Decimal("0.00")

    remaining_amount = (remaining_qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if remaining_amount < Decimal("0.00"):
        remaining_amount = Decimal("0.00")
    return remaining_qty, remaining_amount


def _display_quantity_for_item(item: CheckItem) -> Decimal:
    if item.line_type != CheckItem.LineType.NORMAL:
        return Decimal(str(item.quantity)).quantize(Decimal("0.0001"))
    return _source_qty_for_item(
        check_id=item.barion_check_id,
        item_id=item.id,
        stored_qty=item.quantity,
    )


def _serialize_item_settlement_state(check: Check) -> list[dict]:
    rows = []
    for item in check.items.order_by("id"):
        remaining_qty, remaining_amount = _payment_remaining_for_item(item)
        if remaining_qty <= Decimal("0.0000") or remaining_amount <= Decimal("0.00"):
            continue
        rows.append(
            {
                "id": item.id,
                "artikl_id": item.artikl_id,
                "round_number": item.round_number,
                "sent_to_bar": item.sent_to_bar,
                "quantity": _qty_str(_display_quantity_for_item(item)),
                "paid_quantity": _qty_str(item.paid_quantity),
                "remaining_quantity": _qty_str(remaining_qty),
                "total_amount": _money_str(item.total_amount),
                "paid_amount": _money_str(item.paid_amount),
                "remaining_amount": _money_str(remaining_amount),
            }
        )
    return rows


def _serialize_round_state_items(check: Check) -> list[dict]:
    """
    UI-oriented quantity snapshot for Android round rendering.
    Keeps main NORMAL line as source quantity and exposes PAID aggregate as a virtual line.
    """
    rows: list[dict] = []
    items = (
        check.items.select_related("artikl")
        .filter(line_type=CheckItem.LineType.NORMAL)
        .order_by("round_number", "id")
    )
    for item in items:
        source_qty = _source_qty_for_item(
            check_id=item.barion_check_id,
            item_id=item.id,
            stored_qty=item.quantity,
        )
        sold_qty = Decimal(str(item.paid_quantity or "0.0000")).quantize(Decimal("0.0001"))
        storno_qty = _storno_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
        gratis_qty = _gratis_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
        otpis_qty = _otpis_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
        remaining_qty, _ = _payment_remaining_for_item(item)

        paid_line = None
        if sold_qty > Decimal("0.0000"):
            paid_total = (sold_qty * Decimal(str(item.unit_price or "0.0000"))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            paid_line = {
                "line_type": "PAID",
                "quantity": _qty_str(sold_qty),
                "unit_price": _qty_str(item.unit_price),
                "total_amount": _money_str(paid_total),
                "ui_color": "light_blue",
            }

        rows.append(
            {
                "item_id": item.id,
                "check_id": item.barion_check_id,
                "artikl_id": item.artikl_id,
                "artikl_name": item.artikl.name,
                "round_number": item.round_number,
                "source_quantity": _qty_str(source_qty),
                "sold_quantity": _qty_str(sold_qty),
                "storno_quantity": _qty_str(storno_qty),
                "gratis_quantity": _qty_str(gratis_qty),
                "otpis_quantity": _qty_str(otpis_qty),
                "remaining_quantity": _qty_str(remaining_qty),
                "strike_main": remaining_qty <= Decimal("0.0000"),
                "paid_line": paid_line,
            }
        )
    return rows


def _allocate_payment_to_items(*, check: Check, amount: Decimal, with_allocations: bool = False):
    """Allocates paid amount across items in ID order, updating paid_amount/paid_quantity."""
    remaining_to_allocate = Decimal(str(amount)).quantize(Decimal("0.01"))
    if remaining_to_allocate <= Decimal("0.00"):
        return (Decimal("0.00"), []) if with_allocations else Decimal("0.00")

    allocations: list[dict] = []

    for item in check.items.select_for_update().order_by("id"):
        if item.line_type != CheckItem.LineType.NORMAL:
            continue
        item_remaining_qty, item_remaining_amount = _payment_remaining_for_item(item)
        if item_remaining_amount <= Decimal("0.00") or item_remaining_qty <= Decimal("0.0000"):
            continue
        take = min(item_remaining_amount, remaining_to_allocate).quantize(Decimal("0.01"))
        if take <= Decimal("0.00"):
            continue
        prev_paid_qty = item.paid_quantity
        item.paid_amount = (item.paid_amount + take).quantize(Decimal("0.01"))
        if item.unit_price > Decimal("0.0000"):
            paid_qty = (item.paid_amount / item.unit_price).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            item.paid_quantity = min(paid_qty, item.quantity)
        else:
            item.paid_quantity = item.quantity if item.paid_amount >= item.total_amount else Decimal("0.0000")
        item.save(update_fields=["paid_amount", "paid_quantity", "updated_at"])
        allocated_qty = (item.paid_quantity - prev_paid_qty).quantize(Decimal("0.0001"))
        if allocated_qty > Decimal("0.0000"):
            allocations.append({"item": item, "quantity": allocated_qty})
        remaining_to_allocate = (remaining_to_allocate - take).quantize(Decimal("0.01"))
        if remaining_to_allocate <= Decimal("0.00"):
            break

    allocated_total = (Decimal(str(amount)).quantize(Decimal("0.01")) - max(remaining_to_allocate, Decimal("0.00"))).quantize(
        Decimal("0.01")
    )
    if with_allocations:
        return allocated_total, allocations
    return allocated_total


def _allocate_selected_items(*, selections: list[dict], with_allocations: bool = False):
    allocated_total = Decimal("0.00")
    allocations: list[dict] = []
    for row in selections:
        item = row["item"]
        quantity = Decimal(str(row["quantity"])).quantize(Decimal("0.0001"))
        if quantity <= Decimal("0.0000"):
            continue

        payment_remaining_qty, payment_remaining_amount = _payment_remaining_for_item(item)
        if quantity > payment_remaining_qty:
            raise serializers.ValidationError(f"Nema dovoljno remaining_quantity za item {item.id}.")

        line_amount = (quantity * item.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if line_amount > payment_remaining_amount:
            raise serializers.ValidationError(f"Nema dovoljno remaining_amount za item {item.id}.")

        item.paid_quantity = (item.paid_quantity + quantity).quantize(Decimal("0.0001"))
        item.paid_amount = (item.paid_amount + line_amount).quantize(Decimal("0.01"))
        item.save(update_fields=["paid_amount", "paid_quantity", "updated_at"])
        allocated_total = (allocated_total + line_amount).quantize(Decimal("0.01"))
        allocations.append({"item": item, "quantity": quantity})

    if with_allocations:
        return allocated_total, allocations
    return allocated_total


def _create_receipt_for_part_payment(*, part: SettlementPart, allocations: list[dict], user):
    if part.confirmed_receipt_id:
        return part.confirmed_receipt
    if not allocations:
        return None

    items_payload: list[dict] = []
    for row in allocations:
        item = row["item"]
        quantity = Decimal(str(row["quantity"])).quantize(Decimal("0.0001"))
        if quantity <= Decimal("0.0000"):
            continue
        items_payload.append(
            {
                "artikl": item.artikl_id,
                "quantity": quantity,
                "unit_price": item.unit_price,
            }
        )
    if not items_payload:
        return None

    payment_type = "card" if part.method == SettlementPart.Method.CARD else "cash"
    receipt = create_pos_receipt(
        office_code=os.getenv("FISCAL_OFFICE_CODE", "POS1"),
        device_code=os.getenv("FISCAL_DEVICE_CODE", "1"),
        payment_type=payment_type,
        items=items_payload,
        operator=user,
    )
    part.confirmed_receipt = receipt
    part.save(update_fields=["confirmed_receipt", "updated_at"])
    _save_receipt_pdf_to_media(receipt, user)
    return receipt


def _mark_all_items_paid(*, check: Check) -> None:
    for item in check.items.select_for_update().order_by("id"):
        if item.line_type != CheckItem.LineType.NORMAL:
            continue
        chargeable_qty = _chargeable_qty_for_item(item)
        chargeable_amount = (chargeable_qty * Decimal(str(item.unit_price or "0.0000"))).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        if item.paid_amount != chargeable_amount or item.paid_quantity != chargeable_qty:
            item.paid_amount = chargeable_amount
            item.paid_quantity = chargeable_qty
            item.save(update_fields=["paid_amount", "paid_quantity", "updated_at"])


def _serialize_settlement_parts(parts: list[SettlementPart]) -> list[dict]:
    def _method_display(part: SettlementPart) -> str:
        if part.method == SettlementPart.Method.CASH:
            return "Gotovina"
        brand = (part.card_brand or "").strip()
        masked_pan = (part.card_masked_pan or "").strip()
        if brand and masked_pan:
            return f"{brand}: {masked_pan}"
        if brand:
            return brand
        if masked_pan:
            return masked_pan
        return "Kartica"

    return [
        {
            "id": part.id,
            "method": part.method,
            "method_display": _method_display(part),
            "amount": _money_str(part.amount),
            "tip_amount": _money_str(part.tip_amount),
            "total_charged": _money_str(part.total_charged),
            "fiscal_amount": _money_str(part.fiscal_amount),
            "status": part.status,
            "provider": part.provider,
            "provider_ref": part.provider_ref,
            "card_masked_pan": part.card_masked_pan,
            "card_brand": part.card_brand,
            "card_type": part.card_type,
            "card_auth_code": part.card_auth_code,
            "card_rrn": part.card_rrn,
            "card_bank_id": part.card_bank_id,
            "card_aid": part.card_aid,
            "card_application_label": part.card_application_label,
            "provider_reference_number": part.provider_reference_number,
            "provider_tid": part.provider_tid,
            "provider_order_code": part.provider_order_code,
            "provider_short_order_code": part.provider_short_order_code,
            "provider_transaction_date": part.provider_transaction_date,
            "provider_payment_method": part.provider_payment_method,
            "provider_account_number": part.provider_account_number,
            "provider_verification_method": part.provider_verification_method,
            "provider_transaction_type_id": part.provider_transaction_type_id,
            "provider_transaction_event_id": part.provider_transaction_event_id,
            "provider_surcharge_amount": _money_str(part.provider_surcharge_amount),
            "provider_customer_trns": part.provider_customer_trns,
            "provider_status": part.provider_status,
            "provider_action": part.provider_action,
            "provider_message": part.provider_message,
            "provider_payload": part.provider_payload or {},
        }
        for part in parts
    ]


def _snapshot_part_sort_key(part: SettlementPart) -> tuple[int, int]:
    # Return mutable parts first so clients can safely pick "first matching" part.
    status_rank = {
        SettlementPart.Status.PREPARED: 0,
        SettlementPart.Status.FAILED: 1,
        SettlementPart.Status.PAID: 2,
    }
    return (status_rank.get(part.status, 99), part.id)


def _recalculate_check_settlement_status(check: Check) -> tuple[str, str]:
    check_total = _check_total_amount(check)
    parts = list(check.settlement_parts.all().order_by("id"))
    if not parts:
        check.settlement_status = Check.SettlementStatus.NONE
        check.payment_status = Check.PaymentStatus.UNPAID
        return check.settlement_status, check.payment_status

    allocated_total = sum((part.amount for part in parts), Decimal("0.00")).quantize(Decimal("0.01"))
    confirmed_total = _check_paid_amount(check)
    remaining_total = (check_total - confirmed_total).quantize(Decimal("0.01"))
    has_card_parts = any(part.method == SettlementPart.Method.CARD for part in parts)
    all_confirmed = all(part.status == SettlementPart.Status.PAID for part in parts)

    if confirmed_total <= 0:
        check.payment_status = Check.PaymentStatus.UNPAID
    elif remaining_total > Decimal("0.00"):
        check.payment_status = Check.PaymentStatus.PARTIAL
    else:
        check.payment_status = Check.PaymentStatus.PAID

    if all_confirmed and remaining_total <= Decimal("0.00"):
        check.settlement_status = Check.SettlementStatus.COMPLETE
    elif confirmed_total > Decimal("0.00") and has_card_parts:
        check.settlement_status = Check.SettlementStatus.CARD_CONFIRMED
    elif allocated_total >= remaining_total and remaining_total > Decimal("0.00"):
        check.settlement_status = Check.SettlementStatus.PREPARED
    else:
        check.settlement_status = Check.SettlementStatus.NONE

    return check.settlement_status, check.payment_status


def _sync_settlement_after_items_changed(*, check: Check, user=None) -> None:
    """Item mutations invalidate pending PREPARED parts; keep confirmed PAID history."""
    check.settlement_parts.filter(status=SettlementPart.Status.PREPARED).delete()
    snapshot = _build_settlement_snapshot(check)
    remaining_total = Decimal(str(snapshot["totals"]["remaining_total"]))
    if remaining_total <= Decimal("0.00") and check.status == Check.Status.OPEN:
        check.settlement_status = Check.SettlementStatus.COMPLETE
        check.payment_status = Check.PaymentStatus.PAID
        check.save(update_fields=["settlement_status", "payment_status", "updated_at"])
        _close_check_and_release_table(check=check, user=user)
        return
    _recalculate_check_settlement_status(check)
    check.save(update_fields=["settlement_status", "payment_status", "updated_at"])


def _build_settlement_snapshot(check: Check) -> dict:
    parts = sorted(list(check.settlement_parts.all()), key=_snapshot_part_sort_key)
    check_total = _check_total_amount(check)
    allocated_total = sum((part.amount for part in parts), Decimal("0.00")).quantize(Decimal("0.01"))
    confirmed_total = _check_paid_amount(check)
    remaining_total = (check_total - confirmed_total).quantize(Decimal("0.01"))
    has_unconfirmed_card = any(
        part.method == SettlementPart.Method.CARD and part.status != SettlementPart.Status.PAID
        for part in parts
    )
    can_settle_fully = remaining_total <= Decimal("0.00")
    return {
        "parts": _serialize_settlement_parts(parts),
        "totals": {
            "check_total": _money_str(check_total),
            "allocated_total": _money_str(allocated_total),
            "confirmed_total": _money_str(confirmed_total),
            "remaining_total": _money_str(remaining_total),
        },
        "actions": {
            "can_confirm_card": check.status == Check.Status.OPEN and has_unconfirmed_card,
            "can_issue_receipt": check.status == Check.Status.OPEN and not check.pos_receipt_id and can_settle_fully,
            "can_close_check": check.status == Check.Status.OPEN and can_settle_fully,
        },
        "items": _serialize_item_settlement_state(check),
    }


def _close_check_and_release_table(*, check: Check, user):
    check.status = Check.Status.CLOSED
    check.closed_at = timezone.now()
    check.closed_by = user
    check.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
    placements = list(
        LayoutTable.objects.select_for_update()
        .filter(table_id=check.table_id, is_enabled=True)
        .only("id")
    )
    if placements:
        TableState.objects.filter(
            layout_table_id__in=[p.id for p in placements],
            open_check_id=check.id,
        ).update(
            state=TableState.State.FREE,
            open_check_id=None,
            updated_by=user,
            updated_at=timezone.now(),
        )


def _save_receipt_pdf_to_media(receipt, user) -> str | None:
    from rest_framework.test import APIRequestFactory
    from pos.api import PosReceiptPrintView

    req = APIRequestFactory().get(f"/api/pos/receipts/{receipt.id}/print/")
    req.user = user
    response = PosReceiptPrintView().get(req, receipt.id)
    if getattr(response, "status_code", None) != 200:
        return None

    target_dir = Path(settings.MEDIA_ROOT) / "racuni"
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"pos-receipt-{receipt.id}.pdf"
    target_path = target_dir / filename
    pdf_bytes = response.content
    target_path.write_bytes(pdf_bytes)

    # Auto print only after successful fiscalization.
    if str(getattr(receipt, "status", "")).strip().lower() == "fiscalized":
        send_receipt_pdf_to_print_bridge(receipt=receipt, pdf_bytes=pdf_bytes)
    return f"{settings.MEDIA_URL}racuni/{filename}"


def _build_receipt_pdf_url(request, issued_receipt_id: int | None) -> str | None:
    if not issued_receipt_id:
        return None
    filename = f"pos-receipt-{issued_receipt_id}.pdf"
    relative_path = f"{settings.MEDIA_URL}racuni/{filename}"
    fs_path = Path(settings.MEDIA_ROOT) / "racuni" / filename
    if not fs_path.exists():
        return None
    return request.build_absolute_uri(relative_path)


def _collect_check_receipt_ids(check: Check) -> list[int]:
    receipt_ids: set[int] = set()
    part_receipts = (
        check.settlement_parts.exclude(confirmed_receipt_id__isnull=True)
        .values_list("confirmed_receipt_id", flat=True)
        .distinct()
    )
    receipt_ids.update(int(rid) for rid in part_receipts if rid)
    return sorted(receipt_ids)


def _serialize_check_receipts(request, check: Check) -> list[dict]:
    receipt_ids = _collect_check_receipt_ids(check)
    from pos.models import PosReceipt

    receipts_by_id = {
        receipt.id: receipt
        for receipt in PosReceipt.objects.filter(id__in=receipt_ids).only("id", "receipt_number", "total_amount", "status")
    }
    return [
        {
            "id": rid,
            "receipt_number": receipts_by_id[rid].receipt_number if rid in receipts_by_id else None,
            "total_amount": _money_str(receipts_by_id[rid].total_amount) if rid in receipts_by_id else None,
            "status": receipts_by_id[rid].status if rid in receipts_by_id else None,
            "pdf_url": _build_receipt_pdf_url(request, rid),
        }
        for rid in receipt_ids
    ]


def _primary_check_receipt_id(check: Check) -> int | None:
    receipt_ids = _collect_check_receipt_ids(check)
    if not receipt_ids:
        return None
    return receipt_ids[-1]


def _has_any_check_receipt(check: Check) -> bool:
    return bool(_collect_check_receipt_ids(check))


class PosRuntimeModeView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _serialize(runtime_mode: BarionRuntimeMode) -> dict:
        return {
            "active_mode": runtime_mode.active_mode,
            "updated_at": runtime_mode.updated_at,
            "updated_by_id": runtime_mode.updated_by_id,
        }

    @extend_schema(
        description="Returns backend runtime day/night mode used by POS clients.",
        responses={200: RuntimeModeSerializer},
    )
    def get(self, request):
        runtime_mode = BarionRuntimeMode.get_solo()
        return Response(self._serialize(runtime_mode))

    @extend_schema(
        description="Updates backend runtime day/night mode. Staff users only.",
        request=RuntimeModeUpdateRequestSerializer,
        responses={200: RuntimeModeSerializer, 400: ErrorSerializer, 403: ErrorSerializer},
    )
    def patch(self, request):
        if not request.user.is_staff:
            return Response({"detail": "Nemate dozvolu za izmjenu runtime moda."}, status=status.HTTP_403_FORBIDDEN)

        serializer = RuntimeModeUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updates = serializer.validated_data

        with transaction.atomic():
            runtime_mode = BarionRuntimeMode.objects.select_for_update().filter(pk=1).first() or BarionRuntimeMode.get_solo()
            runtime_mode.active_mode = updates["active_mode"]
            runtime_mode.updated_by = request.user
            try:
                runtime_mode.save()
            except ValidationError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(self._serialize(runtime_mode))


class PosAllowedLayoutsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            "Returns active layouts that current user is allowed to use. "
            "Production note: accesses are managed in Django admin at /admin/barion/userlayoutaccess/."
        ),
        responses={
            200: AllowedLayoutsResponseSerializer,
            409: OpenApiResponse(
                response=ErrorSerializer,
                description=(
                    "User has no active layout assignments. "
                    "Configure access in /admin/barion/userlayoutaccess/."
                ),
            ),
        },
    )
    def get(self, request):
        assignments = list(_allowed_layout_assignments_qs(request.user).order_by("-is_default", "layout__name", "layout_id"))
        if not assignments:
            return Response(
                {"detail": "Korisnik nema dodijeljen nijedan aktivan layout."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "layouts": _serialize_allowed_layouts(assignments)
            }
        )


class PosActiveLayoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            "Returns layout with zones and table placements for current user. "
            "Optional layout_id can select another assigned layout. "
            "Production note: user/layout access is managed in /admin/barion/userlayoutaccess/."
        ),
        parameters=[
            OpenApiParameter(
                name="layout_id",
                type=int,
                required=False,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="include_allowed",
                type=bool,
                required=False,
                location=OpenApiParameter.QUERY,
                description="If true/1, include all allowed active layouts for current user in `allowed_layouts`.",
            ),
        ],
        responses={
            200: ActiveLayoutResponseSerializer,
            304: None,
            400: OpenApiResponse(response=ErrorSerializer, description="layout_id must be numeric."),
            403: OpenApiResponse(response=ErrorSerializer, description="User has no access to requested layout."),
            409: OpenApiResponse(
                response=ErrorSerializer,
                description=(
                    "User has no active layout assignments. "
                    "Configure access in /admin/barion/userlayoutaccess/."
                ),
            ),
        },
    )
    def get(self, request):
        raw_layout_id = request.query_params.get("layout_id")
        include_allowed = str(request.query_params.get("include_allowed", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        layout_id = None
        if raw_layout_id not in (None, ""):
            try:
                layout_id = int(raw_layout_id)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "layout_id mora biti broj."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        layout, resolved_by, error_response = _resolve_layout_for_user(request.user, layout_id)
        if error_response:
            return error_response

        zones = list(
            layout.zones.order_by("order", "id").values("id", "name", "order")
        )

        placements = (
            LayoutTable.objects.select_related("table")
            .filter(layout=layout, is_enabled=True)
            .order_by("z_index", "id")
        )
        tables = [
            {
                "table_id": placement.table_id,
                "label": placement.table.label,
                "shape": placement.table.shape,
                "capacity": placement.table.capacity,
                "is_vip": placement.table.is_vip,
                "x": placement.x,
                "y": placement.y,
                "w": placement.w,
                "h": placement.h,
                "rotation": placement.rotation,
                "zone_id": placement.zone_id,
            }
            for placement in placements
        ]

        updated_at = layout.updated_at.isoformat()
        payload = {
            "resolved_by": resolved_by,
            "layout": {
                "id": layout.id,
                "name": layout.name,
                "updated_at": updated_at,
            },
            "zones": zones,
            "tables": tables,
        }
        if include_allowed:
            assignments = list(_allowed_layout_assignments_qs(request.user).order_by("-is_default", "layout__name", "layout_id"))
            payload["allowed_layouts"] = _serialize_allowed_layouts(assignments)

        signature = f"{layout.id}:{updated_at}:{len(zones)}:{len(tables)}"
        etag = quote_etag(hashlib.md5(signature.encode("utf-8")).hexdigest())
        if etag in parse_etags(request.META.get("HTTP_IF_NONE_MATCH", "")):
            response = Response(status=status.HTTP_304_NOT_MODIFIED)
        else:
            response = Response(payload)
        response["ETag"] = etag
        response["Cache-Control"] = "private, max-age=30"
        return response


class PosTableStatusView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            "Returns table statuses for a layout from TableState with FREE fallback. "
            "User must have access to requested layout via /admin/barion/userlayoutaccess/."
        ),
        parameters=[
            OpenApiParameter(
                name="layout_id",
                type=int,
                required=True,
                location=OpenApiParameter.QUERY,
            )
        ],
        responses={
            200: TableStatusItemSerializer(many=True),
            400: ErrorSerializer,
            404: ErrorSerializer,
        },
    )
    def get(self, request):
        raw_layout_id = request.query_params.get("layout_id")
        if not raw_layout_id:
            return Response(
                {"detail": "layout_id je obavezan query parametar."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            layout_id = int(raw_layout_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "layout_id mora biti broj."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        has_access = UserLayoutAccess.objects.filter(
            user=request.user,
            is_active=True,
            layout_id=layout_id,
            layout__is_active=True,
        ).exists()
        if not has_access:
            if Layout.objects.filter(id=layout_id).exists():
                return Response({"detail": "Nemate pristup traženom layoutu."}, status=status.HTTP_403_FORBIDDEN)
            return Response({"detail": "Layout ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        placements = list(
            LayoutTable.objects.filter(layout_id=layout_id, is_enabled=True)
            .only("id", "table_id")
            .order_by("z_index", "id")
        )
        if not placements:
            return Response([])

        states_by_layout_table = {
            row["layout_table_id"]: row
            for row in TableState.objects.filter(layout_table_id__in=[p.id for p in placements])
            .values("layout_table_id", "state", "open_check_id")
        }

        payload = []
        for placement in placements:
            state_row = states_by_layout_table.get(placement.id)
            if state_row:
                payload.append(
                    {
                        "table_id": placement.table_id,
                        "open_check_id": state_row["open_check_id"],
                        "status": state_row["state"],
                    }
                )
            else:
                payload.append(
                    {
                        "table_id": placement.table_id,
                        "open_check_id": None,
                        "status": TableState.State.FREE,
                    }
                )
        return Response(payload)


class PosChecksView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _serialize(check: Check) -> dict:
        return {
            "id": check.id,
            "table_id": check.table_id,
            "status": check.status,
            "settlement_status": check.settlement_status,
            "payment_status": check.payment_status,
            "pos_receipt_id": check.pos_receipt_id,
            "opened_at": check.opened_at.isoformat() if check.opened_at else None,
            "closed_at": check.closed_at.isoformat() if check.closed_at else None,
        }

    @extend_schema(
        description="Returns currently open check for a table.",
        parameters=[
            OpenApiParameter(
                name="table_id",
                type=int,
                required=True,
                location=OpenApiParameter.QUERY,
            )
        ],
        responses={
            200: CheckSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
        },
    )
    def get(self, request):
        raw_table_id = request.query_params.get("table_id")
        if not raw_table_id:
            return Response(
                {"detail": "table_id je obavezan query parametar."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            table_id = int(raw_table_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "table_id mora biti broj."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        check = (
            Check.objects.filter(table_id=table_id, status=Check.Status.OPEN)
            .order_by("-opened_at")
            .first()
        )
        if not check:
            return Response({"detail": "Otvoreni check ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        return Response(self._serialize(check))

    @extend_schema(
        description="Creates an OPEN check for table or returns existing OPEN check.",
        request=CreateCheckRequestSerializer,
        responses={
            200: CreateCheckResponseSerializer,
            201: CreateCheckResponseSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
        },
    )
    def post(self, request):
        raw_table_id = request.data.get("table_id")
        if raw_table_id is None:
            return Response({"detail": "table_id je obavezan."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            table_id = int(raw_table_id)
        except (TypeError, ValueError):
            return Response({"detail": "table_id mora biti broj."}, status=status.HTTP_400_BAD_REQUEST)

        if not Table.objects.filter(id=table_id).exists():
            return Response({"detail": "Table ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            check = (
                Check.objects.select_for_update()
                .filter(table_id=table_id, status=Check.Status.OPEN)
                .order_by("-opened_at")
                .first()
            )
            created = False
            if not check:
                try:
                    check = Check.objects.create(
                        table_id=table_id,
                        status=Check.Status.OPEN,
                        opened_by=request.user,
                    )
                    created = True
                except IntegrityError:
                    # Concurrent request may have created OPEN check first.
                    check = (
                        Check.objects.select_for_update()
                        .filter(table_id=table_id, status=Check.Status.OPEN)
                        .order_by("-opened_at")
                        .first()
                    )
                    if not check:
                        raise

            placements = list(
                LayoutTable.objects.select_for_update()
                .filter(table_id=table_id, is_enabled=True)
                .only("id")
            )
            for placement in placements:
                TableState.objects.update_or_create(
                    layout_table=placement,
                    defaults={
                        "state": TableState.State.FREE,
                        "open_check_id": None,
                        "updated_by": request.user,
                    },
                )

        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(
            {"created": created, "check": self._serialize(check)},
            status=response_status,
        )


class PosCheckCloseView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Closes an OPEN check and updates TableState to FREE.",
        responses={
            200: CloseCheckResponseSerializer,
            404: ErrorSerializer,
            409: ErrorSerializer,
        },
    )
    def post(self, request, check_id: int):
        with transaction.atomic():
            check = (
                Check.objects.select_for_update()
                .filter(id=check_id)
                .select_related("table")
                .first()
            )
            if not check:
                return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if check.status == Check.Status.CLOSED:
                return Response({"detail": "Check je već zatvoren."}, status=status.HTTP_409_CONFLICT)
            part_qs = check.settlement_parts.select_for_update().all()
            if part_qs.exists() and part_qs.exclude(status=SettlementPart.Status.PAID).exists():
                return Response(
                    {"detail": "Check nije moguće zatvoriti dok svi settlement partovi nisu PAID."},
                    status=status.HTTP_409_CONFLICT,
                )

            check.status = Check.Status.CLOSED
            check.closed_at = timezone.now()
            check.closed_by = request.user
            check.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])

            placements = list(
                LayoutTable.objects.select_for_update()
                .filter(table_id=check.table_id, is_enabled=True)
                .only("id")
            )
            if placements:
                TableState.objects.filter(
                    layout_table_id__in=[p.id for p in placements],
                    open_check_id=check.id,
                ).update(
                    state=TableState.State.FREE,
                    open_check_id=None,
                    updated_by=request.user,
                    updated_at=timezone.now(),
                )

        return Response(
            {
                "id": check.id,
                "status": check.status,
                "table_id": check.table_id,
                "closed_at": check.closed_at.isoformat() if check.closed_at else None,
            }
        )


class PosCheckSendToBarView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _send_ticket_to_printer(ticket: dict) -> None:
        if os.getenv("BARION_BAR_PRINTER_FAIL", "false").lower() in {"1", "true", "yes", "on"}:
            raise RuntimeError("Greška pri slanju na bar printer.")
        send_bar_ticket_to_print_bridge(ticket)

    @staticmethod
    def _build_ticket_payload(*, request, check: Check, round_number: int, sent_items: list[CheckItem], sent_at):
        waiter_name = request.user.get_full_name().strip() or request.user.username
        profile = getattr(request.user, "pos_profile", None)
        device_id = str(getattr(profile, "registered_device_id", "") or "").strip()

        def _modifier_lines_for_item(item: CheckItem) -> list[str]:
            lines: list[str] = []
            for row in _serialize_check_item_modifiers(item):
                qty = int(row.get("quantity") or 1)
                name = str(row.get("option_name") or "").strip()
                if not name:
                    continue
                lines.append(f"{name} x{qty}" if qty > 1 else name)
            return lines

        def _compose_bar_note(*, note: str, modifier_lines: list[str]) -> str:
            base_note = str(note or "").strip()
            if not modifier_lines:
                return base_note
            mods_text = ", ".join(modifier_lines)
            if base_note:
                return f"{mods_text} | Napomena: {base_note}"
            return mods_text

        return {
            "venue_name": os.getenv("BARION_VENUE_NAME", "Mozart"),
            "table_label": check.table.label,
            "check_id": check.id,
            "device_id": device_id,
            "round_number": round_number,
            "waiter": waiter_name,
            "sent_at": sent_at.isoformat(),
            "items": [
                {
                    "id": item.id,
                    "artikl_id": item.artikl_id,
                    "artikl_name": item.artikl.name,
                    "quantity": item.quantity,
                    "note": _compose_bar_note(
                        note=item.note,
                        modifier_lines=_modifier_lines_for_item(item),
                    ),
                    "note_raw": item.note,
                    "modifiers": _serialize_check_item_modifiers(item),
                    "modifier_lines": _modifier_lines_for_item(item),
                }
                for item in sent_items
            ],
        }

    @extend_schema(
        description=(
            "Pošalji na šank: uzima samo nove stavke (sent_to_bar=false), "
            "dodjeljuje im sljedeći round_number i šalje bar ticket za tu rundu."
        ),
        request=None,
        responses={
            200: OpenApiResponse(
                response=SendCheckToBarResponseSerializer,
                description="Runda poslana na šank; printanje je best-effort i može vratiti upozorenje.",
            ),
            404: OpenApiResponse(response=ErrorSerializer, description="Check ne postoji."),
            409: OpenApiResponse(response=ErrorSerializer, description="Nema novih stavki ili check nije OPEN."),
        },
        examples=[
            OpenApiExample(
                "Request",
                summary="Nema body-a",
                value={},
                request_only=True,
            ),
            OpenApiExample(
                "Success 200",
                value={
                    "check_id": 123,
                    "round_number": 3,
                    "sent_items_count": 2,
                    "sent_at": "2026-02-23T12:34:56+01:00",
                    "printed": True,
                    "print_error": "",
                    "ticket": {
                        "venue_name": "Mozart",
                        "table_label": "T12",
                        "check_id": 123,
                        "round_number": 3,
                        "waiter": "ivan",
                        "sent_at": "2026-02-23T12:34:56+01:00",
                            "items": [
                            {"id": 9001, "artikl_id": 501, "artikl_name": "Gin tonic", "quantity": "1.0000", "note": ""},
                            {"id": 9002, "artikl_id": 502, "artikl_name": "Rum cola", "quantity": "2.0000", "note": "bez leda"},
                        ],
                    },
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                "No new items 409",
                value={"detail": "Nema novih stavki za slanje na šank."},
                response_only=True,
                status_codes=["409"],
            ),
            OpenApiExample(
                "Printer warning 200",
                value={
                    "check_id": 123,
                    "round_number": 3,
                    "sent_items_count": 2,
                    "sent_at": "2026-02-23T12:34:56+01:00",
                    "printed": False,
                    "print_error": "Greška pri slanju na bar printer.",
                    "ticket": {
                        "venue_name": "Mozart",
                        "table_label": "T12",
                        "check_id": 123,
                        "round_number": 3,
                        "waiter": "ivan",
                        "sent_at": "2026-02-23T12:34:56+01:00",
                        "items": [
                            {"id": 9001, "artikl_id": 501, "artikl_name": "Gin tonic", "quantity": "1.0000", "note": ""}
                        ],
                    },
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def post(self, request, check_id: int):
        with transaction.atomic():
            check = (
                Check.objects.select_for_update()
                .filter(id=check_id)
                .select_related("table")
                .first()
            )
            if not check:
                return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if check.status != Check.Status.OPEN:
                return Response(
                    {"detail": "Check nije otvoren pa nije moguće poslati rundu na šank."},
                    status=status.HTTP_409_CONFLICT,
                )

            unsent_items = list(
                CheckItem.objects.select_for_update()
                .select_related("artikl")
                .prefetch_related(
                    "modifier_selections__group",
                    "modifier_selections__option",
                    "modifier_selections__bundle_option__artikl",
                )
                .filter(barion_check=check, sent_to_bar=False, line_type=CheckItem.LineType.NORMAL)
                .order_by("id")
            )
            if not unsent_items:
                return Response(
                    {"detail": "Nema novih stavki za slanje na šank."},
                    status=status.HTTP_409_CONFLICT,
                )

            max_round = (
                CheckItem.objects.filter(barion_check=check, round_number__isnull=False)
                .aggregate(max_round=Max("round_number"))
                .get("max_round")
            )
            next_round = (max_round or 0) + 1
            sent_at = timezone.now()

            for item in unsent_items:
                item.round_number = next_round
                item.sent_to_bar = True
                item.sent_at = sent_at
                item.save(update_fields=["round_number", "sent_to_bar", "sent_at", "updated_at"])

            ticket = self._build_ticket_payload(
                request=request,
                check=check,
                round_number=next_round,
                sent_items=unsent_items,
                sent_at=sent_at,
            )

        printed = True
        print_error = ""
        try:
            self._send_ticket_to_printer(ticket)
        except RuntimeError as exc:
            printed = False
            print_error = str(exc)

        return Response(
            {
                "check_id": check.id,
                "round_number": next_round,
                "sent_items_count": len(unsent_items),
                "sent_at": sent_at.isoformat(),
                "ticket": ticket,
                "printed": printed,
                "print_error": print_error,
            }
        )


class PosCheckSettlementStateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            "Returns settlement snapshot for polling/sync on Android clients. "
            "Snapshot includes parts, totals and allowed actions."
        ),
        responses={
            200: SettlementStateResponseSerializer,
            404: ErrorSerializer,
        },
        examples=[
            OpenApiExample(
                "Settlement state",
                value={
                    "check_id": 123,
                    "check_status": "OPEN",
                    "settlement_status": "CARD_CONFIRMED",
                    "payment_status": "PARTIAL",
                    "pos_receipt_id": None,
                    "pos_receipt_ids": [501, 502],
                    "receipts": [
                        {"id": 501, "pdf_url": "https://mozart.sibenik1983.hr/media/racuni/pos-receipt-501.pdf"},
                        {"id": 502, "pdf_url": "https://mozart.sibenik1983.hr/media/racuni/pos-receipt-502.pdf"},
                    ],
                    "parts": [
                        {
                            "id": 1,
                            "method": "CARD",
                            "amount": "20.00",
                            "tip_amount": "2.00",
                            "total_charged": "22.00",
                            "fiscal_amount": "22.00",
                            "status": "PAID",
                            "provider": "VIVA",
                            "provider_ref": "VIVA-REF-001",
                        },
                        {
                            "id": 2,
                            "method": "CASH",
                            "amount": "30.00",
                            "tip_amount": "0.00",
                            "total_charged": "30.00",
                            "fiscal_amount": "30.00",
                            "status": "PREPARED",
                            "provider": "",
                            "provider_ref": "",
                        },
                    ],
                    "totals": {
                        "check_total": "50.00",
                        "allocated_total": "50.00",
                        "confirmed_total": "20.00",
                        "remaining_total": "30.00",
                    },
                    "actions": {
                        "can_confirm_card": False,
                        "can_issue_receipt": False,
                        "can_close_check": False,
                    },
                    "updated_at": "2026-02-24T14:30:00Z",
                },
                response_only=True,
            ),
        ],
    )
    def get(self, request, check_id: int):
        check = Check.objects.filter(id=check_id).first()
        if not check:
            return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)
        snapshot = _build_settlement_snapshot(check)
        return Response(
            {
                "check_id": check.id,
                "check_status": check.status,
                "settlement_status": check.settlement_status,
                "payment_status": check.payment_status,
                "pos_receipt_id": check.pos_receipt_id,
                "pos_receipt_ids": _collect_check_receipt_ids(check),
                "receipts": _serialize_check_receipts(request, check),
                "issued_receipt_id": check.pos_receipt_id,
                "receipt_pdf_url": _build_receipt_pdf_url(request, check.pos_receipt_id),
                "parts": snapshot["parts"],
                "items": snapshot.get("items", []),
                "totals": snapshot["totals"],
                "actions": snapshot["actions"],
                "updated_at": check.updated_at.isoformat(),
            }
        )


class PosCheckRoundStateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            "Returns round UI quantity snapshot for Android clients. "
            "Includes virtual PAID line (ui_color=light_blue) and strike_main flag "
            "which becomes true only when remaining_quantity is 0."
        ),
        responses={
            200: RoundStateResponseSerializer,
            404: ErrorSerializer,
        },
    )
    def get(self, request, check_id: int):
        check = Check.objects.filter(id=check_id).first()
        if not check:
            return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "check_id": check.id,
                "status": check.status,
                "items": _serialize_round_state_items(check),
                "updated_at": check.updated_at.isoformat(),
            }
        )


class PosCheckReceiptFiscalizeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            "Fiscalizes a POS receipt linked to a Barion check. "
            "Intended for Android button action on paid receipt rows."
        ),
        responses={
            200: serializers.JSONField(),
            404: ErrorSerializer,
            409: ErrorSerializer,
            428: ErrorSerializer,
        },
    )
    def post(self, request, check_id: int, receipt_id: int):
        ok, remaining = is_recent_pin_verified(request.user)
        if not ok:
            return Response(
                {
                    "detail": "Potrebna je PIN potvrda za ovu akciju.",
                    "pin_verify_required": True,
                    "pin_verify_endpoint": "/api/pos/pin/verify/",
                    "pin_verify_ttl_seconds": pin_verify_ttl_seconds(),
                    "pin_verify_remaining_seconds": remaining,
                },
                status=428,
            )

        check = Check.objects.filter(id=check_id).first()
        if not check:
            return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        if receipt_id not in _collect_check_receipt_ids(check):
            return Response(
                {"detail": "Račun nije povezan s ovim checkom."},
                status=status.HTTP_404_NOT_FOUND,
            )

        from pos.models import PosReceipt

        receipt = PosReceipt.objects.filter(id=receipt_id).first()
        if not receipt:
            return Response({"detail": "Račun ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        try:
            if receipt.status != PosReceipt.Status.FISCALIZED:
                receipt = fiscalize_pos_receipt(receipt)
                action = "fiscalized"
            else:
                action = "already_fiscalized"
            _save_receipt_pdf_to_media(receipt, request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "check_id": check.id,
                "receipt_id": receipt.id,
                "action": action,
                "status": receipt.status,
                "receipt_number": receipt.receipt_number,
                "total_amount": _money_str(receipt.total_amount),
                "zki": receipt.zki,
                "jir": receipt.jir,
                "qr": receipt.qr_payload,
                "pdf_url": _build_receipt_pdf_url(request, receipt.id),
                "receipts": _serialize_check_receipts(request, check),
            }
        )


class PosCheckPrepareSettlementView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            "Prepares split settlement for an OPEN check. "
            "Validates allocation sum and persists settlement parts."
        ),
        request=PrepareSettlementRequestSerializer,
        responses={
            200: PrepareSettlementResponseSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
            409: ErrorSerializer,
        },
    )
    def post(self, request, check_id: int):
        raw_payload = request.data if isinstance(request.data, dict) else {}
        serializer = PrepareSettlementRequestSerializer(data=raw_payload)
        serializer.is_valid(raise_exception=True)
        payload_parts = serializer.validated_data.get("parts", [])
        ready_for_issue = bool(serializer.validated_data.get("ready_for_issue", False))

        with transaction.atomic():
            check = Check.objects.select_for_update().filter(id=check_id).first()
            if not check:
                return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if check.status != Check.Status.OPEN:
                return Response({"detail": "Settlement je moguće pripremiti samo za OPEN check."}, status=409)

            existing_parts = list(check.settlement_parts.select_for_update().order_by("id"))
            paid_parts = [part for part in existing_parts if part.status == SettlementPart.Status.PAID]
            mutable_parts = [part for part in existing_parts if part.status != SettlementPart.Status.PAID]

            check_total = _check_remaining_amount(check)
            if not payload_parts:
                return Response({"detail": "parts je obavezan i ne smije biti prazan."}, status=status.HTTP_400_BAD_REQUEST)
            if check_total <= Decimal("0.00"):
                return Response({"detail": "Check nema iznos za naplatu."}, status=status.HTTP_400_BAD_REQUEST)

            normalized_parts = []
            for part in payload_parts:
                method = str(part["method"]).upper()
                amount = Decimal(str(part["amount"])).quantize(Decimal("0.01"))
                tip_amount = Decimal(str(part.get("tip_amount", "0.00"))).quantize(Decimal("0.01"))
                if method == SettlementPart.Method.CASH and tip_amount != Decimal("0.00"):
                    return Response({"detail": "tip_amount je dozvoljen samo za CARD method."}, status=400)
                if method == SettlementPart.Method.CARD and tip_amount > amount:
                    return Response({"detail": "tip_amount ne može biti veći od amount."}, status=400)
                total_charged = (amount + tip_amount) if method == SettlementPart.Method.CARD else amount
                fiscal_amount = total_charged
                normalized_parts.append(
                    {
                        "method": method,
                        "amount": amount,
                        "tip_amount": tip_amount,
                        "total_charged": total_charged.quantize(Decimal("0.01")),
                        "fiscal_amount": fiscal_amount.quantize(Decimal("0.01")),
                    }
                )

            allocated_total = sum((part["amount"] for part in normalized_parts), Decimal("0.00")).quantize(Decimal("0.01"))
            # Android "kompletna naplata" može poslati stari/full iznos checka.
            # Ako je poslan samo jedan part, sigurnije ga je normalizirati
            # na trenutno preostali iznos umjesto vraćanja 400.
            if allocated_total > check_total and len(normalized_parts) == 1:
                part = normalized_parts[0]
                part["amount"] = check_total
                if part["method"] == SettlementPart.Method.CARD and part["tip_amount"] > check_total:
                    return Response(
                        {"detail": "tip_amount ne može biti veći od amount nakon normalizacije preostalog iznosa."},
                        status=400,
                    )
                part["total_charged"] = (
                    (check_total + part["tip_amount"]) if part["method"] == SettlementPart.Method.CARD else check_total
                ).quantize(Decimal("0.01"))
                part["fiscal_amount"] = part["total_charged"]
                allocated_total = check_total
            if allocated_total != check_total:
                return Response(
                    {
                        "detail": "Zbroj settlement parts mora biti jednak totalu checka.",
                        "check_total": str(check_total),
                        "allocated_total": str(allocated_total),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            current_signature = [
                (part.method, part.amount, part.tip_amount, part.total_charged, part.fiscal_amount)
                for part in mutable_parts
            ]
            next_signature = [
                (part["method"], part["amount"], part["tip_amount"], part["total_charged"], part["fiscal_amount"])
                for part in normalized_parts
            ]
            if current_signature != next_signature:
                if mutable_parts:
                    check.settlement_parts.filter(id__in=[part.id for part in mutable_parts]).delete()
                SettlementPart.objects.bulk_create(
                    [
                        SettlementPart(
                            barion_check=check,
                            method=part["method"],
                            amount=part["amount"],
                            tip_amount=part["tip_amount"],
                            total_charged=part["total_charged"],
                            fiscal_amount=part["fiscal_amount"],
                        )
                        for part in normalized_parts
                    ]
                )

            refreshed_parts = list(check.settlement_parts.order_by("id"))
            has_only_cash_no_tip = (
                all(part.method == SettlementPart.Method.CASH for part in refreshed_parts)
                and all(part.tip_amount == Decimal("0.00") for part in refreshed_parts)
            )
            check.settlement_status = (
                Check.SettlementStatus.READY_FOR_ISSUE if (ready_for_issue and has_only_cash_no_tip) else Check.SettlementStatus.PREPARED
            )
            check.payment_status = Check.PaymentStatus.PARTIAL if _check_paid_amount(check) > Decimal("0.00") else Check.PaymentStatus.UNPAID
            check.save(update_fields=["settlement_status", "payment_status", "updated_at"])

            snapshot = _build_settlement_snapshot(check)
            response_payload = {
                "check_id": check.id,
                "settlement_status": check.settlement_status,
                "payment_status": check.payment_status,
                "parts": snapshot["parts"],
                "totals": snapshot["totals"],
                "actions": snapshot["actions"],
            }
            return Response(response_payload)


class PosSettlementPartPayCashView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Pays a single CASH settlement part.",
        request=SettlementPartPayCashRequestSerializer,
        responses={200: serializers.JSONField(), 400: ErrorSerializer, 404: ErrorSerializer, 409: ErrorSerializer},
    )
    def post(self, request, check_id: int, part_id: int):
        raw_payload = request.data if isinstance(request.data, dict) else {}
        raw_items = raw_payload.get("items") if isinstance(raw_payload.get("items"), list) else []
        normalized_items = []
        for row in raw_items:
            if not isinstance(row, dict):
                continue
            item_id = row.get("item_id", row.get("id"))
            normalized_items.append(
                {
                    "item_id": item_id,
                    "quantity": row.get("quantity"),
                }
            )

        serializer = SettlementPartPayCashRequestSerializer(
            data={
                "amount": raw_payload.get("amount"),
                "items": normalized_items,
            }
        )
        serializer.is_valid(raise_exception=True)
        requested_amount = serializer.validated_data.get("amount")
        requested_items = serializer.validated_data.get("items") or []

        with transaction.atomic():
            check = Check.objects.select_for_update().filter(id=check_id).first()
            if not check:
                return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if check.status != Check.Status.OPEN:
                return Response({"detail": "Naplata je moguća samo za OPEN check."}, status=status.HTTP_409_CONFLICT)

            part = check.settlement_parts.select_for_update().filter(id=part_id).first()
            if not part:
                return Response({"detail": "Settlement part ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if part.method != SettlementPart.Method.CASH:
                return Response({"detail": "Part nije CASH."}, status=status.HTTP_409_CONFLICT)

            if part.status == SettlementPart.Status.PAID:
                snapshot = _build_settlement_snapshot(check)
                return Response(
                    {
                        "check_id": check.id,
                        "part_id": part.id,
                        "action": "already_paid",
                        "part_status": part.status,
                        "parts": snapshot["parts"],
                        "totals": snapshot["totals"],
                        "actions": snapshot["actions"],
                        "issued_receipt_id": check.pos_receipt_id,
                        "pos_receipt_ids": _collect_check_receipt_ids(check),
                        "receipt_pdf_url": _build_receipt_pdf_url(request, check.pos_receipt_id),
                    }
                )

            selected_items = []
            if requested_items:
                item_ids = [int(row["item_id"]) for row in requested_items]
                if len(set(item_ids)) != len(item_ids):
                    return Response(
                        {"detail": "items ne smiju sadržavati duplikate item_id."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                item_map = {
                    item.id: item
                    for item in check.items.select_for_update().filter(id__in=item_ids).order_by("id")
                }
                if len(item_map) != len(item_ids):
                    return Response(
                        {"detail": "Jedan ili više item_id ne pripadaju checku."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                selected_total = Decimal("0.00")
                for row in requested_items:
                    item = item_map[int(row["item_id"])]
                    if item.line_type != CheckItem.LineType.NORMAL:
                        return Response(
                            {"detail": f"Item {item.id} nije naplativ (line_type={item.line_type})."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    qty = Decimal(str(row["quantity"])).quantize(Decimal("0.0001"))
                    remaining_qty, remaining_amount_item = _payment_remaining_for_item(item)
                    if qty > remaining_qty:
                        return Response(
                            {"detail": f"Tražena quantity je veća od remaining_quantity za item {item.id}."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    line_amount = (qty * item.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if line_amount > remaining_amount_item:
                        return Response(
                            {"detail": f"Traženi iznos je veći od remaining_amount za item {item.id}."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    selected_items.append({"item": item, "quantity": qty})
                    selected_total = (selected_total + line_amount).quantize(Decimal("0.01"))
                normalized_requested = selected_total
                if requested_amount is not None:
                    normalized_amount = Decimal(str(requested_amount)).quantize(Decimal("0.01"))
                    if normalized_amount != normalized_requested:
                        return Response(
                            {"detail": "amount mora biti jednak zbroju odabranih items."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
            elif requested_amount is not None:
                normalized_requested = Decimal(str(requested_amount)).quantize(Decimal("0.01"))
            else:
                normalized_requested = part.amount

            if normalized_requested <= Decimal("0.00"):
                return Response(
                    {"detail": "amount mora biti > 0."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if normalized_requested > part.amount:
                return Response(
                    {"detail": "amount ne može biti veći od amount-a settlement parta."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if normalized_requested < part.amount:
                # Split part into paid + remaining.
                remaining_amount = (part.amount - normalized_requested).quantize(Decimal("0.01"))
                part.amount = remaining_amount
                part.total_charged = remaining_amount
                part.fiscal_amount = remaining_amount
                part.save(update_fields=["amount", "total_charged", "fiscal_amount", "updated_at"])
                paid_part = SettlementPart.objects.create(
                    barion_check=check,
                    method=SettlementPart.Method.CASH,
                    amount=normalized_requested,
                    tip_amount=Decimal("0.00"),
                    status=SettlementPart.Status.PAID,
                    confirmed_at=timezone.now(),
                    confirmed_by=request.user,
                )
                allocated, allocations = (
                    _allocate_selected_items(selections=selected_items, with_allocations=True)
                    if selected_items
                    else _allocate_payment_to_items(check=check, amount=normalized_requested, with_allocations=True)
                )
                if allocated != normalized_requested:
                    paid_part.amount = allocated
                    paid_part.total_charged = allocated
                    paid_part.fiscal_amount = allocated
                    paid_part.save(update_fields=["amount", "total_charged", "fiscal_amount", "updated_at"])
                issued_receipt = _create_receipt_for_part_payment(part=paid_part, allocations=allocations, user=request.user)
                _recalculate_check_settlement_status(check)
                check.save(update_fields=["settlement_status", "payment_status", "updated_at"])
                snapshot = _build_settlement_snapshot(check)
                return Response(
                    {
                        "check_id": check.id,
                        "part_id": paid_part.id,
                        "action": "paid",
                        "part_status": paid_part.status,
                        "parts": snapshot["parts"],
                        "totals": snapshot["totals"],
                        "actions": snapshot["actions"],
                        "issued_receipt_id": issued_receipt.id if issued_receipt else check.pos_receipt_id,
                        "pos_receipt_ids": _collect_check_receipt_ids(check),
                        "receipt_pdf_url": _build_receipt_pdf_url(
                            request, issued_receipt.id if issued_receipt else check.pos_receipt_id
                        ),
                    }
                )

            part.status = SettlementPart.Status.PAID
            part.confirmed_at = timezone.now()
            part.confirmed_by = request.user
            part.save(update_fields=["status", "confirmed_at", "confirmed_by", "updated_at"])
            if selected_items:
                _, allocations = _allocate_selected_items(selections=selected_items, with_allocations=True)
            else:
                _, allocations = _allocate_payment_to_items(check=check, amount=part.amount, with_allocations=True)
            issued_receipt = _create_receipt_for_part_payment(part=part, allocations=allocations, user=request.user)

            _recalculate_check_settlement_status(check)
            check.save(update_fields=["settlement_status", "payment_status", "updated_at"])
            snapshot = _build_settlement_snapshot(check)
            issued_receipt_id = issued_receipt.id if issued_receipt else check.pos_receipt_id
            receipt_pdf_url = _build_receipt_pdf_url(request, issued_receipt_id)

            # Do not auto-close on full CASH payment.
            # Closing is explicit via POST /api/pos/checks/{check_id}/close/ (Free button).
            if Decimal(str(snapshot["totals"]["remaining_total"])) <= Decimal("0.00"):
                check.settlement_status = Check.SettlementStatus.COMPLETE
                check.payment_status = Check.PaymentStatus.PAID
                check.save(update_fields=["settlement_status", "payment_status", "updated_at"])
                receipt_pdf_url = _build_receipt_pdf_url(request, issued_receipt_id)
                snapshot = _build_settlement_snapshot(check)

            return Response(
                {
                    "check_id": check.id,
                    "part_id": part.id,
                    "action": "paid",
                    "part_status": part.status,
                    "parts": snapshot["parts"],
                    "totals": snapshot["totals"],
                    "actions": snapshot["actions"],
                    "issued_receipt_id": issued_receipt_id,
                    "pos_receipt_ids": _collect_check_receipt_ids(check),
                    "receipt_pdf_url": receipt_pdf_url,
                }
            )


class PosSettlementPartPayCardConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Confirms/declines a single CARD settlement part. Failed part is retryable.",
        request=SettlementPartPayCardConfirmRequestSerializer,
        responses={200: serializers.JSONField(), 400: ErrorSerializer, 404: ErrorSerializer, 409: ErrorSerializer},
    )
    def post(self, request, check_id: int, part_id: int):
        serializer = SettlementPartPayCardConfirmRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approved = bool(serializer.validated_data["approved"])
        requested_amount = serializer.validated_data.get("amount")
        requested_tip_amount = serializer.validated_data.get("tip_amount")
        provider = str(serializer.validated_data.get("provider", "")).strip().upper()
        external_txn_id = str(serializer.validated_data.get("external_txn_id", "")).strip()
        provider_ref = str(serializer.validated_data.get("provider_ref", "")).strip()
        card_masked_pan = str(serializer.validated_data.get("card_masked_pan", "")).strip()
        card_brand = str(serializer.validated_data.get("card_brand", "")).strip()
        card_type = str(serializer.validated_data.get("card_type", "")).strip()
        card_auth_code = str(serializer.validated_data.get("card_auth_code", "")).strip()
        card_rrn = str(serializer.validated_data.get("card_rrn", "")).strip()
        card_bank_id = str(serializer.validated_data.get("card_bank_id", "")).strip()
        card_aid = str(serializer.validated_data.get("card_aid", "")).strip()
        card_application_label = str(serializer.validated_data.get("card_application_label", "")).strip()
        rrn = str(serializer.validated_data.get("rrn", "")).strip()
        reference_number = str(serializer.validated_data.get("reference_number", "")).strip()
        authorisation_code = str(serializer.validated_data.get("authorisation_code", "")).strip()
        tid = str(serializer.validated_data.get("tid", "")).strip()
        order_code = str(serializer.validated_data.get("order_code", "")).strip()
        short_order_code = str(serializer.validated_data.get("short_order_code", "")).strip()
        transaction_date = str(serializer.validated_data.get("transaction_date", "")).strip()
        payment_method = str(serializer.validated_data.get("payment_method", "")).strip()
        account_number = str(serializer.validated_data.get("account_number", "")).strip()
        verification_method = str(serializer.validated_data.get("verification_method", "")).strip()
        aid = str(serializer.validated_data.get("aid", "")).strip()
        bank_id = str(serializer.validated_data.get("bank_id", "")).strip()
        transaction_type_id = serializer.validated_data.get("transaction_type_id")
        transaction_event_id = serializer.validated_data.get("transaction_event_id")
        surcharge_amount = serializer.validated_data.get("surcharge_amount")
        customer_trns = str(serializer.validated_data.get("customer_trns", "")).strip()
        provider_status = str(serializer.validated_data.get("provider_status", "")).strip()
        provider_action = str(serializer.validated_data.get("provider_action", "")).strip()
        provider_message = str(serializer.validated_data.get("provider_message", "")).strip()
        provider_payload = serializer.validated_data.get("provider_payload")

        with transaction.atomic():
            check = Check.objects.select_for_update().filter(id=check_id).first()
            if not check:
                return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if check.status != Check.Status.OPEN:
                return Response({"detail": "Naplata je moguća samo za OPEN check."}, status=status.HTTP_409_CONFLICT)

            part = check.settlement_parts.select_for_update().filter(id=part_id).first()
            if not part:
                return Response({"detail": "Settlement part ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if part.method != SettlementPart.Method.CARD:
                return Response(
                    {
                        "detail": "Part nije CARD.",
                        "check_id": check.id,
                        "part_id": part.id,
                        "actual_method": part.method,
                        "expected_method": SettlementPart.Method.CARD,
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            if requested_amount is not None:
                normalized_requested_amount = Decimal(str(requested_amount)).quantize(Decimal("0.01"))
                if normalized_requested_amount != part.amount:
                    return Response({"detail": "amount mora biti jednak amount-u settlement parta."}, status=400)
            if requested_tip_amount is not None:
                normalized_requested_tip = Decimal(str(requested_tip_amount)).quantize(Decimal("0.01"))
                if normalized_requested_tip != part.tip_amount:
                    return Response({"detail": "tip_amount mora biti jednak tip_amount-u settlement parta."}, status=400)

            if approved and part.status == SettlementPart.Status.PAID:
                if external_txn_id and part.external_txn_id and part.external_txn_id != external_txn_id:
                    return Response({"detail": "Part je već plaćen drugim transaction ID-em."}, status=409)
                snapshot = _build_settlement_snapshot(check)
                return Response(
                    {
                        "check_id": check.id,
                        "part_id": part.id,
                        "action": "idempotent",
                        "part_status": part.status,
                        "parts": snapshot["parts"],
                        "totals": snapshot["totals"],
                        "actions": snapshot["actions"],
                        "issued_receipt_id": check.pos_receipt_id,
                        "pos_receipt_ids": _collect_check_receipt_ids(check),
                        "receipt_pdf_url": _build_receipt_pdf_url(request, check.pos_receipt_id),
                    }
                )

            if external_txn_id:
                part.external_txn_id = external_txn_id
            if provider:
                part.provider = provider
            if provider_ref:
                part.provider_ref = provider_ref
            if card_masked_pan:
                part.card_masked_pan = card_masked_pan
            if card_brand:
                part.card_brand = card_brand
            if card_type:
                part.card_type = card_type
            if card_auth_code:
                part.card_auth_code = card_auth_code
            if card_rrn:
                part.card_rrn = card_rrn
            if card_bank_id:
                part.card_bank_id = card_bank_id
            if card_aid:
                part.card_aid = card_aid
            if card_application_label:
                part.card_application_label = card_application_label
            if rrn:
                part.card_rrn = rrn
            if reference_number:
                part.provider_reference_number = reference_number
            if authorisation_code:
                part.card_auth_code = authorisation_code
            if tid:
                part.provider_tid = tid
            if order_code:
                part.provider_order_code = order_code
            if short_order_code:
                part.provider_short_order_code = short_order_code
            if transaction_date:
                part.provider_transaction_date = transaction_date
            if payment_method:
                part.provider_payment_method = payment_method
            if account_number:
                part.provider_account_number = account_number
                if not part.card_masked_pan:
                    part.card_masked_pan = account_number
            if verification_method:
                part.provider_verification_method = verification_method
            if aid:
                part.card_aid = aid
            if bank_id:
                part.card_bank_id = bank_id
            if transaction_type_id is not None:
                part.provider_transaction_type_id = int(transaction_type_id)
            if transaction_event_id is not None:
                part.provider_transaction_event_id = int(transaction_event_id)
            if surcharge_amount is not None:
                part.provider_surcharge_amount = Decimal(str(surcharge_amount)).quantize(Decimal("0.01"))
            if customer_trns:
                part.provider_customer_trns = customer_trns
            if provider_status:
                part.provider_status = provider_status
            if provider_action:
                part.provider_action = provider_action
            if provider_message:
                part.provider_message = provider_message
            if provider_payload is not None:
                part.provider_payload = provider_payload

            if not approved:
                part.status = SettlementPart.Status.FAILED
                part.confirmed_at = timezone.now()
                part.confirmed_by = request.user
                part.save(
                    update_fields=[
                        "status",
                        "confirmed_at",
                        "confirmed_by",
                        "provider",
                        "external_txn_id",
                        "provider_ref",
                        "card_masked_pan",
                        "card_brand",
                        "card_type",
                        "card_auth_code",
                        "card_rrn",
                        "card_bank_id",
                        "card_aid",
                        "card_application_label",
                        "provider_reference_number",
                        "provider_tid",
                        "provider_order_code",
                        "provider_short_order_code",
                        "provider_transaction_date",
                        "provider_payment_method",
                        "provider_account_number",
                        "provider_verification_method",
                        "provider_transaction_type_id",
                        "provider_transaction_event_id",
                        "provider_surcharge_amount",
                        "provider_customer_trns",
                        "provider_status",
                        "provider_action",
                        "provider_message",
                        "provider_payload",
                        "updated_at",
                    ]
                )
                _recalculate_check_settlement_status(check)
                check.save(update_fields=["settlement_status", "payment_status", "updated_at"])
                snapshot = _build_settlement_snapshot(check)
                return Response(
                    {
                        "check_id": check.id,
                        "part_id": part.id,
                        "action": "failed",
                        "part_status": part.status,
                        "parts": snapshot["parts"],
                        "totals": snapshot["totals"],
                        "actions": snapshot["actions"],
                        "issued_receipt_id": check.pos_receipt_id,
                        "pos_receipt_ids": _collect_check_receipt_ids(check),
                        "receipt_pdf_url": _build_receipt_pdf_url(request, check.pos_receipt_id),
                    }
                )

            part.status = SettlementPart.Status.PAID
            part.confirmed_at = timezone.now()
            part.confirmed_by = request.user
            part.save(
                update_fields=[
                    "status",
                    "confirmed_at",
                    "confirmed_by",
                    "provider",
                    "external_txn_id",
                    "provider_ref",
                    "card_masked_pan",
                    "card_brand",
                    "card_type",
                    "card_auth_code",
                    "card_rrn",
                    "card_bank_id",
                    "card_aid",
                    "card_application_label",
                    "provider_reference_number",
                    "provider_tid",
                    "provider_order_code",
                    "provider_short_order_code",
                    "provider_transaction_date",
                    "provider_payment_method",
                    "provider_account_number",
                    "provider_verification_method",
                    "provider_transaction_type_id",
                    "provider_transaction_event_id",
                    "provider_surcharge_amount",
                    "provider_customer_trns",
                    "provider_status",
                    "provider_action",
                    "provider_message",
                    "provider_payload",
                    "updated_at",
                ]
            )
            _, allocations = _allocate_payment_to_items(check=check, amount=part.amount, with_allocations=True)
            issued_receipt = _create_receipt_for_part_payment(part=part, allocations=allocations, user=request.user)

            _recalculate_check_settlement_status(check)
            check.save(update_fields=["settlement_status", "payment_status", "updated_at"])
            snapshot = _build_settlement_snapshot(check)
            return Response(
                {
                    "check_id": check.id,
                    "part_id": part.id,
                    "action": "paid",
                    "part_status": part.status,
                    "parts": snapshot["parts"],
                    "totals": snapshot["totals"],
                    "actions": snapshot["actions"],
                    "issued_receipt_id": issued_receipt.id if issued_receipt else check.pos_receipt_id,
                    "pos_receipt_ids": _collect_check_receipt_ids(check),
                    "receipt_pdf_url": _build_receipt_pdf_url(
                        request, issued_receipt.id if issued_receipt else check.pos_receipt_id
                    ),
                }
            )


class PosCheckPayCardConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _close_check_and_release_table(*, check: Check, user):
        check.status = Check.Status.CLOSED
        check.closed_at = timezone.now()
        check.closed_by = user
        check.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
        placements = list(
            LayoutTable.objects.select_for_update()
            .filter(table_id=check.table_id, is_enabled=True)
            .only("id")
        )
        if placements:
            TableState.objects.filter(
                layout_table_id__in=[p.id for p in placements],
                open_check_id=check.id,
            ).update(
                state=TableState.State.FREE,
                open_check_id=None,
                updated_by=user,
                updated_at=timezone.now(),
            )

    @extend_schema(
        description=(
            "Confirms CARD settlement part (idempotent by external_txn_id). "
            "Can optionally issue receipt if settlement is fully covered."
        ),
        request=PayCardConfirmRequestSerializer,
        responses={
            200: PayCardConfirmResponseSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
            409: ErrorSerializer,
        },
    )
    def post(self, request, check_id: int):
        serializer = PayCardConfirmRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requested_amount = serializer.validated_data.get("amount")
        external_txn_id = str(serializer.validated_data.get("external_txn_id", "")).strip()
        should_issue_receipt = bool(serializer.validated_data.get("issue_receipt", False))

        with transaction.atomic():
            check = Check.objects.select_for_update().filter(id=check_id).select_related("table").first()
            if not check:
                return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if check.status != Check.Status.OPEN:
                return Response({"detail": "Card potvrda je moguća samo za OPEN check."}, status=409)

            all_parts = list(check.settlement_parts.select_for_update().order_by("id"))
            if not all_parts:
                return Response({"detail": "Settlement nije pripremljen."}, status=status.HTTP_409_CONFLICT)

            card_parts = [part for part in all_parts if part.method == SettlementPart.Method.CARD]
            if not card_parts:
                return Response({"detail": "Check nema CARD settlement part."}, status=status.HTTP_409_CONFLICT)

            if external_txn_id:
                same_txn = next((p for p in card_parts if p.external_txn_id == external_txn_id), None)
                if same_txn:
                    _recalculate_check_settlement_status(check)
                    check.save(update_fields=["settlement_status", "payment_status", "updated_at"])
                    snapshot = _build_settlement_snapshot(check)
                    remaining_total = _money_str(snapshot["totals"]["remaining_total"])
                    return Response(
                        {
                            "check_id": check.id,
                            "settlement_status": check.settlement_status,
                            "payment_status": check.payment_status,
                            "card_confirmed": True,
                            "issued_receipt_id": check.pos_receipt_id,
                            "pos_receipt_ids": _collect_check_receipt_ids(check),
                            "receipt_pdf_url": _build_receipt_pdf_url(request, check.pos_receipt_id),
                            "remaining_total": remaining_total,
                            "check_closed": check.status == Check.Status.CLOSED,
                            "action": "idempotent",
                            "parts": snapshot["parts"],
                            "totals": snapshot["totals"],
                            "actions": snapshot["actions"],
                        }
                    )

            unconfirmed_card_parts = [part for part in card_parts if part.status != SettlementPart.Status.PAID]
            if not unconfirmed_card_parts:
                _recalculate_check_settlement_status(check)
                check.save(update_fields=["settlement_status", "payment_status", "updated_at"])
                snapshot = _build_settlement_snapshot(check)
                remaining_total = _money_str(snapshot["totals"]["remaining_total"])
                return Response(
                    {
                        "check_id": check.id,
                        "settlement_status": check.settlement_status,
                        "payment_status": check.payment_status,
                        "card_confirmed": True,
                        "issued_receipt_id": check.pos_receipt_id,
                        "pos_receipt_ids": _collect_check_receipt_ids(check),
                        "receipt_pdf_url": _build_receipt_pdf_url(request, check.pos_receipt_id),
                        "remaining_total": remaining_total,
                        "check_closed": check.status == Check.Status.CLOSED,
                        "action": "already_confirmed",
                        "parts": snapshot["parts"],
                        "totals": snapshot["totals"],
                        "actions": snapshot["actions"],
                    }
                )

            unconfirmed_card_total = sum((part.amount for part in unconfirmed_card_parts), Decimal("0.00")).quantize(Decimal("0.01"))
            if requested_amount is not None:
                normalized_requested = Decimal(str(requested_amount)).quantize(Decimal("0.01"))
                if normalized_requested != unconfirmed_card_total:
                    return Response(
                        {
                            "detail": "amount mora biti jednak nepotvrđenom CARD iznosu.",
                            "expected_amount": str(unconfirmed_card_total),
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            now = timezone.now()
            allocated_card_total = Decimal("0.00")
            confirmed_parts: list[SettlementPart] = []
            for part in unconfirmed_card_parts:
                part.status = SettlementPart.Status.PAID
                part.confirmed_at = now
                part.confirmed_by = request.user
                if external_txn_id:
                    part.external_txn_id = external_txn_id
                part.save(update_fields=["status", "confirmed_at", "confirmed_by", "external_txn_id", "updated_at"])
                allocated_card_total += part.amount
                confirmed_parts.append(part)
            _, allocations = _allocate_payment_to_items(check=check, amount=allocated_card_total, with_allocations=True)
            issued_receipt = None
            if confirmed_parts:
                issued_receipt = _create_receipt_for_part_payment(
                    part=confirmed_parts[0],
                    allocations=allocations,
                    user=request.user,
                )
                if issued_receipt:
                    for extra_part in confirmed_parts[1:]:
                        if not extra_part.confirmed_receipt_id:
                            extra_part.confirmed_receipt = issued_receipt
                            extra_part.save(update_fields=["confirmed_receipt", "updated_at"])

            _recalculate_check_settlement_status(check)
            check.save(update_fields=["settlement_status", "payment_status", "updated_at"])

            snapshot = _build_settlement_snapshot(check)
            remaining_total = _money_str(snapshot["totals"]["remaining_total"])

            issued_receipt_id = issued_receipt.id if issued_receipt else check.pos_receipt_id
            receipt_pdf_url = _build_receipt_pdf_url(request, issued_receipt_id)
            check_closed = check.status == Check.Status.CLOSED
            action = "card_confirmed"

            if Decimal(str(remaining_total)) <= Decimal("0.00") and should_issue_receipt:
                check.settlement_status = Check.SettlementStatus.COMPLETE
                check.payment_status = Check.PaymentStatus.PAID
                check.save(update_fields=["settlement_status", "payment_status", "updated_at"])
                self._close_check_and_release_table(check=check, user=request.user)
                snapshot = _build_settlement_snapshot(check)
                issued_receipt_id = issued_receipt.id if issued_receipt else check.pos_receipt_id
                receipt_pdf_url = _build_receipt_pdf_url(request, issued_receipt_id)
                check_closed = True
                action = "confirmed_and_issued"

        return Response(
            {
                "check_id": check.id,
                "settlement_status": check.settlement_status,
                "payment_status": check.payment_status,
                "card_confirmed": True,
                "issued_receipt_id": issued_receipt_id,
                "pos_receipt_ids": _collect_check_receipt_ids(check),
                "receipt_pdf_url": receipt_pdf_url,
                "remaining_total": remaining_total,
                "check_closed": check_closed,
                "action": action,
                "parts": snapshot["parts"],
                "totals": snapshot["totals"],
                "actions": snapshot["actions"],
            }
        )


class PosCheckIssueReceiptView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _resolve_pos_and_warehouse(*, pos_id, device_id, warehouse_rm_id):
        pos = Pos.objects.filter(id=pos_id).first() if pos_id else None
        if not pos and device_id:
            device = (
                PosDevice.objects.select_related("pos", "pos__warehouse")
                .filter(device_id=device_id, is_active=True, pos__is_active=True)
                .first()
            )
            if device:
                pos = device.pos

        if warehouse_rm_id:
            from stock.models import WarehouseId

            warehouse = WarehouseId.objects.filter(rm_id=warehouse_rm_id).first()
        elif pos and pos.warehouse_id:
            warehouse = pos.warehouse
        else:
            warehouse = None

        return pos, warehouse

    @staticmethod
    def _ensure_turnover(*, user, pos, warehouse):
        issued_on = timezone.localdate()
        turnover = ShiftTurnover.objects.filter(
            issued_on=issued_on,
            user=user,
            warehouse_id=warehouse.id if warehouse else None,
            pos_id=pos.id if pos else None,
        ).first()
        if not turnover:
            turnover = ShiftTurnover.objects.create(
                issued_on=issued_on,
                user=user,
                warehouse_id=warehouse.id if warehouse else None,
                pos_id=pos.id if pos else None,
                total_amount=Decimal("0.00"),
                invoice_count=0,
                invoice_ids=[],
            )

        if os.getenv("POS_REQUIRE_OPENING", "false").lower() in ("1", "true", "yes", "on"):
            opening = (
                turnover.cash_handovers.filter(kind=ShiftCashHandover.Kind.OPENING)
                .order_by("-created_at")
                .first()
            )
            if not opening:
                return None, Response(
                    {
                        "detail": "Preuzimanje blagajne je obavezno prije rada.",
                        "opening_required": True,
                        "turnover_id": turnover.id,
                    },
                    status=status.HTTP_423_LOCKED,
                )
        return turnover, None

    @extend_schema(
        description="Issues POS receipt from OPEN Barion check items and closes the check.",
        request=IssueCheckReceiptRequestSerializer,
        responses={
            200: IssueCheckReceiptResponseSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
            409: ErrorSerializer,
            423: ErrorSerializer,
        },
    )
    def post(self, request, check_id: int):
        ok, remaining = is_recent_pin_verified(request.user)
        if not ok:
            return Response(
                {
                    "detail": "Potrebna je PIN potvrda za ovu akciju.",
                    "pin_verify_required": True,
                    "pin_verify_endpoint": "/api/pos/pin/verify/",
                    "pin_verify_ttl_seconds": pin_verify_ttl_seconds(),
                    "pin_verify_remaining_seconds": remaining,
                },
                status=428,
            )

        request_serializer = IssueCheckReceiptRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        data = request_serializer.validated_data

        office_code = data.get("office_code") or os.getenv("FISCAL_OFFICE_CODE", "POS1")
        device_code = data.get("device_code") or os.getenv("FISCAL_DEVICE_CODE", "1")
        payment_type = data.get("payment_type") or "cash"
        pos_id = data.get("pos_id")
        warehouse_rm_id = data.get("warehouse_id")
        device_id = str(data.get("device_id", "") or "").strip()
        should_fiscalize = bool(data.get("fiscalize", True))

        with transaction.atomic():
            check = (
                Check.objects.select_for_update()
                .filter(id=check_id)
                .select_related("table")
                .first()
            )
            if not check:
                return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)

            if check.pos_receipt_id and check.status != Check.Status.OPEN:
                receipt = check.pos_receipt
                if receipt is None:
                    return Response({"detail": "Neispravna veza na POS račun."}, status=status.HTTP_409_CONFLICT)
                snapshot = _build_settlement_snapshot(check)
                return Response(
                    {
                        "check_id": check.id,
                        "check_status": check.status,
                        "settlement_status": check.settlement_status,
                        "payment_status": check.payment_status,
                        "receipt_id": receipt.id,
                        "receipt_number": receipt.receipt_number,
                        "status": receipt.status,
                        "total_amount": receipt.total_amount,
                        "zki": receipt.zki,
                        "jir": receipt.jir,
                        "qr": receipt.qr_payload,
                        "parts": snapshot["parts"],
                        "totals": snapshot["totals"],
                        "actions": snapshot["actions"],
                    }
                )

            if check.status != Check.Status.OPEN:
                if check.status == Check.Status.CLOSED and not check.pos_receipt_id:
                    check.status = Check.Status.OPEN
                    check.closed_at = None
                    check.closed_by = None
                    check.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
                else:
                    return Response(
                        {"detail": "Check nije otvoren pa nije moguće izdati račun."},
                        status=status.HTTP_409_CONFLICT,
                    )

            if check.status != Check.Status.OPEN:
                return Response(
                    {"detail": "Check nije otvoren pa nije moguće izdati račun."},
                    status=status.HTTP_409_CONFLICT,
                )

            settlement_parts = list(check.settlement_parts.select_for_update().order_by("id"))
            if settlement_parts:
                has_unconfirmed_card = any(
                    part.method == SettlementPart.Method.CARD and part.status != SettlementPart.Status.PAID
                    for part in settlement_parts
                )
                if has_unconfirmed_card:
                    return Response(
                        {"detail": "Kartični dio naplate nije potvrđen."},
                        status=status.HTTP_409_CONFLICT,
                    )

            check_items = list(
                check.items.select_related("artikl")
                .prefetch_related("modifier_selections__bundle_option__artikl")
                .order_by("id")
            )
            if not check_items:
                return Response({"detail": "Check nema stavki."}, status=status.HTTP_400_BAD_REQUEST)

            pos, warehouse = self._resolve_pos_and_warehouse(
                pos_id=pos_id,
                device_id=device_id,
                warehouse_rm_id=warehouse_rm_id,
            )
            _, turnover_error = self._ensure_turnover(user=request.user, pos=pos, warehouse=warehouse)
            if turnover_error:
                return turnover_error

            items_payload = [
                {
                    "artikl": item.artikl_id,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                }
                for item in check_items
            ]
            try:
                receipt = create_pos_receipt(
                    office_code=office_code,
                    device_code=device_code,
                    payment_type=payment_type,
                    items=items_payload,
                    operator=request.user,
                    pos=pos,
                    warehouse=warehouse,
                )
            except Exception as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

            if should_fiscalize:
                try:
                    receipt = fiscalize_pos_receipt(receipt)
                except Exception as exc:
                    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            _save_receipt_pdf_to_media(receipt, request.user)

            if warehouse:
                stock_reference = f"Barion check {check.id} receipt {receipt.id}"
                already_posted = StockMove.objects.filter(
                    move_type=StockMove.MoveType.OUT,
                    purpose=StockMove.Purpose.SALE,
                    reference=stock_reference,
                ).exists()
                if not already_posted:
                    stock_lines, _skipped = _build_stock_out_lines_for_check_items(check_items)
                    if stock_lines:
                        try:
                            post_stock_out(
                                warehouse=warehouse,
                                items=stock_lines,
                                move_date=receipt.issued_at,
                                reference=stock_reference,
                                note=f"Robno razduzenje Barion check #{check.id}, receipt #{receipt.id}",
                                purpose=StockMove.Purpose.SALE,
                                auto_cogs=False,
                                posted_by=request.user,
                            )
                        except ValidationError as exc:
                            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
                        except Exception as exc:
                            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

            if settlement_parts:
                for part in settlement_parts:
                    if part.status != SettlementPart.Status.PAID:
                        part.status = SettlementPart.Status.PAID
                        part.confirmed_at = timezone.now()
                        part.confirmed_by = request.user
                    if not part.confirmed_receipt_id:
                        part.confirmed_receipt = receipt
                    part.save(
                        update_fields=[
                            "status",
                            "confirmed_at",
                            "confirmed_by",
                            "confirmed_receipt",
                            "updated_at",
                        ]
                    )
            else:
                check_total = _check_total_amount(check)
                if check_total > Decimal("0.00"):
                    SettlementPart.objects.create(
                        barion_check=check,
                        method=SettlementPart.Method.CASH if payment_type.lower() != "card" else SettlementPart.Method.CARD,
                        amount=check_total,
                        tip_amount=Decimal("0.00"),
                        total_charged=check_total,
                        fiscal_amount=check_total,
                        status=SettlementPart.Status.PAID,
                        confirmed_at=timezone.now(),
                        confirmed_by=request.user,
                        confirmed_receipt=receipt,
                    )
            _mark_all_items_paid(check=check)

            check.status = Check.Status.CLOSED
            check.closed_at = timezone.now()
            check.closed_by = request.user
            check.settlement_status = Check.SettlementStatus.COMPLETE
            check.payment_status = Check.PaymentStatus.PAID
            check.save(
                update_fields=[
                    "status",
                    "closed_at",
                    "closed_by",
                    "settlement_status",
                    "payment_status",
                    "updated_at",
                ]
            )

            placements = list(
                LayoutTable.objects.select_for_update()
                .filter(table_id=check.table_id, is_enabled=True)
                .only("id")
            )
            if placements:
                TableState.objects.filter(
                    layout_table_id__in=[p.id for p in placements],
                    open_check_id=check.id,
                ).update(
                    state=TableState.State.FREE,
                    open_check_id=None,
                    updated_by=request.user,
                    updated_at=timezone.now(),
                )

        snapshot = _build_settlement_snapshot(check)
        return Response(
            {
                "check_id": check.id,
                "check_status": check.status,
                "settlement_status": check.settlement_status,
                "payment_status": check.payment_status,
                "receipt_id": receipt.id,
                "receipt_number": receipt.receipt_number,
                "status": receipt.status,
                "total_amount": receipt.total_amount,
                "zki": receipt.zki,
                "jir": receipt.jir,
                "qr": receipt.qr_payload,
                "parts": snapshot["parts"],
                "totals": snapshot["totals"],
                "actions": snapshot["actions"],
            }
        )


class PosCheckItemsView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _serialize_item(item: CheckItem) -> dict:
        modifiers = _serialize_check_item_modifiers(item)
        payload = {
            "id": item.id,
            "check_id": item.barion_check_id,
            "artikl_id": item.artikl_id,
            "artikl_name": item.artikl.name,
            "quantity": _display_quantity_for_item(item),
            "unit_price": item.unit_price,
            "vat_rate": item.vat_rate,
            "net_amount": item.net_amount,
            "vat_amount": item.vat_amount,
            "total_amount": item.total_amount,
            "round_number": item.round_number,
            "sent_to_bar": item.sent_to_bar,
            "line_type": item.line_type,
            "sent_at": item.sent_at.isoformat() if item.sent_at else None,
            "note": item.note,
            "modifiers": modifiers,
            "display_lines": _build_check_item_display_lines(item),
        }
        auto_applied = getattr(item, "_modifiers_auto_applied", None)
        if auto_applied is not None:
            payload["modifiers_auto_applied"] = bool(auto_applied)
        return payload

    @staticmethod
    def _get_totals(check: Check) -> dict:
        net_amount = Decimal("0.00")
        vat_amount = Decimal("0.00")
        total_amount = Decimal("0.00")
        for item in check.items.all():
            if item.line_type != CheckItem.LineType.NORMAL:
                continue
            chargeable_qty = _chargeable_qty_for_item(item)
            if chargeable_qty <= Decimal("0.0000"):
                continue
            line_total = (chargeable_qty * Decimal(str(item.unit_price or "0.0000"))).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            rate = Decimal(str(item.vat_rate or "0.0000"))
            if rate > Decimal("0.0000"):
                line_net = (line_total / (Decimal("1.00") + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                line_net = line_total
            line_vat = (line_total - line_net).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_amount = (total_amount + line_total).quantize(Decimal("0.01"))
            net_amount = (net_amount + line_net).quantize(Decimal("0.01"))
            vat_amount = (vat_amount + line_vat).quantize(Decimal("0.01"))
        return {
            "items_count": check.items.count(),
            "net_amount": net_amount,
            "vat_amount": vat_amount,
            "total_amount": total_amount,
        }

    @extend_schema(
        description=(
            "Returns items for a check with totals. "
            "Each item includes `line_type` (NORMAL/STORNO/GRATIS/OTPIS)."
        ),
        responses={
            200: CheckItemsResponseSerializer,
            404: ErrorSerializer,
        },
    )
    def get(self, request, check_id: int):
        check = Check.objects.filter(id=check_id).first()
        if not check:
            return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        items = list(
            check.items.select_related("artikl")
            .prefetch_related(
                "modifier_selections__group",
                "modifier_selections__option",
                "modifier_selections__bundle_option__artikl",
            )
            .order_by("id")
        )
        return Response(
            {
                "check_id": check.id,
                "status": check.status,
                "items": [self._serialize_item(item) for item in items],
                "totals": self._get_totals(check),
            }
        )

    @extend_schema(
        description="Adds NORMAL item to check. If check is CLOSED, it is reopened automatically.",
        request=CreateCheckItemRequestSerializer,
        responses={
            201: CheckItemSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
            409: ErrorSerializer,
        },
    )
    def post(self, request, check_id: int):
        serializer = CreateCheckItemRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        modifiers_provided = "modifiers" in serializer.initial_data

        with transaction.atomic():
            check = Check.objects.select_for_update().filter(id=check_id).first()
            if not check:
                return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if check.status == Check.Status.CLOSED:
                check.status = Check.Status.OPEN
                check.closed_at = None
                check.closed_by = None
                check.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])

            artikl_id = data["artikl_id"]
            artikl = Artikl.objects.filter(id=artikl_id).first()
            if not artikl:
                return Response({"detail": "Artikl ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if modifiers_provided:
                modifier_ids = _normalize_modifier_ids(data.get("modifiers"))
                modifiers_auto_applied = False
            else:
                modifier_ids = _default_modifier_ids_for_artikl(artikl_id)
                modifiers_auto_applied = bool(modifier_ids)
            note = data.get("note", "")
            try:
                _enforce_qty_customization_rule(
                    quantity=data["quantity"],
                    note=note,
                    modifier_ids=modifier_ids,
                )
                allowed_option_to_assignment = _validate_modifier_ids_for_artikl(
                    artikl_id=artikl_id,
                    modifier_ids=modifier_ids,
                )
            except serializers.ValidationError as exc:
                return Response({"detail": str(exc.detail)}, status=status.HTTP_400_BAD_REQUEST)
            try:
                effective_unit_price = _resolve_effective_unit_price_for_item(
                    artikl_id=artikl_id,
                    requested_unit_price=data.get("unit_price"),
                    current_unit_price=None,
                    modifier_ids=modifier_ids,
                )
            except serializers.ValidationError as exc:
                return Response({"detail": str(exc.detail)}, status=status.HTTP_400_BAD_REQUEST)

            check_item = CheckItem.objects.create(
                barion_check=check,
                artikl=artikl,
                quantity=data["quantity"],
                unit_price=effective_unit_price,
                vat_rate=data.get("vat_rate", Decimal("0.0000")),
                note=note,
            )
            _set_check_item_modifiers(
                check_item=check_item,
                modifier_ids=modifier_ids,
                allowed_option_to_assignment=allowed_option_to_assignment,
            )
            check_item._modifiers_auto_applied = modifiers_auto_applied
            _sync_settlement_after_items_changed(check=check, user=request.user)

            placements = list(
                LayoutTable.objects.select_for_update()
                .filter(table_id=check.table_id, is_enabled=True)
                .only("id")
            )
            for placement in placements:
                TableState.objects.update_or_create(
                    layout_table=placement,
                    defaults={
                        "state": TableState.State.OPEN,
                        "open_check_id": check.id,
                        "updated_by": request.user,
                    },
                )

        return Response(self._serialize_item(check_item), status=status.HTTP_201_CREATED)


class PosCheckItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _serialize_item(item: CheckItem) -> dict:
        modifiers = _serialize_check_item_modifiers(item)
        payload = {
            "id": item.id,
            "check_id": item.barion_check_id,
            "artikl_id": item.artikl_id,
            "artikl_name": item.artikl.name,
            "quantity": _display_quantity_for_item(item),
            "unit_price": item.unit_price,
            "vat_rate": item.vat_rate,
            "net_amount": item.net_amount,
            "vat_amount": item.vat_amount,
            "total_amount": item.total_amount,
            "round_number": item.round_number,
            "sent_to_bar": item.sent_to_bar,
            "line_type": item.line_type,
            "sent_at": item.sent_at.isoformat() if item.sent_at else None,
            "note": item.note,
            "modifiers": modifiers,
            "display_lines": _build_check_item_display_lines(item),
        }
        auto_applied = getattr(item, "_modifiers_auto_applied", None)
        if auto_applied is not None:
            payload["modifiers_auto_applied"] = bool(auto_applied)
        return payload

    @extend_schema(
        description=(
            "Updates check item on OPEN check. "
            "Use dedicated endpoints for STORNO/GRATIS actions."
        ),
        request=UpdateCheckItemRequestSerializer,
        responses={
            200: CheckItemSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
            409: ErrorSerializer,
        },
    )
    def patch(self, request, item_id: int):
        serializer = UpdateCheckItemRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            item = (
                CheckItem.objects.select_for_update()
                .select_related("barion_check")
                .filter(id=item_id)
                .first()
            )
            if not item:
                return Response({"detail": "Stavka ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if item.barion_check.status != Check.Status.OPEN:
                return Response(
                    {"detail": "Nije moguće mijenjati stavke zatvorenog checka."},
                    status=status.HTTP_409_CONFLICT,
                )

            if "artikl_id" in data:
                artikl_id = data["artikl_id"]
                artikl = Artikl.objects.filter(id=artikl_id).first()
                if not artikl:
                    return Response({"detail": "Artikl ne postoji."}, status=status.HTTP_404_NOT_FOUND)
                item.artikl = artikl
            target_artikl_id = data.get("artikl_id", item.artikl_id)
            target_quantity = data.get("quantity", item.quantity)
            target_note = data.get("note", item.note)
            modifiers_auto_applied = False
            if "modifiers" in data:
                target_modifier_ids = _normalize_modifier_ids(data.get("modifiers"))
            elif "artikl_id" in data:
                target_modifier_ids = _default_modifier_ids_for_artikl(target_artikl_id)
                modifiers_auto_applied = bool(target_modifier_ids)
            else:
                target_modifier_ids = []
                for selection in item.modifier_selections.all():
                    if selection.option_id:
                        target_modifier_ids.append(("simple", selection.option_id, 1))
                    elif selection.bundle_option_id:
                        target_modifier_ids.append(("bundle", selection.bundle_option_id, int(selection.quantity)))
            try:
                _enforce_qty_customization_rule(
                    quantity=target_quantity,
                    note=target_note,
                    modifier_ids=target_modifier_ids,
                )
                allowed_option_to_assignment = _validate_modifier_ids_for_artikl(
                    artikl_id=target_artikl_id,
                    modifier_ids=target_modifier_ids,
                )
            except serializers.ValidationError as exc:
                return Response({"detail": str(exc.detail)}, status=status.HTTP_400_BAD_REQUEST)
            try:
                effective_unit_price = _resolve_effective_unit_price_for_item(
                    artikl_id=target_artikl_id,
                    requested_unit_price=data.get("unit_price"),
                    current_unit_price=item.unit_price,
                    modifier_ids=target_modifier_ids,
                )
            except serializers.ValidationError as exc:
                return Response({"detail": str(exc.detail)}, status=status.HTTP_400_BAD_REQUEST)

            for field in ("quantity", "unit_price", "vat_rate", "note"):
                if field in data:
                    setattr(item, field, data[field])
            if "unit_price" in data or "modifiers" in data or "artikl_id" in data:
                item.unit_price = effective_unit_price
            item.save()
            if "modifiers" in data or "artikl_id" in data:
                _set_check_item_modifiers(
                    check_item=item,
                    modifier_ids=target_modifier_ids,
                    allowed_option_to_assignment=allowed_option_to_assignment,
                )
                if "artikl_id" in data:
                    item._modifiers_auto_applied = modifiers_auto_applied
            _sync_settlement_after_items_changed(check=item.barion_check, user=request.user)

        return Response(self._serialize_item(item))

    @extend_schema(
        description="Deletes check item from OPEN check.",
        responses={
            204: None,
            404: ErrorSerializer,
            409: ErrorSerializer,
        },
    )
    def delete(self, request, item_id: int):
        with transaction.atomic():
            item = CheckItem.objects.select_for_update().select_related("barion_check").filter(id=item_id).first()
            if not item:
                return Response({"detail": "Stavka ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if item.barion_check.status != Check.Status.OPEN:
                return Response(
                    {"detail": "Nije moguće brisati stavke zatvorenog checka."},
                    status=status.HTTP_409_CONFLICT,
                )
            check = item.barion_check
            item.delete()
            _sync_settlement_after_items_changed(check=check, user=request.user)
            if not check.items.exists():
                placements = list(
                    LayoutTable.objects.select_for_update()
                    .filter(table_id=check.table_id, is_enabled=True)
                    .only("id")
                )
                if placements:
                    TableState.objects.filter(layout_table_id__in=[p.id for p in placements]).update(
                        state=TableState.State.FREE,
                        open_check_id=None,
                        updated_by=request.user,
                        updated_at=timezone.now(),
                    )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PosCheckItemStornoView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _storno_marker(item_id: int) -> str:
        return f"[storno_of:{item_id}]"

    @classmethod
    def _storno_applied_qty(cls, *, check_id: int, item_id: int) -> Decimal:
        marker = cls._storno_marker(item_id)
        storno_sum = (
            CheckItem.objects.filter(
                barion_check_id=check_id,
                line_type=CheckItem.LineType.STORNO,
                note__startswith=marker,
            ).aggregate(total=Sum("quantity"))["total"]
            or Decimal("0.0000")
        )
        return abs(Decimal(str(storno_sum)))

    @extend_schema(
        description="Creates storno line on the same OPEN check by copying item with negative quantity.",
        request=CheckItemActionRequestSerializer,
        examples=[
            OpenApiExample(
                "Storno request",
                value={"reason": "Krivi unos"},
                request_only=True,
            ),
            OpenApiExample(
                "Storno response",
                value={
                    "id": 101,
                    "check_id": 55,
                    "artikl_id": 12,
                    "artikl_name": "Gin tonic",
                    "quantity": "-1.0000",
                    "unit_price": "8.0000",
                    "vat_rate": "0.2500",
                    "net_amount": "-6.40",
                    "vat_amount": "-1.60",
                    "total_amount": "-8.00",
                    "round_number": None,
                    "sent_to_bar": False,
                    "line_type": "STORNO",
                    "sent_at": None,
                    "note": "[storno_of:77] Krivi unos",
                },
                response_only=True,
            ),
        ],
        responses={
            201: CheckItemSerializer,
            404: ErrorSerializer,
            409: ErrorSerializer,
        },
    )
    def post(self, request, item_id: int):
        serializer = CheckItemActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "").strip()
        requested_qty = serializer.validated_data.get("quantity")

        with transaction.atomic():
            item = (
                CheckItem.objects.select_for_update()
                .select_related("barion_check", "artikl")
                .filter(id=item_id)
                .first()
            )
            if not item:
                return Response({"detail": "Stavka ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if item.barion_check.status != Check.Status.OPEN:
                return Response(
                    {"detail": "Nije moguće stornirati stavke zatvorenog checka."},
                    status=status.HTTP_409_CONFLICT,
                )
            if item.line_type == CheckItem.LineType.STORNO:
                return Response(
                    {"detail": "Storno stavku nije moguće ponovno stornirati."},
                    status=status.HTTP_409_CONFLICT,
                )
            if item.line_type == CheckItem.LineType.GRATIS:
                return Response(
                    {"detail": "Gratis stavku nije moguće stornirati."},
                    status=status.HTTP_409_CONFLICT,
                )

            marker = self._storno_marker(item.id)
            already_storno_qty = self._storno_applied_qty(
                check_id=item.barion_check_id,
                item_id=item.id,
            )
            source_qty = abs(
                _source_qty_for_item(
                    check_id=item.barion_check_id,
                    item_id=item.id,
                    stored_qty=item.quantity,
                )
            )
            paid_qty = Decimal(str(item.paid_quantity or "0.0000")).quantize(Decimal("0.0001"))
            available_qty = (
                source_qty
                - already_storno_qty
                - _gratis_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
                - _otpis_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
                - paid_qty
            )
            if available_qty <= 0:
                return Response(
                    {"detail": "Storno je već u cijelosti primijenjen za ovu stavku."},
                    status=status.HTTP_409_CONFLICT,
                )

            apply_qty = Decimal(str(requested_qty)) if requested_qty is not None else available_qty
            if apply_qty <= 0 or apply_qty > available_qty:
                return Response(
                    {"detail": f"quantity mora biti > 0 i <= {available_qty}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            existing_storno = (
                CheckItem.objects.filter(
                    barion_check_id=item.barion_check_id,
                    line_type=CheckItem.LineType.STORNO,
                    note__startswith=marker,
                )
                .order_by("id")
                .first()
            )
            if existing_storno and requested_qty is None and available_qty == source_qty:
                return Response(PosCheckItemDetailView._serialize_item(existing_storno))

            note = marker
            if reason:
                note = f"{note} {reason}"

            storno_item = CheckItem.objects.create(
                barion_check=item.barion_check,
                artikl=item.artikl,
                quantity=-apply_qty,
                unit_price=item.unit_price,
                vat_rate=item.vat_rate,
                round_number=item.round_number,
                line_type=CheckItem.LineType.STORNO,
                note=note,
            )
            _sync_settlement_after_items_changed(check=item.barion_check, user=request.user)

        return Response(PosCheckItemDetailView._serialize_item(storno_item), status=status.HTTP_201_CREATED)


class PosCheckItemGratisView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Marks item as GRATIS on OPEN check by keeping quantity and setting unit price to 0.",
        request=CheckItemActionRequestSerializer,
        examples=[
            OpenApiExample(
                "Gratis request",
                value={"reason": "Kuća časti"},
                request_only=True,
            ),
            OpenApiExample(
                "Gratis response",
                value={
                    "id": 77,
                    "check_id": 55,
                    "artikl_id": 12,
                    "artikl_name": "Gin tonic",
                    "quantity": "1.0000",
                    "unit_price": "0.0000",
                    "vat_rate": "0.2500",
                    "net_amount": "0.00",
                    "vat_amount": "0.00",
                    "total_amount": "0.00",
                    "round_number": None,
                    "sent_to_bar": False,
                    "line_type": "GRATIS",
                    "sent_at": None,
                    "note": "[gratis] Kuća časti",
                },
                response_only=True,
            ),
        ],
        responses={
            200: CheckItemSerializer,
            404: ErrorSerializer,
            409: ErrorSerializer,
        },
    )
    def post(self, request, item_id: int):
        serializer = CheckItemActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "").strip()
        requested_qty = serializer.validated_data.get("quantity")

        with transaction.atomic():
            item = (
                CheckItem.objects.select_for_update()
                .select_related("barion_check", "artikl")
                .filter(id=item_id)
                .first()
            )
            if not item:
                return Response({"detail": "Stavka ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if item.barion_check.status != Check.Status.OPEN:
                return Response(
                    {"detail": "Nije moguće postaviti gratis na zatvorenom checku."},
                    status=status.HTTP_409_CONFLICT,
                )
            if item.line_type == CheckItem.LineType.STORNO:
                return Response(
                    {"detail": "Storno stavka ne može biti gratis."},
                    status=status.HTTP_409_CONFLICT,
                )
            source_qty = _source_qty_for_item(
                check_id=item.barion_check_id,
                item_id=item.id,
                stored_qty=item.quantity,
            )
            if source_qty <= 0:
                return Response(
                    {"detail": "Gratis je moguće primijeniti samo na pozitivnu količinu."},
                    status=status.HTTP_409_CONFLICT,
                )

            storno_applied_qty = PosCheckItemStornoView._storno_applied_qty(
                check_id=item.barion_check_id,
                item_id=item.id,
            )
            paid_qty = Decimal(str(item.paid_quantity or "0.0000")).quantize(Decimal("0.0001"))
            available_qty = (
                source_qty
                - storno_applied_qty
                - _gratis_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
                - _otpis_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
                - paid_qty
            )
            if available_qty <= 0:
                return Response(
                    {"detail": "Nema dostupne količine za gratis nakon storna."},
                    status=status.HTTP_409_CONFLICT,
                )

            apply_qty = Decimal(str(requested_qty)) if requested_qty is not None else available_qty
            if apply_qty <= 0 or apply_qty > available_qty:
                return Response(
                    {"detail": f"quantity mora biti > 0 i <= {available_qty}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            gratis_note = f"[gratis_of:{item.id}]"
            if reason:
                gratis_note = f"{gratis_note} {reason}"
            gratis_item = CheckItem.objects.create(
                barion_check=item.barion_check,
                artikl=item.artikl,
                quantity=apply_qty,
                unit_price=Decimal("0.0000"),
                vat_rate=item.vat_rate,
                round_number=item.round_number,
                line_type=CheckItem.LineType.GRATIS,
                note=gratis_note,
            )
            _sync_settlement_after_items_changed(check=item.barion_check, user=request.user)

        return Response(PosCheckItemDetailView._serialize_item(gratis_item))


class PosCheckItemOtpisView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            "Marks item as OTPIS (waste/write-off) on OPEN check. "
            "Supports partial quantity and creates OTPIS line with unit_price=0."
        ),
        request=CheckItemActionRequestSerializer,
        examples=[
            OpenApiExample(
                "Otpis request",
                value={"quantity": "2.0000", "reason": "lom/prosipanje"},
                request_only=True,
            ),
            OpenApiExample(
                "Otpis response",
                value={
                    "id": 130,
                    "check_id": 55,
                    "artikl_id": 12,
                    "artikl_name": "Gin tonic",
                    "quantity": "2.0000",
                    "unit_price": "0.0000",
                    "vat_rate": "0.2500",
                    "net_amount": "0.00",
                    "vat_amount": "0.00",
                    "total_amount": "0.00",
                    "round_number": 4,
                    "sent_to_bar": False,
                    "line_type": "OTPIS",
                    "sent_at": None,
                    "note": "[otpis_of:77] lom/prosipanje",
                },
                response_only=True,
            ),
        ],
        responses={
            200: CheckItemSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
            409: ErrorSerializer,
        },
    )
    def post(self, request, item_id: int):
        serializer = CheckItemActionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get("reason", "").strip()
        requested_qty = serializer.validated_data.get("quantity")

        with transaction.atomic():
            item = (
                CheckItem.objects.select_for_update()
                .select_related("barion_check", "artikl")
                .filter(id=item_id)
                .first()
            )
            if not item:
                return Response({"detail": "Stavka ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if item.barion_check.status != Check.Status.OPEN:
                return Response(
                    {"detail": "Nije moguće napraviti otpis na zatvorenom checku."},
                    status=status.HTTP_409_CONFLICT,
                )
            if item.line_type in {CheckItem.LineType.STORNO, CheckItem.LineType.GRATIS, CheckItem.LineType.OTPIS}:
                return Response(
                    {"detail": "Otpis je moguće napraviti samo nad NORMAL stavkom."},
                    status=status.HTTP_409_CONFLICT,
                )

            source_qty = _source_qty_for_item(
                check_id=item.barion_check_id,
                item_id=item.id,
                stored_qty=item.quantity,
            )
            if source_qty <= 0:
                return Response(
                    {"detail": "Otpis je moguće primijeniti samo na pozitivnu količinu."},
                    status=status.HTTP_409_CONFLICT,
                )

            storno_applied_qty = PosCheckItemStornoView._storno_applied_qty(
                check_id=item.barion_check_id,
                item_id=item.id,
            )
            paid_qty = Decimal(str(item.paid_quantity or "0.0000")).quantize(Decimal("0.0001"))
            available_qty = (
                source_qty
                - storno_applied_qty
                - _gratis_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
                - _otpis_applied_qty_for_item(check_id=item.barion_check_id, item_id=item.id)
                - paid_qty
            )
            if available_qty <= 0:
                return Response(
                    {"detail": "Nema dostupne količine za otpis nakon storna."},
                    status=status.HTTP_409_CONFLICT,
                )

            apply_qty = Decimal(str(requested_qty)) if requested_qty is not None else available_qty
            if apply_qty <= 0 or apply_qty > available_qty:
                return Response(
                    {"detail": f"quantity mora biti > 0 i <= {available_qty}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            otpis_note = f"[otpis_of:{item.id}]"
            if reason:
                otpis_note = f"{otpis_note} {reason}"
            otpis_item = CheckItem.objects.create(
                barion_check=item.barion_check,
                artikl=item.artikl,
                quantity=apply_qty,
                unit_price=Decimal("0.0000"),
                vat_rate=item.vat_rate,
                round_number=item.round_number,
                line_type=CheckItem.LineType.OTPIS,
                note=otpis_note,
            )
            _sync_settlement_after_items_changed(check=item.barion_check, user=request.user)

        return Response(PosCheckItemDetailView._serialize_item(otpis_item))


class PosProductSearchView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _priced_sellable_queryset():
        from sales.models import SalesPriceItem

        now = timezone.now()
        active_price_subquery = (
            SalesPriceItem.objects.filter(
                artikl_id=OuterRef("pk"),
                is_active=True,
                price_list__is_active=True,
                price_list__valid_from__lte=now,
            )
            .filter(
                Q(price_list__valid_to__isnull=True)
                | Q(price_list__valid_to__gte=now)
            )
            .order_by("-price_list__valid_from", "-price_list__created_at", "-id")
            .values("unit_price_gross")[:1]
        )
        return (
            Artikl.objects.select_related("category", "tax_group")
            .annotate(
                active_unit_price=Subquery(
                    active_price_subquery,
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
            .filter(is_sellable=True, active_unit_price__isnull=False)
            .filter(Q(category__isnull=True) | Q(category__is_active=True))
        )

    @staticmethod
    def _apply_category_filter(qs, *, root_category: Category):
        qs = qs.filter(_category_subtree_q(root_category))
        delegated_nodes = _delegated_barion_descendants(
            root_category,
            active_barion_nodes=_active_barion_category_nodes_for_subtree(root_category),
        )
        if delegated_nodes:
            delegated_q = Q()
            for delegated in delegated_nodes:
                delegated_q |= _category_subtree_q(delegated)
            qs = qs.exclude(delegated_q)
        return qs

    @staticmethod
    def _serialize_products(*, request, qs, limit: int):
        rows = []
        for artikl in qs[:limit]:
            rows.append(_serialize_product_row(request=request, artikl=artikl))
        return rows

    @extend_schema(
        description="Search sellable products with active sales price for Barion POS item entry.",
        parameters=[
            OpenApiParameter(
                name="q",
                type=str,
                required=False,
                location=OpenApiParameter.QUERY,
                description="Text query for product code/name.",
            ),
            OpenApiParameter(
                name="category_id",
                type=int,
                required=False,
                location=OpenApiParameter.QUERY,
                description=(
                    "Filter po kategoriji i svim potomcima (subtree). "
                    "Za POS tabove koristi level-2 kategoriju kao root."
                ),
            ),
            OpenApiParameter(
                name="limit",
                type=int,
                required=False,
                location=OpenApiParameter.QUERY,
                description="Max results, default 20, max 100.",
            ),
            OpenApiParameter(
                name="sort",
                type=str,
                required=False,
                location=OpenApiParameter.QUERY,
                description="Sort mode: popular (default), name, code.",
            ),
        ],
        responses={
            200: PosProductSearchItemSerializer(many=True),
            400: ErrorSerializer,
        },
    )
    def get(self, request):
        raw_limit = request.query_params.get("limit", "20")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return Response({"detail": "limit mora biti broj."}, status=status.HTTP_400_BAD_REQUEST)
        limit = max(1, min(limit, 100))

        qs = self._priced_sellable_queryset()

        raw_category_id = request.query_params.get("category_id")
        if raw_category_id not in (None, ""):
            try:
                category_id = int(raw_category_id)
            except (TypeError, ValueError):
                return Response({"detail": "category_id mora biti broj."}, status=status.HTTP_400_BAD_REQUEST)
            root_category = Category.objects.filter(id=category_id, is_active=True).first()
            if not root_category:
                return Response([])
            qs = qs.filter(_category_subtree_q(root_category))
            delegated_nodes = _delegated_barion_descendants(
                root_category,
                active_barion_nodes=_active_barion_category_nodes_for_subtree(root_category),
            )
            if delegated_nodes:
                delegated_q = Q()
                for delegated in delegated_nodes:
                    delegated_q |= _category_subtree_q(delegated)
                qs = qs.exclude(delegated_q)

        q = (request.query_params.get("q") or "").strip()
        sort_mode = (request.query_params.get("sort") or "popular").strip().lower()
        if sort_mode not in {"popular", "name", "code"}:
            return Response(
                {"detail": "sort mora biti jedan od: popular, name, code."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            mode, _runtime_mode = _resolve_effective_mode(requested_mode=request.query_params.get("mode"))
        except serializers.ValidationError as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_400_BAD_REQUEST)

        popularity_field = (
            "barion_popularity_snapshot__sold_qty_night"
            if mode == "night"
            else "barion_popularity_snapshot__sold_qty_day"
        )

        qs = qs.annotate(
            popularity_score=Coalesce(
                F(popularity_field),
                Value(Decimal("0.0000")),
                output_field=DecimalField(max_digits=14, decimal_places=4),
            )
        )

        if q:
            query = Q(code__icontains=q) | Q(name__icontains=q)
            for term in [term for term in q.split(" ") if term]:
                query &= Q(name__icontains=term) | Q(code__icontains=term)

            qs = qs.filter(query).annotate(
                rank=Case(
                    When(code__iexact=q, then=Value(0)),
                    When(code__istartswith=q, then=Value(1)),
                    When(name__istartswith=q, then=Value(2)),
                    When(name__icontains=q, then=Value(3)),
                    default=Value(4),
                    output_field=IntegerField(),
                )
            )
            if sort_mode == "name":
                qs = qs.order_by("rank", "name", "id")
            elif sort_mode == "code":
                qs = qs.order_by("rank", "code", "name", "id")
            else:
                qs = qs.order_by("rank", "-popularity_score", "name", "id")
        else:
            if sort_mode == "name":
                qs = qs.order_by("name", "id")
            elif sort_mode == "code":
                qs = qs.order_by("code", "name", "id")
            else:
                qs = qs.order_by("-popularity_score", "name", "id")

        return Response(self._serialize_products(request=request, qs=qs, limit=limit))


class PosProductModifiersView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Returns active modifier groups/options configured for given product.",
        responses={
            200: ProductModifiersResponseSerializer,
            404: ErrorSerializer,
        },
    )
    def get(self, request, artikl_id: int):
        artikl = Artikl.objects.filter(id=artikl_id).first()
        if not artikl:
            return Response({"detail": "Artikl ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        assignments = list(_active_modifier_assignments_for_artikl(artikl_id))
        modifier_groups: list[dict] = []
        for assignment in assignments:
            group = assignment.group
            default_map: dict[tuple[str, int], int] = {}
            for default_sel in assignment.default_selections.all().order_by("id"):
                if default_sel.option_id and default_sel.option and default_sel.option.is_active:
                    default_map[("simple", int(default_sel.option_id))] = 1
                elif (
                    default_sel.bundle_option_id
                    and default_sel.bundle_option
                    and default_sel.bundle_option.is_active
                ):
                    key = ("bundle", int(default_sel.bundle_option_id))
                    default_map[key] = default_map.get(key, 0) + int(default_sel.quantity or 1)
            options = []
            for option in group.options.all():
                if not option.is_active:
                    continue
                default_qty = default_map.get(("simple", int(option.id)))
                options.append(
                    {
                        "id": option.id,
                        "option_type": "simple",
                        "name": option.name,
                        "code": option.code,
                        "sort_order": option.sort_order,
                        "artikl_id": None,
                        "artikl_name": None,
                        "price_delta": Decimal("0.0000"),
                        "is_default": bool(default_qty),
                        "default_quantity": default_qty if default_qty else None,
                    }
                )
            for option in group.bundle_options.all():
                if not option.is_active:
                    continue
                default_qty = default_map.get(("bundle", int(option.id)))
                options.append(
                    {
                        "id": option.id,
                        "option_type": "bundle",
                        "name": option.artikl.name,
                        "code": option.artikl.code or str(option.artikl_id),
                        "sort_order": option.sort_order,
                        "artikl_id": option.artikl_id,
                        "artikl_name": option.artikl.name,
                        "price_delta": option.price_delta,
                        "is_default": bool(default_qty),
                        "default_quantity": default_qty if default_qty else None,
                    }
                )
            options.sort(key=lambda row: (int(row["sort_order"]), str(row["name"]).lower(), int(row["id"])))
            min_select, max_select = _resolve_group_min_max(assignment)
            modifier_groups.append(
                {
                    "id": group.id,
                    "name": group.name,
                    "code": group.code,
                    "type": group.type,
                    "selection_mode": group.selection_mode,
                    "min_select": min_select,
                    "max_select": max_select,
                    "is_required": assignment.is_required,
                    "allow_note": group.allow_note,
                    "options": options,
                }
            )

        return Response(
            {
                "artikl_id": artikl.id,
                "modifier_version": _product_versions_for_artikl(artikl)[1],
                "modifier_groups": modifier_groups,
            }
        )


class PosProductBundlePriceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Calculates effective bundle unit price from server base sales price + selected mixers.",
        request=ProductBundlePriceRequestSerializer,
        responses={
            200: ProductBundlePriceResponseSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
        },
    )
    def post(self, request, artikl_id: int):
        artikl = Artikl.objects.filter(id=artikl_id).first()
        if not artikl:
            return Response({"detail": "Artikl ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        serializer = ProductBundlePriceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        modifier_ids = _normalize_modifier_ids(serializer.validated_data.get("modifiers"))
        try:
            _validate_modifier_ids_for_artikl(artikl_id=artikl_id, modifier_ids=modifier_ids)
        except serializers.ValidationError as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_400_BAD_REQUEST)

        if any(option_type != "bundle" for option_type, _option_id, _qty in modifier_ids):
            return Response(
                {"detail": "Bundle price endpoint podržava samo modifiers type=bundle."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        base_unit_price = _active_sales_unit_price_for_artikl(artikl_id)
        if base_unit_price is None:
            return Response(
                {"detail": "Za bundle artikl nema aktivne prodajne cijene."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        mixers_delta = _bundle_options_total_delta(modifier_ids)
        final_unit_price = (base_unit_price + mixers_delta).quantize(Decimal("0.0001"))
        return Response(
            {
                "artikl_id": artikl_id,
                "base_unit_price": base_unit_price,
                "mixers_delta": mixers_delta,
                "final_unit_price": final_unit_price,
                "mixers": _serialize_bundle_breakdown(modifier_ids),
            }
        )


class PosCategoriesDisplayView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _priced_category_ids_for_subtree(root: Category) -> set[int]:
        now = timezone.now()
        return set(
            Artikl.objects.filter(
                is_sellable=True,
                category__isnull=False,
                category__is_active=True,
                category__tree_id=root.tree_id,
                category__lft__gte=root.lft,
                category__rght__lte=root.rght,
                sales_price_items__is_active=True,
                sales_price_items__price_list__is_active=True,
                sales_price_items__price_list__valid_from__lte=now,
            )
            .filter(
                Q(sales_price_items__price_list__valid_to__isnull=True)
                | Q(sales_price_items__price_list__valid_to__gte=now)
            )
            .values_list("category_id", flat=True)
            .distinct()
        )

    @staticmethod
    def _direct_popularity_by_category_for_subtree(*, root: Category, popularity_field: str) -> dict[int, Decimal]:
        now = timezone.now()
        direct_map: dict[int, Decimal] = {}
        priced_rows = (
            Artikl.objects.filter(
                is_sellable=True,
                category__isnull=False,
                category__is_active=True,
                category__tree_id=root.tree_id,
                category__lft__gte=root.lft,
                category__rght__lte=root.rght,
                sales_price_items__is_active=True,
                sales_price_items__price_list__is_active=True,
                sales_price_items__price_list__valid_from__lte=now,
            )
            .filter(
                Q(sales_price_items__price_list__valid_to__isnull=True)
                | Q(sales_price_items__price_list__valid_to__gte=now)
            )
            .annotate(
                popularity_score=Coalesce(
                    F(popularity_field),
                    Value(Decimal("0.0000")),
                    output_field=DecimalField(max_digits=14, decimal_places=4),
                )
            )
            .values_list("category_id", "popularity_score")
        )
        for category_id, popularity_score in priced_rows:
            popularity = Decimal(str(popularity_score or "0.0000")).quantize(Decimal("0.0001"))
            direct_map[category_id] = (direct_map.get(category_id, Decimal("0.0000")) + popularity).quantize(
                Decimal("0.0001")
            )
        return direct_map

    @staticmethod
    def _subtree_popularity_map(*, root: Category, direct_popularity: dict[int, Decimal]) -> dict[int, Decimal]:
        subtree = list(
            Category.objects.filter(
                tree_id=root.tree_id,
                lft__gte=root.lft,
                rght__lte=root.rght,
                is_active=True,
            )
            .only("id", "parent_id", "lft")
            .order_by("lft")
        )
        children_by_parent: dict[int | None, list[int]] = {}
        for category in subtree:
            children_by_parent.setdefault(category.parent_id, []).append(category.id)

        subtree_popularity: dict[int, Decimal] = {}
        for category in reversed(subtree):
            total_popularity = direct_popularity.get(category.id, Decimal("0.0000"))
            for child_id in children_by_parent.get(category.id, []):
                total_popularity += subtree_popularity.get(child_id, Decimal("0.0000"))
            subtree_popularity[category.id] = total_popularity.quantize(Decimal("0.0001"))
        return subtree_popularity

    @classmethod
    def _build_display_payload(cls, *, root: Category | None, mode: str) -> dict:
        popularity_field = (
            "barion_popularity_snapshot__sold_qty_night"
            if mode == "night"
            else "barion_popularity_snapshot__sold_qty_day"
        )
        base_barion_categories = BarionCategory.objects.select_related("category").filter(
            is_active=True,
            category__is_active=True,
        )
        if root is not None:
            base_barion_categories = base_barion_categories.filter(
                category__tree_id=root.tree_id,
                category__lft__gte=root.lft,
                category__rght__lte=root.rght,
            )

        barion_categories = list(base_barion_categories.order_by("sort_order", "category__name", "id"))
        active_barion_nodes = [barion_category.category for barion_category in barion_categories]
        if not active_barion_nodes:
            return {
                "root_id": root.id if root else None,
                "display_level": root.level + 1 if root else 0,
                "categories": [],
            }

        tree_ids = sorted({node.tree_id for node in active_barion_nodes})
        subtree_nodes_qs = Category.objects.filter(
            tree_id__in=tree_ids,
            is_active=True,
        )
        if root is not None:
            subtree_nodes_qs = subtree_nodes_qs.filter(
                lft__gte=root.lft,
                rght__lte=root.rght,
            )
        subtree_nodes = list(
            subtree_nodes_qs.only("id", "parent_id", "lft", "tree_id", "rght", "level").order_by("tree_id", "lft")
        )

        now = timezone.now()
        priced_qs = Artikl.objects.filter(
            is_sellable=True,
            category__isnull=False,
            category__is_active=True,
            category__tree_id__in=tree_ids,
            sales_price_items__is_active=True,
            sales_price_items__price_list__is_active=True,
            sales_price_items__price_list__valid_from__lte=now,
        ).filter(
            Q(sales_price_items__price_list__valid_to__isnull=True)
            | Q(sales_price_items__price_list__valid_to__gte=now)
        )
        if root is not None:
            priced_qs = priced_qs.filter(
                category__lft__gte=root.lft,
                category__rght__lte=root.rght,
            )
        priced_category_ids = set(priced_qs.values_list("category_id", flat=True).distinct())

        direct_popularity: dict[int, Decimal] = {}
        popularity_rows = priced_qs.annotate(
            popularity_score=Coalesce(
                F(popularity_field),
                Value(Decimal("0.0000")),
                output_field=DecimalField(max_digits=14, decimal_places=4),
            )
        ).values_list("category_id", "popularity_score")
        for category_id, popularity_score in popularity_rows:
            popularity = Decimal(str(popularity_score or "0.0000")).quantize(Decimal("0.0001"))
            direct_popularity[category_id] = (
                direct_popularity.get(category_id, Decimal("0.0000")) + popularity
            ).quantize(Decimal("0.0001"))

        categories = []
        for barion_category in barion_categories:
            category = barion_category.category
            delegated_nodes = _delegated_barion_descendants(
                category,
                active_barion_nodes=active_barion_nodes,
            )
            effective_node_ids = [
                node.id
                for node in subtree_nodes
                if _is_category_within_subtree(node, category, include_self=True)
                and not _is_in_delegated_subtree(node, delegated_nodes)
            ]
            if not any(node_id in priced_category_ids for node_id in effective_node_ids):
                continue
            popularity_score = sum(
                (direct_popularity.get(node_id, Decimal("0.0000")) for node_id in effective_node_ids),
                start=Decimal("0.0000"),
            ).quantize(Decimal("0.0001"))
            categories.append(
                {
                    "id": category.id,
                    "name": category.name,
                    "parent_id": category.parent_id,
                    "sort_order": barion_category.sort_order,
                    "popularity_score": popularity_score,
                }
            )
        categories.sort(
            key=lambda row: (
                -Decimal(str(row.get("popularity_score") or "0.0000")),
                int(row.get("sort_order") or 0),
                str(row.get("name") or ""),
                int(row.get("id") or 0),
            )
        )
        return {
            "root_id": root.id if root else None,
            "display_level": root.level + 1 if root else 0,
            "categories": categories,
        }

    @extend_schema(
        description=(
            "Returns display categories for POS by root category. "
            "Selection is active-only and limited to categories explicitly enabled in Barion."
        ),
        parameters=[
            OpenApiParameter(
                name="root_id",
                type=int,
                required=True,
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: PosCategoryDisplayResponseSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
        },
    )
    def get(self, request):
        raw_root_id = request.query_params.get("root_id")
        if not raw_root_id:
            return Response(
                {"detail": "root_id je obavezan query parametar."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            root_id = int(raw_root_id)
        except (TypeError, ValueError):
            return Response({"detail": "root_id mora biti broj."}, status=status.HTTP_400_BAD_REQUEST)

        root = Category.objects.filter(id=root_id, is_active=True).first()
        if not root:
            return Response({"detail": "Aktivna root kategorija ne postoji."}, status=status.HTTP_404_NOT_FOUND)
        try:
            mode, _runtime_mode = _resolve_effective_mode(requested_mode=request.query_params.get("mode"))
        except serializers.ValidationError as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._build_display_payload(root=root, mode=mode))


class PosBootstrapView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            "Returns initial Barion POS catalog state for client startup, "
            "including effective runtime mode, visible categories, and optional products for the first category."
        ),
        parameters=[
            OpenApiParameter(
                name="root_id",
                type=int,
                required=False,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="include_products",
                type=bool,
                required=False,
                location=OpenApiParameter.QUERY,
            ),
        ],
        responses={
            200: PosBootstrapResponseSerializer,
            400: ErrorSerializer,
            404: ErrorSerializer,
        },
    )
    def get(self, request):
        raw_root_id = request.query_params.get("root_id")
        try:
            root = _resolve_root_category(raw_root_id=raw_root_id)
        except serializers.ValidationError as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_400_BAD_REQUEST)
        if raw_root_id not in (None, "") and not root:
            return Response({"detail": "Aktivna root kategorija ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        include_products = str(request.query_params.get("include_products", "")).strip().lower() in {"1", "true", "yes"}
        try:
            mode, _runtime_mode = _resolve_effective_mode(requested_mode=request.query_params.get("mode"))
        except serializers.ValidationError as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_400_BAD_REQUEST)

        display_payload = PosCategoriesDisplayView._build_display_payload(root=root, mode=mode)
        categories = display_payload["categories"]
        selected_category_id = categories[0]["id"] if categories else None
        products = []

        if include_products and selected_category_id is not None:
            selected_category = Category.objects.filter(id=selected_category_id, is_active=True).first()
            if selected_category:
                qs = PosProductSearchView._priced_sellable_queryset()
                qs = PosProductSearchView._apply_category_filter(qs, root_category=selected_category)
                popularity_field = (
                    "barion_popularity_snapshot__sold_qty_night"
                    if mode == "night"
                    else "barion_popularity_snapshot__sold_qty_day"
                )
                qs = qs.annotate(
                    popularity_score=Coalesce(
                        F(popularity_field),
                        Value(Decimal("0.0000")),
                        output_field=DecimalField(max_digits=14, decimal_places=4),
                    )
                ).order_by("-popularity_score", "name", "id")
                products = PosProductSearchView._serialize_products(request=request, qs=qs, limit=100)

        return Response(
            {
                "catalog_version": get_catalog_version(),
                "active_mode": mode,
                "root_id": display_payload["root_id"],
                "display_level": display_payload["display_level"],
                "categories": categories,
                "selected_category_id": selected_category_id,
                "products": products,
            }
        )


class PosCatalogChangesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description=(
            "Returns catalog delta changes for layouts, categories, and products within a stable version window."
        ),
        parameters=[
            OpenApiParameter(name="afterVersion", type=int, required=False, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="limit", type=int, required=False, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="targetVersion", type=int, required=False, location=OpenApiParameter.QUERY),
        ],
        responses={
            200: CatalogChangesResponseSerializer,
            400: ErrorSerializer,
        },
    )
    def get(self, request):
        try:
            after_version = int(request.query_params.get("afterVersion", "0") or "0")
        except (TypeError, ValueError):
            return Response({"detail": "afterVersion mora biti broj."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            limit = int(request.query_params.get("limit", "50") or "50")
        except (TypeError, ValueError):
            return Response({"detail": "limit mora biti broj."}, status=status.HTTP_400_BAD_REQUEST)
        if after_version < 0:
            return Response({"detail": "afterVersion mora biti >= 0."}, status=status.HTTP_400_BAD_REQUEST)
        limit = max(1, min(limit, 200))

        current_version = get_catalog_version()
        raw_target_version = request.query_params.get("targetVersion")
        try:
            target_version = int(raw_target_version) if raw_target_version not in (None, "") else current_version
        except (TypeError, ValueError):
            return Response({"detail": "targetVersion mora biti broj."}, status=status.HTTP_400_BAD_REQUEST)

        if after_version > current_version and raw_target_version in (None, ""):
            empty_entities = {"updated": [], "deleted": []}
            return Response(
                {
                    "requiresFullSync": True,
                    "baseVersion": after_version,
                    "appliedThroughVersion": after_version,
                    "targetVersion": current_version,
                    "catalogVersion": current_version,
                    "layouts": empty_entities,
                    "categories": empty_entities,
                    "products": empty_entities,
                    "hasMore": False,
                }
            )

        if target_version < after_version:
            return Response({"detail": "targetVersion mora biti >= afterVersion."}, status=status.HTTP_400_BAD_REQUEST)
        if target_version > current_version:
            return Response({"detail": "targetVersion ne može biti veći od catalogVersion."}, status=status.HTTP_400_BAD_REQUEST)

        earliest_version = earliest_catalog_event_version()
        requires_full_sync = False
        if after_version > current_version:
            requires_full_sync = True
        elif earliest_version is not None and after_version != 0 and after_version < earliest_version - 1:
            requires_full_sync = True

        empty_entities = {"updated": [], "deleted": []}
        if requires_full_sync:
            return Response(
                {
                    "requiresFullSync": True,
                    "baseVersion": after_version,
                    "appliedThroughVersion": after_version,
                    "targetVersion": current_version,
                    "catalogVersion": current_version,
                    "layouts": empty_entities,
                    "categories": empty_entities,
                    "products": empty_entities,
                    "hasMore": False,
                }
            )

        page_versions = list(
            BarionCatalogSyncEvent.objects.filter(version__gt=after_version, version__lte=target_version)
            .values_list("version", flat=True)
            .order_by("version")
            .distinct()[:limit]
        )
        applied_through_version = int(page_versions[-1]) if page_versions else after_version
        delta_ids = collect_delta_ids(after_version=after_version, target_version=applied_through_version)
        has_more = BarionCatalogSyncEvent.objects.filter(
            version__gt=applied_through_version,
            version__lte=target_version,
        ).exists()

        try:
            mode, _runtime_mode = _resolve_effective_mode(requested_mode=request.query_params.get("mode"))
        except serializers.ValidationError as exc:
            return Response({"detail": str(exc.detail)}, status=status.HTTP_400_BAD_REQUEST)

        layout_ids = sorted(delta_ids.get(BarionCatalogSyncEvent.EntityType.LAYOUT, {}).get("updated", set()))
        category_ids = sorted(delta_ids.get(BarionCatalogSyncEvent.EntityType.CATEGORY, {}).get("updated", set()))
        product_ids = sorted(delta_ids.get(BarionCatalogSyncEvent.EntityType.PRODUCT, {}).get("updated", set()))

        layouts_updated = [
            _serialize_layout_snapshot(layout=layout)
            for layout in Layout.objects.filter(id__in=layout_ids).order_by("id")
        ]

        categories_payload = PosCategoriesDisplayView._build_display_payload(root=None, mode=mode)["categories"]
        categories_updated = [row for row in categories_payload if int(row["id"]) in set(category_ids)]

        products_updated = []
        if product_ids:
            popularity_field = (
                "barion_popularity_snapshot__sold_qty_night"
                if mode == "night"
                else "barion_popularity_snapshot__sold_qty_day"
            )
            qs = (
                PosProductSearchView._priced_sellable_queryset()
                .filter(id__in=product_ids)
                .annotate(
                    popularity_score=Coalesce(
                        F(popularity_field),
                        Value(Decimal("0.0000")),
                        output_field=DecimalField(max_digits=14, decimal_places=4),
                    )
                )
                .order_by("id")
            )
            products_updated = PosProductSearchView._serialize_products(request=request, qs=qs, limit=len(product_ids))

        return Response(
            {
                "requiresFullSync": False,
                "baseVersion": after_version,
                "appliedThroughVersion": applied_through_version,
                "targetVersion": target_version,
                "catalogVersion": target_version,
                "layouts": {
                    "updated": layouts_updated,
                    "deleted": sorted(delta_ids.get(BarionCatalogSyncEvent.EntityType.LAYOUT, {}).get("deleted", set())),
                },
                "categories": {
                    "updated": categories_updated,
                    "deleted": sorted(delta_ids.get(BarionCatalogSyncEvent.EntityType.CATEGORY, {}).get("deleted", set())),
                },
                "products": {
                    "updated": products_updated,
                    "deleted": sorted(delta_ids.get(BarionCatalogSyncEvent.EntityType.PRODUCT, {}).get("deleted", set())),
                },
                "hasMore": has_more,
            }
        )
