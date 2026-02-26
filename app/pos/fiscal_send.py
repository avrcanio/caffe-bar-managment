from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.utils import timezone

from sales.fiscal import FiscalConfig, _format_amount
from pos.models import PosReceipt


FISCAL_TYPES_NS = "http://www.apis-it.hr/fin/2012/types/f73"
SOAPENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"


@dataclass(frozen=True)
class SendResult:
    jir: str


def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def is_send_enabled() -> bool:
    return _bool_env("FISCAL_SEND_ENABLED", False)


def _get_service_url(config: FiscalConfig) -> str:
    env = (config.environment or "").strip().lower()
    if env in ("prod", "production", "live"):
        return "https://cis.porezna-uprava.hr:8449/FiskalizacijaService"
    return "https://cistest.apis-it.hr:8449/FiskalizacijaServiceTest"


def _format_dt_xml(dt) -> str:
    from zoneinfo import ZoneInfo
    from django.utils import timezone as dj_tz

    tz = ZoneInfo(os.getenv("FISCAL_TIMEZONE", "Europe/Zagreb"))
    if dj_tz.is_naive(dt):
        dt = dj_tz.make_aware(dt, tz)
    dt_local = dt.astimezone(tz)
    return dt_local.strftime("%d.%m.%YT%H:%M:%S")


def _load_key_and_cert(config: FiscalConfig):
    from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

    if not config.cert_pass:
        raise ValueError("FISCAL_CERT_PASS nije postavljen.")
    if getattr(config, "cert_p12_data", None):
        p12_data = config.cert_p12_data
    else:
        if not config.cert_path:
            raise ValueError("FISCAL_CERT_PATH nije postavljen (nema certifikata u bazi).")
        with open(config.cert_path, "rb") as fh:
            p12_data = fh.read()
    key, cert, _additional = load_key_and_certificates(
        p12_data, config.cert_pass.encode("utf-8")
    )
    if not key:
        raise ValueError("Ne mogu učitati privatni ključ iz certifikata.")
    if not cert:
        raise ValueError("Ne mogu učitati certifikat (X.509) iz .p12 datoteke.")
    return key, cert


def _operator_oib(config: FiscalConfig) -> str:
    return os.getenv("FISCAL_OPERATOR_OIB", "") or config.oib


def _ozn_slijed() -> str:
    return os.getenv("FISCAL_OZNSLIJED", "P")


def _usustpdv() -> str:
    return "true" if _bool_env("FISCAL_USUSTPDV", True) else "false"


def _nacin_placanja(receipt: PosReceipt) -> str:
    return "K" if receipt.payment_type == "card" else "G"


def _round_2(value: Decimal) -> Decimal:
    return (value or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _build_pdv_elements(receipt: PosReceipt, root):
    from lxml import etree

    items = receipt.items.all()
    buckets: dict[Decimal, dict[str, Decimal]] = {}
    for it in items:
        gross = it.total_amount or Decimal("0.00")
        rate = it.vat_rate or Decimal("0.0000")
        if rate <= 0:
            continue
        percent = (rate * Decimal("100.0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        base = gross / (Decimal("1.0") + rate)
        osnovica = _round_2(base)
        iznos = _round_2(gross - osnovica)
        b = buckets.setdefault(percent, {"osnovica": Decimal("0.00"), "iznos": Decimal("0.00")})
        b["osnovica"] += osnovica
        b["iznos"] += iznos

    if not buckets:
        return

    pdv_el = etree.SubElement(root, etree.QName(FISCAL_TYPES_NS, "Pdv"))
    for percent in sorted(buckets.keys()):
        porez_el = etree.SubElement(pdv_el, etree.QName(FISCAL_TYPES_NS, "Porez"))
        etree.SubElement(porez_el, etree.QName(FISCAL_TYPES_NS, "Stopa")).text = f"{percent:.2f}"
        etree.SubElement(porez_el, etree.QName(FISCAL_TYPES_NS, "Osnovica")).text = _format_amount(
            _round_2(buckets[percent]["osnovica"])
        )
        etree.SubElement(porez_el, etree.QName(FISCAL_TYPES_NS, "Iznos")).text = _format_amount(
            _round_2(buckets[percent]["iznos"])
        )


def build_racun_zahtjev(receipt: PosReceipt, config: FiscalConfig, *, id_poruke: str | None = None):
    from lxml import etree

    if not config.oib:
        raise ValueError("OIB nije postavljen (CompanyProfile.oib ili FISCAL_OIB).")

    op_oib = _operator_oib(config)
    if not op_oib:
        raise ValueError("FISCAL_OPERATOR_OIB nije postavljen (OIB operatera).")

    id_poruke = id_poruke or str(uuid.uuid4())
    root = etree.Element(etree.QName(FISCAL_TYPES_NS, "RacunZahtjev"), nsmap={"tns": FISCAL_TYPES_NS})
    root.set("Id", id_poruke)

    zaglavlje = etree.SubElement(root, etree.QName(FISCAL_TYPES_NS, "Zaglavlje"))
    etree.SubElement(zaglavlje, etree.QName(FISCAL_TYPES_NS, "IdPoruke")).text = id_poruke
    etree.SubElement(zaglavlje, etree.QName(FISCAL_TYPES_NS, "DatumVrijeme")).text = _format_dt_xml(timezone.now())

    racun = etree.SubElement(root, etree.QName(FISCAL_TYPES_NS, "Racun"))
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "Oib")).text = config.oib
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "USustPdv")).text = _usustpdv()
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "DatVrijeme")).text = _format_dt_xml(receipt.issued_at)
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "OznSlijed")).text = _ozn_slijed()

    br_rac = etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "BrRac"))
    etree.SubElement(br_rac, etree.QName(FISCAL_TYPES_NS, "BrOznRac")).text = str(receipt.receipt_number)
    etree.SubElement(br_rac, etree.QName(FISCAL_TYPES_NS, "OznPosPr")).text = receipt.office_code
    etree.SubElement(br_rac, etree.QName(FISCAL_TYPES_NS, "OznNapUr")).text = receipt.device_code

    _build_pdv_elements(receipt, racun)

    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "IznosUkupno")).text = _format_amount(_round_2(receipt.total_amount))
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "NacinPlac")).text = _nacin_placanja(receipt)
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "OibOper")).text = op_oib
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "ZastKod")).text = receipt.zki
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "NakDost")).text = "false"
    return root


