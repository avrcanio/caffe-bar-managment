from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from configuration.models import CompanyProfile
from sales.models import FiscalReceipt, SalesInvoice


@dataclass
class FiscalConfig:
    oib: str
    office_code: str
    device_code: str
    cert_path: str
    cert_p12_data: bytes | None
    cert_pass: str
    environment: str = "EDUC"


def get_fiscal_config() -> FiscalConfig:
    company = CompanyProfile.objects.first()
    oib = (company.oib if company else "") or os.getenv("FISCAL_OIB", "")
    office_code = os.getenv("FISCAL_OFFICE_CODE", "POS1")
    device_code = os.getenv("FISCAL_DEVICE_CODE", "1")
    cert_path = os.getenv("FISCAL_CERT_PATH", "")
    cert_p12_data = None
    cert_pass = os.getenv("FISCAL_CERT_PASS", "")
    if company and getattr(company, "fiscal_cert_p12", None):
        # Prefer DB-stored certificate to avoid filesystem/public media exposure.
        cert_p12_data = bytes(company.fiscal_cert_p12)
        cert_pass = (company.fiscal_cert_pass or "").strip() or cert_pass
    environment = os.getenv("FISCAL_ENV", "EDUC")
    return FiscalConfig(
        oib=oib,
        office_code=office_code,
        device_code=device_code,
        cert_path=cert_path,
        cert_p12_data=cert_p12_data,
        cert_pass=cert_pass,
        environment=environment,
    )


def _load_private_key(config: FiscalConfig):
    from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

    if not config.cert_pass:
        raise ValueError("FISCAL_CERT_PASS nije postavljen.")
    if config.cert_p12_data:
        p12_data = config.cert_p12_data
    else:
        if not config.cert_path:
            raise ValueError("FISCAL_CERT_PATH nije postavljen (nema certifikata u bazi).")
        with open(config.cert_path, "rb") as fh:
            p12_data = fh.read()
    key, _cert, _additional = load_key_and_certificates(
        p12_data, config.cert_pass.encode("utf-8")
    )
    if not key:
        raise ValueError("Ne mogu učitati privatni ključ iz certifikata.")
    return key


def _format_amount(value: Decimal) -> str:
    return f"{value:.2f}"


def _is_mock_enabled() -> bool:
    return os.getenv("FISCAL_MOCK", "false").lower() in ("1", "true", "yes", "on")


def build_zki_input(invoice: SalesInvoice, config: FiscalConfig) -> str:
    issued_at = timezone.localtime(invoice.issued_at)
    issued_at_str = issued_at.strftime("%d.%m.%Y %H:%M:%S")
    return (
        f"{config.oib}{issued_at_str}{invoice.rm_number}"
        f"{config.office_code}{config.device_code}{_format_amount(invoice.total_amount)}"
    )


def generate_zki(invoice: SalesInvoice, config: FiscalConfig) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    if _is_mock_enabled():
        payload = (build_zki_input(invoice, config) + "|MOCK").encode("utf-8")
        return hashlib.md5(payload).hexdigest()
    key = _load_private_key(config)
    payload = build_zki_input(invoice, config).encode("utf-8")
    signature = key.sign(payload, padding.PKCS1v15(), hashes.SHA1())
    return hashlib.md5(signature).hexdigest()


def build_qr_payload(invoice: SalesInvoice, config: FiscalConfig, zki: str) -> str:
    issued_at = timezone.localtime(invoice.issued_at)
    issued_at_str = issued_at.strftime("%d.%m.%Y %H:%M:%S")
    return "|".join(
        [
            config.oib,
            issued_at_str,
            str(invoice.rm_number),
            config.office_code,
            config.device_code,
            _format_amount(invoice.total_amount),
            zki,
        ]
    )


def fiscalize_sales_invoice(invoice: SalesInvoice, *, user=None) -> FiscalReceipt:
    config = get_fiscal_config()
    if not config.oib:
        raise ValueError("OIB nije postavljen (CompanyProfile.oib ili FISCAL_OIB).")
    receipt, _ = FiscalReceipt.objects.get_or_create(invoice=invoice)
    if receipt.status == FiscalReceipt.Status.SUCCESS and receipt.jir:
        return receipt
    try:
        zki = generate_zki(invoice, config)
        receipt.zki = zki
        receipt.qr_payload = build_qr_payload(invoice, config, zki)
        if _is_mock_enabled():
            receipt.status = FiscalReceipt.Status.SUCCESS
            receipt.error_message = "MOCK fiskalizacija (bez certifikata)."
            receipt.save(update_fields=["zki", "qr_payload", "status", "error_message", "updated_at"])
            return receipt

        receipt.status = FiscalReceipt.Status.PENDING
        receipt.error_message = ""
        receipt.save(update_fields=["zki", "qr_payload", "status", "error_message", "updated_at"])

        from sales.fiscal_send import is_send_enabled, send_sales_invoice

        if is_send_enabled():
            result = send_sales_invoice(invoice, config)
            receipt.jir = result.jir
            receipt.xml_request = result.xml_request
            receipt.xml_response = result.xml_response
            receipt.sent_at = timezone.now()
            receipt.status = FiscalReceipt.Status.SUCCESS
            receipt.save(
                update_fields=[
                    "jir",
                    "xml_request",
                    "xml_response",
                    "sent_at",
                    "status",
                    "updated_at",
                ]
            )
    except Exception as exc:
        receipt.status = FiscalReceipt.Status.ERROR
        receipt.error_message = str(exc)
        receipt.save(update_fields=["status", "error_message", "updated_at"])
        raise
    return receipt
