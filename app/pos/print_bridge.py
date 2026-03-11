import base64
import json
import logging
import os
from io import BytesIO
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


logger = logging.getLogger(__name__)
_BAR_FONT_REGISTERED = False


def _register_bar_pdf_font() -> tuple[str, str]:
    global _BAR_FONT_REGISTERED
    if not _BAR_FONT_REGISTERED:
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        bold_font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        try:
            if os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont("BarTicketSans", font_path))
                if os.path.exists(bold_font_path):
                    pdfmetrics.registerFont(TTFont("BarTicketSansBold", bold_font_path))
                _BAR_FONT_REGISTERED = True
        except Exception:
            _BAR_FONT_REGISTERED = False
    if _BAR_FONT_REGISTERED:
        return "BarTicketSans", "BarTicketSansBold"
    return "Helvetica", "Helvetica-Bold"


def _is_true(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _bridge_url() -> str:
    return str(os.getenv("PRINT_BRIDGE_URL", "http://print_bridge:8090")).rstrip("/")


def _bridge_token() -> str:
    return str(os.getenv("PRINT_BRIDGE_API_TOKEN", "")).strip()


def _resolve_receiver_token(*, device) -> str:
    return str(getattr(device, "print_receiver_token", "") or "").strip() if device else ""


def _get_device_model():
    from pos.models import PosDevice

    return PosDevice


def _get_device_for_receipt(receipt):
    PosDevice = _get_device_model()
    operator = getattr(receipt, "operator", None)
    profile = getattr(operator, "pos_profile", None) if operator else None
    registered_device_id = str(getattr(profile, "registered_device_id", "") or "").strip()

    if registered_device_id:
        device = (
            PosDevice.objects.select_related("receipt_printer", "bar_printer")
            .filter(device_id=registered_device_id, is_active=True)
            .first()
        )
        if device:
            return device

    def _fallback_single_active_device():
        active_devices = list(
            PosDevice.objects.select_related("receipt_printer", "bar_printer")
            .filter(is_active=True)
            .order_by("id")[:2]
        )
        if len(active_devices) == 1:
            logger.warning("Receipt missing pos/device binding; falling back to the only active POS device.")
            return active_devices[0]
        return None

    pos_id = getattr(receipt, "pos_id", None)
    if not pos_id:
        return _fallback_single_active_device()

    devices = list(
        PosDevice.objects.select_related("receipt_printer", "bar_printer")
        .filter(pos_id=pos_id, is_active=True)
        .order_by("id")
    )
    if len(devices) == 1:
        return devices[0]
    if not devices:
        return _fallback_single_active_device()
    return None


def _get_device_for_bar_ticket(ticket: dict[str, Any]):
    device_id = str(ticket.get("device_id", "") or "").strip()
    PosDevice = _get_device_model()
    if device_id:
        return (
            PosDevice.objects.select_related("receipt_printer", "bar_printer")
            .filter(device_id=device_id, is_active=True)
            .first()
        )

    # Fallback for legacy/partially configured clients that do not send device_id:
    # if there is exactly one active POS device, use it for bar printing.
    active_devices = list(
        PosDevice.objects.select_related("receipt_printer", "bar_printer")
        .filter(is_active=True)
        .order_by("id")[:2]
    )
    if len(active_devices) == 1:
        logger.warning("Bar ticket missing device_id; falling back to the only active POS device.")
        return active_devices[0]
    return None


def _post_job(payload: dict[str, Any]) -> dict[str, Any]:
    timeout = float(os.getenv("PRINT_BRIDGE_TIMEOUT", "5"))
    headers = {"Content-Type": "application/json"}
    token = _bridge_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{_bridge_url()}/v1/jobs"
    # Ensure non-JSON-native values (e.g. Decimal) are serialized safely.
    body = json.dumps(payload, default=str)
    response = requests.post(url, data=body, headers=headers, timeout=timeout)
    if 200 <= response.status_code < 300:
        try:
            return response.json()
        except Exception:
            return {"ok": True}

    detail = response.text[:500]
    raise RuntimeError(f"print bridge error status={response.status_code} detail={detail}")


def _to_print_qty(value: Any) -> Any:
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


def _build_bar_ticket_pdf(*, ticket: dict[str, Any], items: list[dict[str, Any]]) -> bytes:
    font_regular, font_bold = _register_bar_pdf_font()
    page_width = 80 * mm
    left = 6 * mm
    right = 6 * mm
    content_width = page_width - left - right
    line_h = 4.2 * mm

    lines: list[tuple[str, str, int]] = []
    lines.append(("center", "BAR TICKET", 12))
    lines.append(("left", f"Table: {ticket.get('table') or ticket.get('table_label') or 'N/A'}", 9))
    lines.append(("left", f"Waiter: {ticket.get('waiter') or 'N/A'}", 9))
    lines.append(("left", f"Round: {ticket.get('round_number') or '-'}", 9))
    lines.append(("left", "-" * 42, 8))

    for idx, item in enumerate(items, start=1):
        qty = item.get("qty")
        name = str(item.get("name") or item.get("artikl_name") or "").strip() or "Item"
        title = f"{idx}. {qty} x {name}"
        for split in simpleSplit(title, font_bold, 9, content_width):
            lines.append(("left_bold", split, 9))

        modifier_lines = item.get("modifier_lines")
        if isinstance(modifier_lines, list):
            for mod_line in modifier_lines:
                mod_txt = str(mod_line or "").strip()
                if not mod_txt:
                    continue
                for split in simpleSplit(f"   + {mod_txt}", font_regular, 8, content_width):
                    lines.append(("left", split, 8))

        note = str(item.get("note") or "").strip()
        if note:
            for split in simpleSplit(f"   note: {note}", font_regular, 8, content_width):
                lines.append(("left", split, 8))

    lines.append(("left", "-" * 42, 8))
    sent_at = str(ticket.get("sent_at") or "").strip()
    if sent_at:
        lines.append(("left", sent_at, 8))

    page_height = max(80 * mm, (len(lines) + 3) * line_h + 10 * mm)
    buff = BytesIO()
    c = canvas.Canvas(buff, pagesize=(page_width, page_height))
    y = page_height - 8 * mm

    for align, txt, size in lines:
        if align == "left_bold":
            c.setFont(font_bold, size)
            c.drawString(left, y, txt)
        elif align == "center":
            c.setFont(font_bold, size)
            c.drawCentredString(page_width / 2, y, txt)
        else:
            c.setFont(font_regular, size)
            c.drawString(left, y, txt)
        y -= line_h

    c.showPage()
    c.save()
    return buff.getvalue()


def send_bar_ticket_to_print_bridge(ticket: dict[str, Any]) -> None:
    if not _is_true(os.getenv("BARION_BAR_PRINTER_ENABLED", "true")):
        raise RuntimeError("Bar printer nije konfiguriran.")

    receiver_url = ""
    printer_name = ""
    device = _get_device_for_bar_ticket(ticket)
    if device:
        receiver_url = str(device.print_receiver_url or "").strip()
        if device.bar_printer_id and device.bar_printer and device.bar_printer.is_active:
            printer_name = str(device.bar_printer.name or "").strip()

    if not receiver_url:
        receiver_url = str(os.getenv("BARION_BAR_RECEIVER_URL", "")).strip()
    if not printer_name:
        printer_name = str(os.getenv("BARION_BAR_PRINTER_NAME", "")).strip()
    receiver_token = _resolve_receiver_token(device=device)
    if not receiver_url or not printer_name or not receiver_token:
        raise RuntimeError("Bar printer nije konfiguriran.")

    normalized_items = []
    for raw_item in ticket.get("items") or []:
        if not isinstance(raw_item, dict):
            continue
        qty_raw = raw_item.get("quantity") if raw_item.get("quantity") is not None else raw_item.get("qty")
        qty = _to_print_qty(qty_raw)
        normalized_items.append(
            {
                "id": raw_item.get("id"),
                "artikl_id": raw_item.get("artikl_id"),
                "artikl_name": raw_item.get("artikl_name") or raw_item.get("name") or "",
                "name": raw_item.get("name") or raw_item.get("artikl_name") or "",
                "quantity": qty,
                "qty": qty,
                "note": raw_item.get("note") or "",
            }
        )

    normalized_ticket = {
        "check_id": ticket.get("check_id"),
        "table": ticket.get("table") or ticket.get("table_label"),
        "table_label": ticket.get("table_label") or ticket.get("table"),
        "waiter": ticket.get("waiter"),
        "round_number": ticket.get("round_number"),
        "items": normalized_items,
    }

    payload = {
        "kind": "receipt_pdf",
        "target": {
            "receiver_url": receiver_url,
            "printer_name": printer_name,
            "receiver_token": receiver_token,
        },
        "payload": {
            "filename": (
                f"bar-ticket-{normalized_ticket.get('check_id') or 'na'}-"
                f"r{normalized_ticket.get('round_number') or '0'}.pdf"
            ),
            "pdf_base64": base64.b64encode(
                _build_bar_ticket_pdf(ticket=normalized_ticket, items=normalized_items)
            ).decode("ascii"),
        },
        "meta": {
            "source": "mozzart",
            "original_kind": "bar_ticket",
            "check_id": ticket.get("check_id"),
            "round_number": ticket.get("round_number"),
        },
    }

    try:
        _post_job(payload)
    except Exception as exc:
        logger.exception("Failed to dispatch bar ticket to print bridge")
        raise RuntimeError("Greška pri slanju na bar printer.") from exc


def send_receipt_pdf_to_print_bridge(*, receipt, pdf_bytes: bytes) -> None:
    if not _is_true(os.getenv("PRINT_RECEIPT_ENABLED", "true")):
        return
    if str(getattr(receipt, "status", "")).strip().lower() != "fiscalized":
        logger.info("Skipping receipt print bridge dispatch: receipt is not fiscalized yet.")
        return

    receiver_url = ""
    printer_name = ""
    pos = getattr(receipt, "pos", None)
    device = _get_device_for_receipt(receipt)
    if device:
        receiver_url = str(device.print_receiver_url or "").strip()
        if device.receipt_printer_id and device.receipt_printer and device.receipt_printer.is_active:
            printer_name = str(device.receipt_printer.name or "").strip()

    pos_config = getattr(pos, "config", {}) if pos else {}
    if isinstance(pos_config, dict):
        if not receiver_url:
            receiver_url = str(pos_config.get("receipt_receiver_url", "")).strip()
        if not printer_name:
            printer_name = str(pos_config.get("receipt_printer_name", "")).strip()

    if not receiver_url:
        receiver_url = str(os.getenv("POS_RECEIPT_RECEIVER_URL", "")).strip()
    if not printer_name:
        printer_name = str(os.getenv("POS_RECEIPT_PRINTER_NAME", "")).strip()
    receiver_token = _resolve_receiver_token(device=device)

    if not receiver_url or not printer_name or not receiver_token:
        logger.info("Skipping receipt print bridge dispatch: missing receiver/printer/token config.")
        return

    payload = {
        "kind": "receipt_pdf",
        "target": {
            "receiver_url": receiver_url,
            "printer_name": printer_name,
            "receiver_token": receiver_token,
        },
        "payload": {
            "filename": f"pos-receipt-{receipt.id}.pdf",
            "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        },
        "meta": {
            "source": "mozzart",
            "receipt_id": receipt.id,
            "receipt_number": receipt.receipt_number,
            "office_code": receipt.office_code,
            "device_code": receipt.device_code,
        },
    }

    try:
        _post_job(payload)
    except Exception:
        logger.exception("Failed to dispatch receipt PDF to print bridge")
