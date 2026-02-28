import os
from decimal import Decimal

from django.db import models
from django.db.models import Max
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers

from configuration.models import CompanyProfile
from accounting.models import JournalEntry, JournalItem
from accounting.services import get_single_ledger, get_account_by_code, get_default_cash_account
from sales.models import SalesInvoice, ShiftTurnover, ShiftTurnoverClose, ShiftTurnoverExpense, ShiftCashHandover
from sales.fiscal import fiscalize_sales_invoice
from stock.models import WarehouseId
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from django.http import HttpResponse
from reportlab.lib.utils import ImageReader
from django.utils import timezone
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from pos.services import create_pos_receipt, create_pos_storno
from pos.fiscal import fiscalize_pos_receipt
from pos.models import PosReceipt, Pos, PosDevice, PosPrinterInventory
from pos.security import is_recent_pin_verified, mark_pin_verified, pin_verify_ttl_seconds
from rest_framework.authtoken.models import Token
from sales.remaris_importer import import_sales_invoices, load_import_defaults
from sales.services import resolve_waiter_user


class PosSerializer(serializers.ModelSerializer):
    warehouse = serializers.SlugRelatedField(
        slug_field="rm_id",
        queryset=WarehouseId.objects.all(),
    )

    class Meta:
        model = Pos
        fields = ("id", "external_pos_id", "name", "platform", "warehouse", "is_active", "config")


CASH_SHORTAGE_ACCOUNT_CODE = "4699"
CASH_SURPLUS_ACCOUNT_CODE = "7815"


class PosDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PosDevice
        fields = (
            "id",
            "device_id",
            "pos",
            "name",
            "is_active",
            "print_receiver_url",
            "receipt_printer",
            "bar_printer",
            "registered_at",
        )


class PosPrinterInventorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PosPrinterInventory
        fields = (
            "id",
            "device",
            "name",
            "is_default",
            "status",
            "is_active",
            "last_seen_at",
            "raw_payload",
            "created_at",
            "updated_at",
        )


class PosPrinterSyncPrinterRowSerializer(serializers.Serializer):
    name = serializers.CharField(required=True, trim_whitespace=True)
    is_default = serializers.BooleanField(required=False, default=False)
    status = serializers.CharField(required=False, allow_blank=True, default="")
    raw = serializers.JSONField(required=False, default=dict)


class PosPrinterSyncRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(required=True, trim_whitespace=True)
    receiver_url = serializers.CharField(required=True, trim_whitespace=True)
    printers = PosPrinterSyncPrinterRowSerializer(many=True, required=True)


class PosDevicePrinterSelectionRequestSerializer(serializers.Serializer):
    receipt_printer_id = serializers.IntegerField(required=False, allow_null=True)
    bar_printer_id = serializers.IntegerField(required=False, allow_null=True)
    receiver_url = serializers.CharField(required=False, allow_blank=True)


class PosPinVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    class VerifyRequestSerializer(serializers.Serializer):
        pin = serializers.CharField(required=True, trim_whitespace=True)

    class VerifySuccessSerializer(serializers.Serializer):
        ok = serializers.BooleanField()
        verified_for_seconds = serializers.IntegerField()

    class VerifyErrorSerializer(serializers.Serializer):
        detail = serializers.CharField()
        cooldown_seconds = serializers.IntegerField(required=False)

    @extend_schema(
        description=(
            "Verify PIN for currently authenticated user. "
            "Used for step-up confirmation in sensitive POS actions."
        ),
        request=VerifyRequestSerializer,
        responses={
            200: VerifySuccessSerializer,
            400: VerifyErrorSerializer,
            423: VerifyErrorSerializer,
        },
    )
    def post(self, request):
        pin = str(request.data.get("pin", "")).strip()
        if not pin:
            return Response({"detail": "PIN je obavezan."}, status=status.HTTP_400_BAD_REQUEST)

        profile = getattr(request.user, "pos_profile", None)
        if not profile or not profile.pin_hash:
            return Response({"detail": "PIN nije postavljen."}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        if profile.pin_locked_until and profile.pin_locked_until > now:
            seconds = int((profile.pin_locked_until - now).total_seconds())
            return Response(
                {"detail": "PIN je privremeno zaključan.", "cooldown_seconds": seconds},
                status=status.HTTP_423_LOCKED,
            )

        if not profile.check_pin(pin):
            profile.pin_fail_count += 1
            if profile.pin_fail_count >= 5:
                profile.pin_locked_until = now + timezone.timedelta(minutes=5)
                profile.pin_fail_count = 0
            profile.save(update_fields=["pin_fail_count", "pin_locked_until"])
            return Response({"detail": "Neispravan PIN."}, status=status.HTTP_400_BAD_REQUEST)

        if profile.pin_fail_count or profile.pin_locked_until:
            profile.pin_fail_count = 0
            profile.pin_locked_until = None
            profile.save(update_fields=["pin_fail_count", "pin_locked_until"])
        mark_pin_verified(profile)
        return Response({"ok": True, "verified_for_seconds": pin_verify_ttl_seconds()})


def _require_recent_pin_verify(request):
    ok, remaining = is_recent_pin_verified(request.user)
    if ok:
        return None
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


class PosPinLoginView(APIView):
    permission_classes = [AllowAny]
    # Token-based login endpoint: disable session auth to avoid CSRF requirements when browser has a session cookie.
    authentication_classes = []

    class LoginRequestSerializer(serializers.Serializer):
        pin = serializers.CharField(required=True, trim_whitespace=True)
        username = serializers.CharField(required=False, allow_blank=True)
        device_id = serializers.CharField(required=False, allow_blank=True)

    class LoginSuccessSerializer(serializers.Serializer):
        token = serializers.CharField()
        user_id = serializers.IntegerField()
        username = serializers.CharField()

    class LoginErrorSerializer(serializers.Serializer):
        detail = serializers.CharField()
        cooldown_seconds = serializers.IntegerField(required=False)

    @extend_schema(
        description=(
            "PIN login for POS devices. Uses DRF token auth and does not require CSRF."
        ),
        request=LoginRequestSerializer,
        responses={
            200: LoginSuccessSerializer,
            400: LoginErrorSerializer,
            403: LoginErrorSerializer,
            423: LoginErrorSerializer,
        },
    )

    def post(self, request):
        pin = str(request.data.get("pin", "")).strip()
        username = str(request.data.get("username", "")).strip()
        device_id = str(request.data.get("device_id", "")).strip()
        if not pin:
            return Response({"detail": "PIN je obavezan."}, status=status.HTTP_400_BAD_REQUEST)

        if username:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            user = User.objects.filter(username=username).first()
            profile = getattr(user, "pos_profile", None) if user else None
            if not profile or not profile.pin_hash:
                return Response({"detail": "PIN nije postavljen."}, status=status.HTTP_400_BAD_REQUEST)

            now = timezone.now()
            if profile.pin_locked_until and profile.pin_locked_until > now:
                seconds = int((profile.pin_locked_until - now).total_seconds())
                return Response(
                    {"detail": "PIN je privremeno zaključan.", "cooldown_seconds": seconds},
                    status=status.HTTP_423_LOCKED,
                )
            if not profile.check_pin(pin):
                profile.pin_fail_count += 1
                if profile.pin_fail_count >= 5:
                    profile.pin_locked_until = now + timezone.timedelta(minutes=5)
                    profile.pin_fail_count = 0
                profile.save(update_fields=["pin_fail_count", "pin_locked_until"])
                return Response({"detail": "Neispravan PIN."}, status=status.HTTP_400_BAD_REQUEST)

            if profile.is_registered:
                if not device_id or profile.registered_device_id != device_id:
                    return Response({"detail": "POS profil je registriran na drugi uredaj."}, status=status.HTTP_403_FORBIDDEN)
            elif device_id:
                profile.is_registered = True
                profile.registered_device_id = device_id
                profile.registered_at = timezone.now()
                profile.save(update_fields=["is_registered", "registered_device_id", "registered_at"])

            if profile.pin_fail_count or profile.pin_locked_until:
                profile.pin_fail_count = 0
                profile.pin_locked_until = None
                profile.save(update_fields=["pin_fail_count", "pin_locked_until"])
            token, _ = Token.objects.get_or_create(user=user)
            return Response({"token": token.key, "user_id": user.id, "username": user.username})

        try:
            from pos.models import PosProfile

            profiles = PosProfile.objects.select_related("user").exclude(pin_hash="")
        except Exception:
            profiles = []

        for profile in profiles:
            if profile.is_registered:
                if not device_id or profile.registered_device_id != device_id:
                    continue
            now = timezone.now()
            if profile.pin_locked_until and profile.pin_locked_until > now:
                continue
            if profile.check_pin(pin):
                if not profile.is_registered and device_id:
                    profile.is_registered = True
                    profile.registered_device_id = device_id
                    profile.registered_at = timezone.now()
                    profile.save(update_fields=["is_registered", "registered_device_id", "registered_at"])
                if profile.pin_fail_count or profile.pin_locked_until:
                    profile.pin_fail_count = 0
                    profile.pin_locked_until = None
                    profile.save(update_fields=["pin_fail_count", "pin_locked_until"])
                token, _ = Token.objects.get_or_create(user=profile.user)
                return Response(
                    {
                        "token": token.key,
                        "user_id": profile.user_id,
                        "username": profile.user.username,
                    }
                )

        return Response({"detail": "Neispravan PIN."}, status=status.HTTP_400_BAD_REQUEST)


class PosFiscalizeInvoiceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        invoice_id = request.data.get("invoice_id")
        if not invoice_id:
            return Response({"detail": "invoice_id je obavezan."}, status=status.HTTP_400_BAD_REQUEST)

        invoice = SalesInvoice.objects.filter(id=invoice_id).first()
        if not invoice:
            return Response({"detail": "Račun ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        try:
            receipt = fiscalize_sales_invoice(invoice, user=request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "invoice_id": invoice.id,
                "status": receipt.status,
                "zki": receipt.zki,
                "jir": receipt.jir,
                "qr": receipt.qr_payload,
            }
        )


class PosReceiptCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        verify_error = _require_recent_pin_verify(request)
        if verify_error:
            return verify_error

        items = request.data.get("items") or []
        if not isinstance(items, list) or not items:
            return Response({"detail": "items su obavezne."}, status=status.HTTP_400_BAD_REQUEST)

        office_code = request.data.get("office_code") or os.getenv("FISCAL_OFFICE_CODE", "POS1")
        device_code = request.data.get("device_code") or os.getenv("FISCAL_DEVICE_CODE", "1")
        payment_type = request.data.get("payment_type") or "cash"

        pos_id = request.data.get("pos_id")
        warehouse_rm_id = request.data.get("warehouse_id")
        device_id = str(request.data.get("device_id", "") or "").strip()

        pos = Pos.objects.filter(id=pos_id).first() if pos_id else None
        if not pos and device_id:
            # TouchPOS typically knows its device_id; resolve the POS/warehouse from PosDevice mapping.
            device = (
                PosDevice.objects.select_related("pos", "pos__warehouse")
                .filter(device_id=device_id, is_active=True, pos__is_active=True)
                .first()
            )
            if device:
                pos = device.pos

        if warehouse_rm_id:
            warehouse = WarehouseId.objects.filter(rm_id=warehouse_rm_id).first()
        elif pos and pos.warehouse_id:
            warehouse = pos.warehouse
        else:
            warehouse = None

        issued_on = timezone.localdate()
        turnover = ShiftTurnover.objects.filter(
            issued_on=issued_on,
            user=request.user,
            warehouse_id=warehouse.id if warehouse else None,
            pos_id=pos.id if pos else None,
        ).first()
        if not turnover:
            turnover = ShiftTurnover.objects.create(
                issued_on=issued_on,
                user=request.user,
                warehouse_id=warehouse.id if warehouse else None,
                pos_id=pos.id if pos else None,
                total_amount=Decimal("0.00"),
                invoice_count=0,
                invoice_ids=[],
            )
        # Cash handover/opening enforcement can be enabled later; keep it behind a flag for now.
        if os.getenv("POS_REQUIRE_OPENING", "false").lower() in ("1", "true", "yes", "on"):
            opening = (
                turnover.cash_handovers.filter(kind=ShiftCashHandover.Kind.OPENING)
                .order_by("-created_at")
                .first()
            )
            if not opening:
                return Response(
                    {
                        "detail": "Preuzimanje blagajne je obavezno prije rada.",
                        "opening_required": True,
                        "turnover_id": turnover.id,
                    },
                    status=status.HTTP_423_LOCKED,
                )

        try:
            receipt = create_pos_receipt(
                office_code=office_code,
                device_code=device_code,
                payment_type=payment_type,
                items=items,
                operator=request.user,
                pos=pos,
                warehouse=warehouse,
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "receipt_id": receipt.id,
                "receipt_number": receipt.receipt_number,
                "issued_at": receipt.issued_at,
                "total_amount": receipt.total_amount,
                "net_amount": receipt.net_amount,
                "vat_amount": receipt.vat_amount,
                "currency": receipt.currency,
                "status": receipt.status,
            }
        )


class PosReceiptFiscalizeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, receipt_id: int):
        verify_error = _require_recent_pin_verify(request)
        if verify_error:
            return verify_error

        receipt = PosReceipt.objects.filter(id=receipt_id).first()
        if not receipt:
            return Response({"detail": "Račun ne postoji."}, status=status.HTTP_404_NOT_FOUND)
        try:
            receipt = fiscalize_pos_receipt(receipt)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "receipt_id": receipt.id,
                "status": receipt.status,
                "zki": receipt.zki,
                "jir": receipt.jir,
                "qr": receipt.qr_payload,
            }
        )


class PosReceiptStornoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, receipt_id: int):
        verify_error = _require_recent_pin_verify(request)
        if verify_error:
            return verify_error

        original = PosReceipt.objects.filter(id=receipt_id).first()
        if not original:
            return Response({"detail": "Račun ne postoji."}, status=status.HTTP_404_NOT_FOUND)
        try:
            storno = create_pos_storno(original=original, operator=request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "receipt_id": storno.id,
                "receipt_number": storno.receipt_number,
                "status": storno.status,
                "total_amount": storno.total_amount,
            }
        )


class PosReceiptPrintView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, receipt_id: int):
        receipt = PosReceipt.objects.filter(id=receipt_id).prefetch_related("items", "barion_settlement_parts").first()
        if not receipt:
            return Response({"detail": "Račun ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        payment_type_raw = str(receipt.payment_type or "").strip().lower()
        payment_type_label = "Kartica" if payment_type_raw == "card" else "Gotovina"
        card_masked_pan = ""
        card_brand = ""
        if payment_type_raw == "card":
            card_masked_pan = (
                receipt.barion_settlement_parts.exclude(card_masked_pan="")
                .order_by("-id")
                .values_list("card_masked_pan", flat=True)
                .first()
                or ""
            )
            card_brand = (
                receipt.barion_settlement_parts.exclude(card_brand="")
                .order_by("-id")
                .values_list("card_brand", flat=True)
                .first()
                or ""
            )

        tip_total = sum(
            (part.tip_amount or Decimal("0.00")) for part in receipt.barion_settlement_parts.all()
        ).quantize(Decimal("0.01"))
        show_tip = tip_total > Decimal("0.00")

        # Thermal roll: 80mm width, dynamic height
        line_h = 4 * mm
        company = CompanyProfile.objects.first()
        address = ""
        if company:
            address = " ".join(part for part in [company.address, company.postal_code, company.city] if part)
        header_lines = 4  # title + receipt number + date + payment type
        if card_masked_pan:
            header_lines += 1
        if address:
            header_lines += 1
        if company and company.oib:
            header_lines += 1
        header_h = (header_lines + 1) * line_h
        totals_h = (20 + (4 if show_tip else 0)) * mm
        qr_h = 35 * mm if receipt.qr_payload else 0
        items_h = max(1, receipt.items.count()) * line_h
        height = header_h + items_h + totals_h + qr_h + 10 * mm
        width = 80 * mm

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=(width, height))

        font_regular = "Helvetica"
        font_bold = "Helvetica-Bold"
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
            font_regular = "DejaVuSans"
            font_bold = "DejaVuSans-Bold"
        except Exception:
            pass

        x_left = 4 * mm
        x_right = width - 4 * mm

        y = height - 6 * mm
        c.setFont(font_bold, 9)
        c.drawString(x_left, y, company.name if company else "POS račun")
        y -= line_h
        c.setFont(font_regular, 8)
        if address:
            c.drawString(x_left, y, address)
            y -= line_h
        if company and company.oib:
            c.drawString(x_left, y, f"OIB: {company.oib}")
            y -= line_h
        c.drawString(
            x_left,
            y,
            f"Broj: {receipt.receipt_number}/{receipt.office_code}/{receipt.device_code}",
        )
        y -= line_h
        c.drawString(x_left, y, f"Datum: {receipt.issued_at:%d.%m.%Y %H:%M}")
        y -= line_h
        c.drawString(x_left, y, f"Placanje: {payment_type_label}")
        y -= line_h
        if card_masked_pan:
            brand_label = card_brand or "Kartica"
            c.drawString(x_left, y, f"{brand_label}: {card_masked_pan}")
            y -= line_h

        c.setFont(font_bold, 8)
        c.drawString(x_left, y, "Artikl")
        c.drawRightString(x_right, y, "Iznos")
        y -= line_h
        c.setFont(font_regular, 8)
        for item in receipt.items.all():
            c.drawString(x_left, y, f"{item.product_name} x {item.quantity}")
            c.drawRightString(x_right, y, f"{item.total_amount:.2f}")
            y -= line_h

        y -= line_h
        c.setFont(font_bold, 8)
        c.drawRightString(x_right, y, f"Net: {receipt.net_amount:.2f}")
        y -= line_h
        c.drawRightString(x_right, y, f"PDV: {receipt.vat_amount:.2f}")
        y -= line_h
        c.drawRightString(x_right, y, f"Ukupno: {receipt.total_amount:.2f} {receipt.currency}")
        y -= line_h
        if show_tip:
            c.drawRightString(x_right, y, f"Tip: {tip_total:.2f} {receipt.currency}")
            y -= line_h

        if receipt.zki:
            c.setFont(font_regular, 7)
            c.drawString(x_left, y, f"ZKI: {receipt.zki}")
            y -= line_h
        if receipt.jir:
            c.drawString(x_left, y, f"JIR: {receipt.jir}")
            y -= line_h

        if receipt.qr_payload:
            try:
                import qrcode

                qr_img = qrcode.make(receipt.qr_payload)
                qr_buffer = BytesIO()
                qr_img.save(qr_buffer, format="PNG")
                qr_buffer.seek(0)
                qr_reader = ImageReader(qr_buffer)
                c.drawImage(qr_reader, x_left, y - 30 * mm, width=28 * mm, height=28 * mm)
                y -= 34 * mm
            except Exception:
                pass

        c.showPage()
        c.save()
        pdf = buffer.getvalue()
        buffer.close()

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="pos-receipt-{receipt.id}.pdf"'
        return response


class PosListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PosSerializer(many=True)})
    def get(self, request):
        qs = Pos.objects.all().order_by("name", "id")
        return Response(PosSerializer(qs, many=True).data)

    @extend_schema(request=PosSerializer, responses={201: PosSerializer})
    def post(self, request):
        serializer = PosSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pos = serializer.save()
        device_id = str(request.data.get("device_id", "") or "").strip()
        if not device_id:
            device_id = str(pos.external_pos_id)
        if device_id:
            PosDevice.objects.update_or_create(
                device_id=device_id,
                defaults={"pos": pos, "name": pos.name},
            )
        return Response(PosSerializer(pos).data, status=status.HTTP_201_CREATED)


class PosDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_pos(self, pos_id):
        return Pos.objects.filter(id=pos_id).first()

    @extend_schema(responses={200: PosSerializer})
    def get(self, request, pos_id):
        pos = self._get_pos(pos_id)
        if not pos:
            return Response({"detail": "POS nije pronađen."}, status=status.HTTP_404_NOT_FOUND)
        return Response(PosSerializer(pos).data)

    @extend_schema(request=PosSerializer, responses={200: PosSerializer})
    def patch(self, request, pos_id):
        pos = self._get_pos(pos_id)
        if not pos:
            return Response({"detail": "POS nije pronađen."}, status=status.HTTP_404_NOT_FOUND)
        serializer = PosSerializer(pos, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        pos = serializer.save()
        return Response(PosSerializer(pos).data)


class PosPrinterSyncView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _resolve_device_for_user(*, user, device_id: str):
        device = (
            PosDevice.objects.select_related("pos")
            .filter(device_id=device_id, is_active=True, pos__is_active=True)
            .first()
        )
        if not device:
            return None, Response({"detail": "Uređaj nije pronađen ili nije aktivan."}, status=status.HTTP_404_NOT_FOUND)

        profile = getattr(user, "pos_profile", None)
        if profile and profile.is_registered and profile.registered_device_id and profile.registered_device_id != device_id:
            return None, Response({"detail": "Korisnik nije registriran za ovaj uređaj."}, status=status.HTTP_403_FORBIDDEN)
        return device, None

    def post(self, request):
        serializer = PosPrinterSyncRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        device_id = str(data["device_id"]).strip()
        device, error = self._resolve_device_for_user(user=request.user, device_id=device_id)
        if error:
            return error

        receiver_url = str(data["receiver_url"]).strip()
        printer_rows = data.get("printers") or []
        now = timezone.now()

        seen_ids: list[int] = []
        upserted_count = 0
        for row in printer_rows:
            name = str(row.get("name", "")).strip()
            if not name:
                continue
            defaults = {
                "is_default": bool(row.get("is_default", False)),
                "status": str(row.get("status", "") or "").strip(),
                "is_active": True,
                "last_seen_at": now,
                "raw_payload": row.get("raw") or {},
            }
            printer, _ = PosPrinterInventory.objects.update_or_create(
                device=device,
                name=name,
                defaults=defaults,
            )
            seen_ids.append(printer.id)
            upserted_count += 1

        inactive_qs = device.printers.filter(is_active=True)
        if seen_ids:
            inactive_qs = inactive_qs.exclude(id__in=seen_ids)
        inactive_ids = list(inactive_qs.values_list("id", flat=True))
        inactive_count = inactive_qs.update(is_active=False)

        update_fields = []
        if device.print_receiver_url != receiver_url:
            device.print_receiver_url = receiver_url
            update_fields.append("print_receiver_url")
        if device.receipt_printer_id and device.receipt_printer_id in inactive_ids:
            device.receipt_printer = None
            update_fields.append("receipt_printer")
        if device.bar_printer_id and device.bar_printer_id in inactive_ids:
            device.bar_printer = None
            update_fields.append("bar_printer")
        if update_fields:
            device.save(update_fields=update_fields)

        return Response(
            {
                "device_id": device.device_id,
                "upserted_count": upserted_count,
                "inactive_count": inactive_count,
                "active_printer_ids": seen_ids,
            }
        )


class PosPrinterListView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _as_bool(value, *, default=False) -> bool:
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def get(self, request):
        device_id = str(request.GET.get("device_id", "") or "").strip()
        if not device_id:
            return Response({"detail": "device_id je obavezan."}, status=status.HTTP_400_BAD_REQUEST)

        device = (
            PosDevice.objects.select_related("pos")
            .filter(device_id=device_id, is_active=True, pos__is_active=True)
            .first()
        )
        if not device:
            return Response({"detail": "Uređaj nije pronađen ili nije aktivan."}, status=status.HTTP_404_NOT_FOUND)

        profile = getattr(request.user, "pos_profile", None)
        if profile and profile.is_registered and profile.registered_device_id and profile.registered_device_id != device_id:
            return Response({"detail": "Korisnik nije registriran za ovaj uređaj."}, status=status.HTTP_403_FORBIDDEN)

        active_only = self._as_bool(request.GET.get("active_only"), default=True)
        qs = device.printers.all().order_by("-is_default", "name", "id")
        if active_only:
            qs = qs.filter(is_active=True)

        return Response(
            {
                "device_id": device.device_id,
                "receiver_url": device.print_receiver_url,
                "receipt_printer_id": device.receipt_printer_id,
                "bar_printer_id": device.bar_printer_id,
                "printers": PosPrinterInventorySerializer(qs, many=True).data,
            }
        )


class PosDevicePrinterSelectionView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, device_id: str):
        serializer = PosDevicePrinterSelectionRequestSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not data:
            return Response({"detail": "Nema podataka za ažuriranje."}, status=status.HTTP_400_BAD_REQUEST)

        device = (
            PosDevice.objects.select_related("pos")
            .filter(device_id=device_id, is_active=True, pos__is_active=True)
            .first()
        )
        if not device:
            return Response({"detail": "Uređaj nije pronađen ili nije aktivan."}, status=status.HTTP_404_NOT_FOUND)

        profile = getattr(request.user, "pos_profile", None)
        if profile and profile.is_registered and profile.registered_device_id and profile.registered_device_id != device_id:
            return Response({"detail": "Korisnik nije registriran za ovaj uređaj."}, status=status.HTTP_403_FORBIDDEN)

        update_fields = []
        if "receiver_url" in data:
            receiver_url = str(data.get("receiver_url", "") or "").strip()
            if device.print_receiver_url != receiver_url:
                device.print_receiver_url = receiver_url
                update_fields.append("print_receiver_url")

        for field_name in ("receipt_printer_id", "bar_printer_id"):
            if field_name not in data:
                continue
            value = data.get(field_name)
            target_field = "receipt_printer" if field_name == "receipt_printer_id" else "bar_printer"
            if value is None:
                setattr(device, target_field, None)
                update_fields.append(target_field)
                continue

            printer = PosPrinterInventory.objects.filter(
                id=value,
                device=device,
                is_active=True,
            ).first()
            if not printer:
                return Response(
                    {"detail": f"Printer {value} nije aktivan ili ne pripada uređaju {device_id}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            setattr(device, target_field, printer)
            update_fields.append(target_field)

        if update_fields:
            device.save(update_fields=sorted(set(update_fields)))

        return Response(
            {
                "device_id": device.device_id,
                "receiver_url_effective": device.print_receiver_url,
                "receipt_printer": (
                    PosPrinterInventorySerializer(device.receipt_printer).data if device.receipt_printer_id else None
                ),
                "bar_printer": (
                    PosPrinterInventorySerializer(device.bar_printer).data if device.bar_printer_id else None
                ),
            }
        )


class PosShiftTurnoverView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        issued_on_raw = request.GET.get("issued_on")
        warehouse_id = request.GET.get("warehouse_id")
        pos_id = request.GET.get("pos_id")
        issued_on = timezone.localdate() if not issued_on_raw else timezone.datetime.fromisoformat(issued_on_raw).date()

        turnover = ShiftTurnover.objects.filter(
            issued_on=issued_on,
            user=request.user,
            warehouse_id=warehouse_id or None,
            pos_id=pos_id or None,
        ).select_related("user", "warehouse", "pos").first()
        if not turnover:
            return Response({"detail": "Promet smjene ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        close = getattr(turnover, "close", None)
        expenses = []
        if close:
            expenses = [
                {"id": exp.id, "amount": str(exp.amount), "note": exp.note, "created_at": exp.created_at.isoformat()}
                for exp in close.expenses.all()
            ]

        return Response(
            {
                "id": turnover.id,
                "issued_on": turnover.issued_on.isoformat(),
                "user_id": turnover.user_id,
                "warehouse_id": turnover.warehouse_id,
                "pos_id": turnover.pos_id,
                "total_amount": str(turnover.total_amount),
                "invoice_count": turnover.invoice_count,
                "invoice_ids": turnover.invoice_ids,
                "close": {
                    "id": close.id,
                    "cash_counted": str(close.cash_counted),
                    "card_total": str(close.card_total),
                    "note": close.note,
                }
                if close
                else None,
                "expenses": expenses,
            }
        )


class PosShiftCloseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        verify_error = _require_recent_pin_verify(request)
        if verify_error:
            return verify_error

        issued_on_raw = request.data.get("issued_on")
        warehouse_id = request.data.get("warehouse_id")
        pos_id = request.data.get("pos_id")
        cash_counted = Decimal(str(request.data.get("cash_counted", 0)))
        card_total = Decimal(str(request.data.get("card_total", 0)))
        note = str(request.data.get("note", "") or "")
        run_import = bool(request.data.get("run_import", True))

        issued_on = timezone.localdate() if not issued_on_raw else timezone.datetime.fromisoformat(issued_on_raw).date()

        if run_import:
            defaults = load_import_defaults()
            import_sales_invoices(date_from=issued_on, date_to=issued_on, **defaults)

        for invoice in SalesInvoice.objects.filter(issued_on=issued_on, user__isnull=True):
            user = resolve_waiter_user(invoice.waiter_name)
            if user:
                invoice.user = user
                invoice.save(update_fields=["user"])

        qs = SalesInvoice.objects.filter(
            issued_on=issued_on,
            user=request.user,
        )
        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)
        if pos_id:
            qs = qs.filter(pos_id=pos_id)

        if not qs.exists():
            return Response({"detail": "Nema racuna za ovog konobara."}, status=status.HTTP_400_BAD_REQUEST)

        cash_qs = qs.filter(is_card=False)
        card_qs = qs.filter(is_card=True)

        turnover, created = ShiftTurnover.objects.get_or_create(
            issued_on=issued_on,
            user=request.user,
            warehouse_id=warehouse_id or None,
            pos_id=pos_id or None,
            defaults={
                "total_amount": cash_qs.aggregate(total=models.Sum("total_amount"))["total"] or Decimal("0.00"),
                "invoice_count": cash_qs.count(),
                "invoice_ids": list(cash_qs.values_list("id", flat=True)),
            },
        )
        if not created:
            total = cash_qs.aggregate(total=models.Sum("total_amount"))["total"] or Decimal("0.00")
            turnover.total_amount = total
            turnover.invoice_count = cash_qs.count()
            turnover.invoice_ids = list(cash_qs.values_list("id", flat=True))
            turnover.save(update_fields=["total_amount", "invoice_count", "invoice_ids"])

        close, _ = ShiftTurnoverClose.objects.update_or_create(
            turnover=turnover,
            defaults={
                "cash_counted": cash_counted,
                "card_total": card_qs.aggregate(total=models.Sum("total_amount"))["total"] or Decimal("0.00"),
                "note": note,
                "created_by": request.user,
            },
        )

        return Response(
            {
                "turnover_id": turnover.id,
                "issued_on": turnover.issued_on.isoformat(),
                "total_amount": str(turnover.total_amount),
                "invoice_count": turnover.invoice_count,
                "close_id": close.id,
            }
        )


class PosShiftExpenseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        issued_on_raw = request.data.get("issued_on")
        warehouse_id = request.data.get("warehouse_id")
        pos_id = request.data.get("pos_id")
        amount = Decimal(str(request.data.get("amount", 0)))
        note = str(request.data.get("note", "") or "")

        issued_on = timezone.localdate() if not issued_on_raw else timezone.datetime.fromisoformat(issued_on_raw).date()

        turnover = ShiftTurnover.objects.filter(
            issued_on=issued_on,
            user=request.user,
            warehouse_id=warehouse_id or None,
            pos_id=pos_id or None,
        ).first()
        if not turnover:
            return Response({"detail": "Promet smjene ne postoji."}, status=status.HTTP_404_NOT_FOUND)

        close, _ = ShiftTurnoverClose.objects.get_or_create(
            turnover=turnover,
            defaults={
                "cash_counted": Decimal("0.00"),
                "card_total": Decimal("0.00"),
                "note": "",
                "created_by": request.user,
            },
        )
        expense = ShiftTurnoverExpense.objects.create(
            close=close,
            amount=amount,
            note=note,
            created_by=request.user,
        )
        return Response(
            {
                "id": expense.id,
                "amount": str(expense.amount),
                "note": expense.note,
                "created_at": expense.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


class PosShiftCashExpectedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        issued_on_raw = request.GET.get("issued_on")
        warehouse_id = request.GET.get("warehouse_id")
        pos_id = request.GET.get("pos_id")

        issued_on = timezone.localdate() if not issued_on_raw else timezone.datetime.fromisoformat(issued_on_raw).date()

        turnover = ShiftTurnover.objects.filter(
            issued_on=issued_on,
            user=request.user,
            warehouse_id=warehouse_id or None,
            pos_id=pos_id or None,
        ).first()
        if not turnover:
            turnover = ShiftTurnover.objects.create(
                issued_on=issued_on,
                user=request.user,
                warehouse_id=warehouse_id or None,
                pos_id=pos_id or None,
                total_amount=Decimal("0.00"),
                invoice_count=0,
                invoice_ids=[],
            )

        opening = turnover.cash_handovers.filter(kind=ShiftCashHandover.Kind.OPENING).order_by("-created_at").first()
        if opening:
            opening_amount = opening.counted_amount
            opening_source = "opening"
        else:
            prev = (
                ShiftCashHandover.objects.filter(
                    kind=ShiftCashHandover.Kind.CLOSING,
                    turnover__warehouse_id=turnover.warehouse_id,
                    turnover__pos_id=turnover.pos_id,
                )
                .exclude(turnover_id=turnover.id)
                .order_by("-created_at")
                .first()
            )
            opening_amount = prev.counted_amount if prev else Decimal("0.00")
            opening_source = "previous_closing" if prev else "none"

        expenses_total = Decimal("0.00")
        if hasattr(turnover, "close") and turnover.close:
            expenses_total = (
                turnover.close.expenses.aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
            )

        expected = opening_amount + turnover.total_amount - expenses_total
        opening_required = opening is None
        closing_required = not turnover.cash_handovers.filter(kind=ShiftCashHandover.Kind.CLOSING).exists()

        return Response(
            {
                "turnover_id": turnover.id,
                "issued_on": turnover.issued_on.isoformat(),
                "opening_amount": str(opening_amount),
                "opening_source": opening_source,
                "cash_turnover": str(turnover.total_amount),
                "expenses_total": str(expenses_total),
                "expected_amount": str(expected),
                "opening_required": opening_required,
                "closing_required": closing_required,
            }
        )


class PosShiftCashHandoverView(APIView):
    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        issued_on = serializers.DateField(required=False)
        warehouse_id = serializers.IntegerField(required=False)
        pos_id = serializers.IntegerField(required=False)
        kind = serializers.ChoiceField(choices=[ShiftCashHandover.Kind.OPENING, ShiftCashHandover.Kind.CLOSING])
        counted_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
        note = serializers.CharField(required=False, allow_blank=True)

    def post(self, request):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issued_on = serializer.validated_data.get("issued_on") or timezone.localdate()
        warehouse_id = serializer.validated_data.get("warehouse_id")
        pos_id = serializer.validated_data.get("pos_id")
        kind = serializer.validated_data["kind"]
        counted_amount = serializer.validated_data["counted_amount"]
        note = (serializer.validated_data.get("note") or "").strip()

        turnover = ShiftTurnover.objects.filter(
            issued_on=issued_on,
            user=request.user,
            warehouse_id=warehouse_id or None,
            pos_id=pos_id or None,
        ).first()
        if not turnover:
            turnover = ShiftTurnover.objects.create(
                issued_on=issued_on,
                user=request.user,
                warehouse_id=warehouse_id or None,
                pos_id=pos_id or None,
                total_amount=Decimal("0.00"),
                invoice_count=0,
                invoice_ids=[],
            )

        opening = turnover.cash_handovers.filter(kind=ShiftCashHandover.Kind.OPENING).order_by("-created_at").first()
        if opening:
            opening_amount = opening.counted_amount
        else:
            prev = (
                ShiftCashHandover.objects.filter(
                    kind=ShiftCashHandover.Kind.CLOSING,
                    turnover__warehouse_id=turnover.warehouse_id,
                    turnover__pos_id=turnover.pos_id,
                )
                .exclude(turnover_id=turnover.id)
                .order_by("-created_at")
                .first()
            )
            opening_amount = prev.counted_amount if prev else Decimal("0.00")

        expenses_total = Decimal("0.00")
        if hasattr(turnover, "close") and turnover.close:
            expenses_total = (
                turnover.close.expenses.aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
            )

        if kind == ShiftCashHandover.Kind.OPENING:
            expected_amount = opening_amount
        else:
            expected_amount = opening_amount + turnover.total_amount - expenses_total

        difference = counted_amount - expected_amount
        if difference != Decimal("0.00") and not note:
            return Response({"note": "Napomena je obavezna kada postoji razlika."}, status=status.HTTP_400_BAD_REQUEST)

        journal_entry = None
        if kind == ShiftCashHandover.Kind.CLOSING and difference != Decimal("0.00"):
            ledger = get_single_ledger()
            cash_account = get_default_cash_account()
            if difference < Decimal("0.00"):
                diff_amount = abs(difference)
                diff_account = get_account_by_code(CASH_SHORTAGE_ACCOUNT_CODE, ledger=ledger)
                description = f"Manjak blagajne – smjena {issued_on} (user {request.user.username})"
                debit_account = diff_account
                credit_account = cash_account
            else:
                diff_amount = difference
                diff_account = get_account_by_code(CASH_SURPLUS_ACCOUNT_CODE, ledger=ledger)
                description = f"Visak blagajne – smjena {issued_on} (user {request.user.username})"
                debit_account = cash_account
                credit_account = diff_account

            next_number = (JournalEntry.objects.filter(ledger=ledger).aggregate(max_number=Max("number"))["max_number"] or 0) + 1
            entry = JournalEntry.objects.create(
                ledger=ledger,
                number=next_number,
                date=issued_on,
                description=description,
                status=JournalEntry.Status.DRAFT,
            )
            JournalItem.objects.create(
                entry=entry,
                account=debit_account,
                debit=diff_amount,
                credit=Decimal("0.00"),
            )
            JournalItem.objects.create(
                entry=entry,
                account=credit_account,
                debit=Decimal("0.00"),
                credit=diff_amount,
            )
            entry.post(user=request.user)
            journal_entry = entry

        handover, _ = ShiftCashHandover.objects.update_or_create(
            turnover=turnover,
            kind=kind,
            defaults={
                "expected_amount": expected_amount,
                "counted_amount": counted_amount,
                "difference_amount": difference,
                "note": note,
                "created_by": request.user,
                "journal_entry": journal_entry,
            },
        )

        return Response(
            {
                "id": handover.id,
                "kind": handover.kind,
                "expected_amount": str(handover.expected_amount),
                "counted_amount": str(handover.counted_amount),
                "difference_amount": str(handover.difference_amount),
                "note": handover.note,
                "journal_entry_id": journal_entry.id if journal_entry else None,
            }
        )


class PosInvoicePaymentFlagView(APIView):
    permission_classes = [IsAuthenticated]

    class QuerySerializer(serializers.Serializer):
        issued_on = serializers.DateField(required=False)
        warehouse_id = serializers.IntegerField(required=False)
        pos_id = serializers.IntegerField(required=False)
        user_id = serializers.IntegerField(required=False)

    class PatchSerializer(serializers.Serializer):
        issued_on = serializers.DateField(required=False)
        warehouse_id = serializers.IntegerField(required=False)
        pos_id = serializers.IntegerField(required=False)
        user_id = serializers.IntegerField(required=False)
        invoice_id = serializers.IntegerField(required=False)
        invoice_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
        is_card = serializers.BooleanField()

    def _filtered_queryset(self, request):
        issued_on_raw = request.GET.get("issued_on") or request.data.get("issued_on")
        warehouse_id = request.GET.get("warehouse_id") or request.data.get("warehouse_id")
        pos_id = request.GET.get("pos_id") or request.data.get("pos_id")
        user_id = request.GET.get("user_id") or request.data.get("user_id") or request.user.id

        issued_on = None
        if issued_on_raw:
            issued_on = timezone.datetime.fromisoformat(issued_on_raw).date()

        qs = SalesInvoice.objects.all()
        if issued_on:
            qs = qs.filter(issued_on=issued_on)
        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)
        if pos_id:
            qs = qs.filter(pos_id=pos_id)
        if user_id:
            qs = qs.filter(user_id=user_id)
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter("issued_on", type=str, required=False),
            OpenApiParameter("warehouse_id", type=int, required=False),
            OpenApiParameter("pos_id", type=int, required=False),
            OpenApiParameter("user_id", type=int, required=False),
        ],
        responses={200: serializers.Serializer},
    )
    def get(self, request):
        qs = self._filtered_queryset(request).select_related("user", "pos")
        data = [
            {
                "id": inv.id,
                "rm_number": inv.rm_number,
                "issued_on": inv.issued_on.isoformat(),
                "issued_at": inv.issued_at.isoformat() if inv.issued_at else None,
                "user_id": inv.user_id,
                "user": inv.user.get_full_name() if inv.user_id else None,
                "pos_id": inv.pos_id,
                "pos": inv.pos.name if inv.pos_id else None,
                "total_amount": str(inv.total_amount),
                "is_card": bool(inv.is_card),
            }
            for inv in qs.order_by("issued_at", "id")
        ]
        return Response({"results": data})

    @extend_schema(request=PatchSerializer, responses={200: serializers.Serializer})
    def patch(self, request):
        invoice_ids = request.data.get("invoice_ids") or []
        invoice_id = request.data.get("invoice_id")
        is_card = request.data.get("is_card", None)

        if is_card is None:
            return Response({"detail": "Nedostaje is_card."}, status=status.HTTP_400_BAD_REQUEST)

        if invoice_id:
            invoice_ids = [invoice_id]

        if not invoice_ids:
            return Response({"detail": "Nedostaju invoice_ids."}, status=status.HTTP_400_BAD_REQUEST)

        qs = self._filtered_queryset(request).filter(id__in=invoice_ids)
        if not qs.exists():
            return Response({"detail": "Nema racuna za azuriranje."}, status=status.HTTP_404_NOT_FOUND)

        updated = 0
        errors = []
        for inv in qs:
            try:
                inv.is_card = bool(is_card)
                inv.save(update_fields=["is_card"])
                updated += 1
            except ValidationError as exc:
                errors.append({"id": inv.id, "error": str(exc)})

        return Response({"updated": updated, "errors": errors})
