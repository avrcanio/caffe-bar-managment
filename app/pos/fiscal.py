import os
import hashlib
from decimal import Decimal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from django.utils import timezone

from configuration.models import CompanyProfile
from pos.models import PosReceipt
from sales.fiscal import get_fiscal_config


def _format_amount(value: Decimal) -> str:
    return f"{value:.2f}"


def _format_qr_amount(value: Decimal) -> str:
    # PU QR expects amount as 10 chars without decimal separator (2 decimal places implied).
    cents = int((Decimal(str(value)).quantize(Decimal("0.01")) * 100))
    return str(cents).zfill(10)


def _is_mock_enabled() -> bool:
    return os.getenv("FISCAL_MOCK", "false").lower() in ("1", "true", "yes", "on")


def _load_private_key():
    company = CompanyProfile.objects.first()
    cert_pass = (getattr(company, "fiscal_cert_pass", "") or "").strip() or os.getenv("FISCAL_CERT_PASS", "")
    if not cert_pass:
        raise ValueError("FISCAL_CERT_PASS nije postavljen.")
    p12_data = None
    if company and getattr(company, "fiscal_cert_p12", None):
        p12_data = bytes(company.fiscal_cert_p12)
    else:
        cert_path = os.getenv("FISCAL_CERT_PATH", "")
        if not cert_path:
            raise ValueError("FISCAL_CERT_PATH nije postavljen (nema certifikata u bazi).")
        with open(cert_path, "rb") as fh:
            p12_data = fh.read()
    key, _cert, _additional = load_key_and_certificates(
        p12_data, cert_pass.encode("utf-8")
    )
    if not key:
        raise ValueError("Ne mogu učitati privatni ključ iz certifikata.")
    return key


def _get_oib() -> str:
    company = CompanyProfile.objects.first()
    return (company.oib if company else "") or os.getenv("FISCAL_OIB", "")


def build_zki_input(receipt: PosReceipt) -> str:
    oib = _get_oib()
    issued_at = timezone.localtime(receipt.issued_at)
    issued_at_str = issued_at.strftime("%d.%m.%Y %H:%M:%S")
    return (
        f"{oib}{issued_at_str}{receipt.receipt_number}"
        f"{receipt.office_code}{receipt.device_code}{_format_amount(receipt.total_amount)}"
    )


def generate_zki(receipt: PosReceipt) -> str:
    if _is_mock_enabled():
        payload = (build_zki_input(receipt) + "|MOCK").encode("utf-8")
        return hashlib.md5(payload).hexdigest()
    key = _load_private_key()
    payload = build_zki_input(receipt).encode("utf-8")
    signature = key.sign(payload, padding.PKCS1v15(), hashes.SHA1())
    return hashlib.md5(signature).hexdigest()


def build_qr_payload(receipt: PosReceipt, zki: str, jir: str = "") -> str:
    issued_at = timezone.localtime(receipt.issued_at)
    datv = issued_at.strftime("%Y%m%d_%H%M")
    izn = _format_qr_amount(receipt.total_amount)
    key = "jir" if jir else "zki"
    code = jir or zki
    return f"https://porezna.gov.hr/rn?{key}={code}&datv={datv}&izn={izn}"


def fiscalize_pos_receipt(receipt: PosReceipt) -> PosReceipt:
    oib = _get_oib()
    if not oib:
        raise ValueError("OIB nije postavljen (CompanyProfile.oib ili FISCAL_OIB).")
    try:
        zki = generate_zki(receipt)
        receipt.zki = zki
        receipt.qr_payload = build_qr_payload(receipt, zki)
        receipt.status = PosReceipt.Status.FISCALIZED
        receipt.error_message = "MOCK fiskalizacija (bez certifikata)." if _is_mock_enabled() else ""
        receipt.save(update_fields=["zki", "qr_payload", "status", "error_message", "updated_at"])

        if os.getenv("FISCAL_SEND_ENABLED", "false").lower() == "true":
            from pos.fiscal_send import send_pos_receipt

            result = send_pos_receipt(receipt, get_fiscal_config())
            receipt.jir = result.jir
            receipt.qr_payload = build_qr_payload(receipt, zki, result.jir)
            receipt.error_message = ""
            receipt.save(update_fields=["jir", "qr_payload", "error_message", "updated_at"])
        return receipt
    except Exception as exc:
        receipt.status = PosReceipt.Status.ERROR
        receipt.error_message = str(exc)
        receipt.save(update_fields=["status", "error_message", "updated_at"])
        raise
