import hashlib
import os
from decimal import Decimal

from django.db import transaction
from django.db.models import Case, DecimalField, IntegerField, Max, OuterRef, Q, Subquery, Value, When
from django.db.models import Sum
from django.utils import timezone
from django.utils.http import parse_etags, quote_etag
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework.views import APIView

from artikli.models import Artikl, DrinkCategory
from pos.fiscal import fiscalize_pos_receipt
from pos.models import Pos, PosDevice
from pos.security import is_recent_pin_verified, pin_verify_ttl_seconds
from pos.services import create_pos_receipt
from sales.models import ShiftCashHandover, ShiftTurnover

from .models import Check, CheckItem, Layout, LayoutTable, Table, TableState, UserLayoutAccess


class ErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


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


class PosProductSearchItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    rm_id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField()
    code = serializers.CharField(allow_null=True, allow_blank=True)
    image_46x75 = serializers.CharField(allow_null=True)
    drink_category_id = serializers.IntegerField(allow_null=True)
    drink_category_name = serializers.CharField(allow_null=True)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=4, allow_null=True)


class PosDrinkCategoryDisplayItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    parent_id = serializers.IntegerField(allow_null=True)
    sort_order = serializers.IntegerField()


class PosDrinkCategoryDisplayResponseSerializer(serializers.Serializer):
    root_id = serializers.IntegerField()
    display_level = serializers.IntegerField()
    categories = PosDrinkCategoryDisplayItemSerializer(many=True)


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
    receipt_id = serializers.IntegerField()
    receipt_number = serializers.IntegerField()
    status = serializers.CharField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    zki = serializers.CharField()
    jir = serializers.CharField()
    qr = serializers.CharField()


class SendCheckToBarResponseSerializer(serializers.Serializer):
    check_id = serializers.IntegerField()
    round_number = serializers.IntegerField()
    sent_items_count = serializers.IntegerField()
    sent_at = serializers.DateTimeField()
    ticket = serializers.JSONField()


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
                check = Check.objects.create(
                    table_id=table_id,
                    status=Check.Status.OPEN,
                    opened_by=request.user,
                )
                created = True

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
        if os.getenv("BARION_BAR_PRINTER_ENABLED", "true").lower() in {"0", "false", "no", "off"}:
            raise RuntimeError("Bar printer nije konfiguriran.")
        if os.getenv("BARION_BAR_PRINTER_FAIL", "false").lower() in {"1", "true", "yes", "on"}:
            raise RuntimeError("Greška pri slanju na bar printer.")
        # V1: printer integration is adapter-ready. Current deployment uses no-op success.
        _ = ticket

    @staticmethod
    def _build_ticket_payload(*, request, check: Check, round_number: int, sent_items: list[CheckItem], sent_at):
        waiter_name = request.user.get_full_name().strip() or request.user.username
        return {
            "venue_name": os.getenv("BARION_VENUE_NAME", "Mozart"),
            "table_label": check.table.label,
            "check_id": check.id,
            "round_number": round_number,
            "waiter": waiter_name,
            "sent_at": sent_at.isoformat(),
            "items": [
                {
                    "id": item.id,
                    "artikl_id": item.artikl_id,
                    "artikl_name": item.artikl.name,
                    "quantity": item.quantity,
                    "note": item.note,
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
                description="Runda uspješno poslana na šank.",
            ),
            404: OpenApiResponse(response=ErrorSerializer, description="Check ne postoji."),
            409: OpenApiResponse(response=ErrorSerializer, description="Nema novih stavki ili check nije OPEN."),
            503: OpenApiResponse(response=ErrorSerializer, description="Greška printera ili printer nije konfiguriran."),
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
                "Printer error 503",
                value={"detail": "Greška pri slanju na bar printer."},
                response_only=True,
                status_codes=["503"],
            ),
        ],
    )
    def post(self, request, check_id: int):
        try:
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
                    CheckItem.objects.select_for_update().select_related("artikl")
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
                self._send_ticket_to_printer(ticket)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(
            {
                "check_id": check.id,
                "round_number": next_round,
                "sent_items_count": len(unsent_items),
                "sent_at": sent_at.isoformat(),
                "ticket": ticket,
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

            if check.pos_receipt_id:
                receipt = check.pos_receipt
                return Response(
                    {
                        "check_id": check.id,
                        "receipt_id": receipt.id,
                        "receipt_number": receipt.receipt_number,
                        "status": receipt.status,
                        "total_amount": receipt.total_amount,
                        "zki": receipt.zki,
                        "jir": receipt.jir,
                        "qr": receipt.qr_payload,
                    }
                )

            if check.status != Check.Status.OPEN:
                return Response(
                    {"detail": "Check nije otvoren pa nije moguće izdati račun."},
                    status=status.HTTP_409_CONFLICT,
                )

            check_items = list(check.items.select_related("artikl").order_by("id"))
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

            check.status = Check.Status.CLOSED
            check.closed_at = timezone.now()
            check.closed_by = request.user
            check.pos_receipt = receipt
            check.save(update_fields=["status", "closed_at", "closed_by", "pos_receipt", "updated_at"])

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
                "check_id": check.id,
                "receipt_id": receipt.id,
                "receipt_number": receipt.receipt_number,
                "status": receipt.status,
                "total_amount": receipt.total_amount,
                "zki": receipt.zki,
                "jir": receipt.jir,
                "qr": receipt.qr_payload,
            }
        )