def _sign_racun_zahtjev(racun_zahtjev_el, *, key, cert, reference_uri: str):
    from cryptography.hazmat.primitives import serialization
    from signxml import XMLSigner, methods
    import signxml.signer

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    orig_check = signxml.signer.XMLSigner.check_deprecated_methods
    signxml.signer.XMLSigner.check_deprecated_methods = lambda self: None  # type: ignore[assignment]
    try:
        signer = XMLSigner(
            method=methods.enveloped,
            signature_algorithm="rsa-sha1",
            digest_algorithm="sha1",
            c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#",
        )
    finally:
        signxml.signer.XMLSigner.check_deprecated_methods = orig_check  # type: ignore[assignment]

    return signer.sign(
        racun_zahtjev_el,
        key=key,
        cert=cert_pem,
        reference_uri=reference_uri,
        id_attribute="Id",
    )


def _wrap_soap(body_el) -> bytes:
    from lxml import etree

    env = etree.Element(etree.QName(SOAPENV_NS, "Envelope"), nsmap={"soapenv": SOAPENV_NS})
    body = etree.SubElement(env, etree.QName(SOAPENV_NS, "Body"))
    body.append(body_el)
    return etree.tostring(env, xml_declaration=True, encoding="UTF-8")


def _parse_racun_odgovor(xml_bytes: bytes) -> tuple[str, str | None]:
    from lxml import etree

    doc = etree.fromstring(xml_bytes)
    ns = {"tns": FISCAL_TYPES_NS, "soapenv": SOAPENV_NS}
    jir = doc.xpath("string(.//tns:Jir)", namespaces=ns).strip()
    if jir:
        return jir, None
    code = doc.xpath("string(.//tns:Greska/tns:SifraGreske)", namespaces=ns).strip()
    msg = doc.xpath("string(.//tns:Greska/tns:PorukaGreske)", namespaces=ns).strip()
    if code or msg:
        return "", f"{code}: {msg}".strip(": ").strip()
    fault = doc.xpath("string(.//soapenv:Fault/faultstring)", namespaces=ns).strip()
    if fault:
        return "", fault
    return "", "Nepoznat odgovor (nema JIR ni greske)."


def send_pos_receipt(receipt: PosReceipt, config: FiscalConfig) -> SendResult:
    if not is_send_enabled():
        raise RuntimeError("Slanje nije omoguceno (FISCAL_SEND_ENABLED=false).")

    racun_zahtjev = build_racun_zahtjev(receipt, config)
    req_id = racun_zahtjev.get("Id")
    key, cert = _load_key_and_cert(config)
    signed = _sign_racun_zahtjev(racun_zahtjev, key=key, cert=cert, reference_uri=f"#{req_id}")
    soap_bytes = _wrap_soap(signed)

    ca_path = os.getenv("FISCAL_TLS_CA_PATH", "").strip()
    verify = ca_path if ca_path else True
    timeout = float(os.getenv("FISCAL_HTTP_TIMEOUT", "15"))
    url = _get_service_url(config)

    resp = requests.post(
        url,
        data=soap_bytes,
        headers={"Content-Type": "text/xml; charset=utf-8"},
        timeout=timeout,
        verify=verify,
    )
    resp_xml = resp.content or b""
    jir, err = _parse_racun_odgovor(resp_xml)
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {err or resp.text[:200]}")
    if err:
        raise RuntimeError(err)
    if not jir:
        raise RuntimeError("Nema JIR u odgovoru.")
    return SendResult(jir=jir)