class PosCheckItemsView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _serialize_item(item: CheckItem) -> dict:
        return {
            "id": item.id,
            "check_id": item.barion_check_id,
            "artikl_id": item.artikl_id,
            "artikl_name": item.artikl.name,
            "quantity": item.quantity,
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
        }

    @staticmethod
    def _get_totals(check: Check) -> dict:
        agg = check.items.aggregate(
            net_amount=Sum("net_amount"),
            vat_amount=Sum("vat_amount"),
            total_amount=Sum("total_amount"),
        )
        return {
            "items_count": check.items.count(),
            "net_amount": agg["net_amount"] or Decimal("0.00"),
            "vat_amount": agg["vat_amount"] or Decimal("0.00"),
            "total_amount": agg["total_amount"] or Decimal("0.00"),
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

        items = list(check.items.select_related("artikl").order_by("id"))
        return Response(
            {
                "check_id": check.id,
                "status": check.status,
                "items": [self._serialize_item(item) for item in items],
                "totals": self._get_totals(check),
            }
        )

    @extend_schema(
        description="Adds NORMAL item to OPEN check.",
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

        with transaction.atomic():
            check = Check.objects.select_for_update().filter(id=check_id).first()
            if not check:
                return Response({"detail": "Check ne postoji."}, status=status.HTTP_404_NOT_FOUND)
            if check.status != Check.Status.OPEN:
                return Response(
                    {"detail": "Nije moguće dodati stavku na zatvoreni check."},
                    status=status.HTTP_409_CONFLICT,
                )

            artikl_id = data["artikl_id"]
            artikl = Artikl.objects.filter(id=artikl_id).first()
            if not artikl:
                return Response({"detail": "Artikl ne postoji."}, status=status.HTTP_404_NOT_FOUND)

            check_item = CheckItem.objects.create(
                barion_check=check,
                artikl=artikl,
                quantity=data["quantity"],
                unit_price=data["unit_price"],
                vat_rate=data.get("vat_rate", Decimal("0.0000")),
                note=data.get("note", ""),
            )

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
        return {
            "id": item.id,
            "check_id": item.barion_check_id,
            "artikl_id": item.artikl_id,
            "artikl_name": item.artikl.name,
            "quantity": item.quantity,
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
        }

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

            for field in ("quantity", "unit_price", "vat_rate", "note"):
                if field in data:
                    setattr(item, field, data[field])
            item.save()

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
            source_qty = abs(Decimal(str(item.quantity)))
            available_qty = source_qty - already_storno_qty
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
            source_qty = Decimal(str(item.quantity))
            if source_qty <= 0:
                return Response(
                    {"detail": "Gratis je moguće primijeniti samo na pozitivnu količinu."},
                    status=status.HTTP_409_CONFLICT,
                )

            storno_applied_qty = PosCheckItemStornoView._storno_applied_qty(
                check_id=item.barion_check_id,
                item_id=item.id,
            )
            available_qty = source_qty - storno_applied_qty
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

            if apply_qty == source_qty:
                item.unit_price = Decimal("0.0000")
                item.line_type = CheckItem.LineType.GRATIS
                if reason:
                    item.note = f"{item.note} [gratis] {reason}".strip()
                item.save()
                return Response(PosCheckItemDetailView._serialize_item(item))

            # Partial gratis: split source line and create separate GRATIS line.
            item.quantity = source_qty - apply_qty
            item.save()
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

            source_qty = Decimal(str(item.quantity))
            if source_qty <= 0:
                return Response(
                    {"detail": "Otpis je moguće primijeniti samo na pozitivnu količinu."},
                    status=status.HTTP_409_CONFLICT,
                )

            storno_applied_qty = PosCheckItemStornoView._storno_applied_qty(
                check_id=item.barion_check_id,
                item_id=item.id,
            )
            available_qty = source_qty - storno_applied_qty
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

            if apply_qty == source_qty:
                item.unit_price = Decimal("0.0000")
                item.line_type = CheckItem.LineType.OTPIS
                if reason:
                    item.note = f"{item.note} [otpis] {reason}".strip()
                item.save()
                return Response(PosCheckItemDetailView._serialize_item(item))

            item.quantity = source_qty - apply_qty
            item.save()
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
            Artikl.objects.select_related("drink_category", "tax_group")
            .annotate(
                active_unit_price=Subquery(
                    active_price_subquery,
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
            .filter(is_sellable=True, active_unit_price__isnull=False)
            .filter(Q(drink_category__isnull=True) | Q(drink_category__is_active=True))
        )

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
                name="drink_category_id",
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

        raw_drink_category_id = request.query_params.get("drink_category_id")
        if raw_drink_category_id not in (None, ""):
            try:
                drink_category_id = int(raw_drink_category_id)
            except (TypeError, ValueError):
                return Response({"detail": "drink_category_id mora biti broj."}, status=status.HTTP_400_BAD_REQUEST)
            root_category = DrinkCategory.objects.filter(id=drink_category_id, is_active=True).first()
            if not root_category:
                return Response([])
            qs = qs.filter(
                drink_category__tree_id=root_category.tree_id,
                drink_category__lft__gte=root_category.lft,
                drink_category__rght__lte=root_category.rght,
            )

        q = (request.query_params.get("q") or "").strip()
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
            ).order_by("rank", "name", "id")
        else:
            qs = qs.order_by("name", "id")

        rows = []
        for artikl in qs[:limit]:
            image_46x75 = None
            if artikl.image and artikl.rm_id is not None:
                path = f"/api/artikli/{artikl.rm_id}/image-46x75/"
                image_46x75 = request.build_absolute_uri(path)
            rows.append(
                {
                    "id": artikl.id,
                    "rm_id": artikl.rm_id,
                    "name": artikl.name,
                    "code": artikl.code,
                    "image_46x75": image_46x75,
                    "drink_category_id": artikl.drink_category_id,
                    "drink_category_name": artikl.drink_category.name if artikl.drink_category_id else None,
                    "unit_price": artikl.active_unit_price,
                    "tax_rate": artikl.tax_group.rate if artikl.tax_group_id else None,
                }
            )
        return Response(rows)


class PosDrinkCategoriesDisplayView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _priced_category_ids_for_subtree(root: DrinkCategory) -> set[int]:
        now = timezone.now()
        return set(
            Artikl.objects.filter(
                is_sellable=True,
                drink_category__isnull=False,
                drink_category__is_active=True,
                drink_category__tree_id=root.tree_id,
                drink_category__lft__gte=root.lft,
                drink_category__rght__lte=root.rght,
                sales_price_items__is_active=True,
                sales_price_items__price_list__is_active=True,
                sales_price_items__price_list__valid_from__lte=now,
            )
            .filter(
                Q(sales_price_items__price_list__valid_to__isnull=True)
                | Q(sales_price_items__price_list__valid_to__gte=now)
            )
            .values_list("drink_category_id", flat=True)
            .distinct()
        )

    @extend_schema(
        description=(
            "Returns display drink categories for POS by root category. "
            "Selection is active-only and prefers deepest available level with sellable products that have active sales price."
        ),
        parameters=[
            OpenApiParameter(
                name="root_id",
                type=int,
                required=True,
                location=OpenApiParameter.QUERY,
            )
        ],
        responses={
            200: PosDrinkCategoryDisplayResponseSerializer,
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

        root = DrinkCategory.objects.filter(id=root_id, is_active=True).first()
        if not root:
            return Response({"detail": "Aktivna root kategorija ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        subtree = list(
            DrinkCategory.objects.filter(
                tree_id=root.tree_id,
                lft__gte=root.lft,
                rght__lte=root.rght,
                is_active=True,
            )
            .only("id", "name", "parent_id", "sort_order", "level", "lft")
            .order_by("lft")
        )
        if not subtree:
            return Response({"root_id": root.id, "display_level": root.level + 1, "categories": []})

        priced_category_ids = self._priced_category_ids_for_subtree(root)

        children_by_parent: dict[int | None, list[int]] = {}
        for category in subtree:
            children_by_parent.setdefault(category.parent_id, []).append(category.id)

        has_products_in_subtree: dict[int, bool] = {}
        for category in reversed(subtree):
            own_products = category.id in priced_category_ids
            child_products = any(
                has_products_in_subtree.get(child_id, False)
                for child_id in children_by_parent.get(category.id, [])
            )
            has_products_in_subtree[category.id] = own_products or child_products

        visible_descendant_levels = sorted(
            {
                category.level
                for category in subtree
                if category.id != root.id and has_products_in_subtree.get(category.id, False)
            },
            reverse=True,
        )
        if visible_descendant_levels:
            target_level = visible_descendant_levels[0]
        elif has_products_in_subtree.get(root.id, False):
            target_level = root.level
        else:
            target_level = root.level

        categories = [
            {
                "id": category.id,
                "name": category.name,
                "parent_id": category.parent_id,
                "sort_order": category.sort_order,
            }
            for category in subtree
            if category.level == target_level and has_products_in_subtree.get(category.id, False)
        ]

        return Response(
            {
                "root_id": root.id,
                "display_level": target_level + 1,
                "categories": categories,
            }
        )
