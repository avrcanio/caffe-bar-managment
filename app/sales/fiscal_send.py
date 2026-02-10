from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.utils import timezone

from sales.fiscal import FiscalConfig, _format_amount, generate_zki
from sales.models import SalesInvoice


FISCAL_TYPES_NS = "http://www.apis-it.hr/fin/2012/types/f73"
SOAPENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"


@dataclass(frozen=True)
class SendResult:
    jir: str
    xml_request: str
    xml_response: str


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
    # Default to test/EDUC.
    return "https://cistest.apis-it.hr:8449/FiskalizacijaServiceTest"


def _format_dt_xml(dt) -> str:
    # Fiskalizacija schema uses a custom datetime string format: dd.MM.yyyyTHH:mm:ss
    # (note: not ISO 8601 with dashes).
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
    # In production this should be the operator's OIB.
    # For EDU/testing, some setups reuse the company's OIB.
    return os.getenv("FISCAL_OPERATOR_OIB", "") or config.oib


def _ozn_slijed() -> str:
    return os.getenv("FISCAL_OZNSLIJED", "P")


def _usustpdv() -> str:
    # XML expects "true"/"false" (xsd:boolean).
    return "true" if _bool_env("FISCAL_USUSTPDV", True) else "false"


def _nacin_placanja(invoice: SalesInvoice) -> str:
    # Codes per Fiskalizacija: G=gotovina, K=kartice, T=transakcijski racun, C=cek, O=ostalo.
    if getattr(invoice, "is_card", False):
        return "K"
    return "G"


def _round_2(value: Decimal) -> Decimal:
    return (value or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _build_pdv_elements(invoice: SalesInvoice, root, nsmap):
    """
    Build a PDV breakdown from invoice items tax_group.rate.
    If items don't have rates, we skip PDV entirely (service may still accept if USustPdv=false).
    """
    from lxml import etree

    items = (
        invoice.items.select_related("artikl__tax_group")
        .all()
    )
    buckets: dict[Decimal, dict[str, Decimal]] = {}
    for it in items:
        gross = it.amount or Decimal("0.00")
        rate = None
        if it.artikl and it.artikl.tax_group:
            rate = it.artikl.tax_group.rate
        rate = rate or Decimal("0.0000")
        if rate <= 0:
            continue
        percent = (rate * Decimal("100.0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        base = (gross / (Decimal("1.0") + rate))
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


def build_racun_zahtjev(invoice: SalesInvoice, config: FiscalConfig, *, id_poruke: str | None = None):
    from lxml import etree

    if not config.oib:
        raise ValueError("OIB nije postavljen (CompanyProfile.oib ili FISCAL_OIB).")

    op_oib = _operator_oib(config)
    if not op_oib:
        raise ValueError("FISCAL_OPERATOR_OIB nije postavljen (OIB operatera).")

    id_poruke = id_poruke or str(uuid.uuid4())
    nsmap = {"tns": FISCAL_TYPES_NS}
    root = etree.Element(etree.QName(FISCAL_TYPES_NS, "RacunZahtjev"), nsmap=nsmap)
    root.set("Id", id_poruke)

    zaglavlje = etree.SubElement(root, etree.QName(FISCAL_TYPES_NS, "Zaglavlje"))
    etree.SubElement(zaglavlje, etree.QName(FISCAL_TYPES_NS, "IdPoruke")).text = id_poruke
    etree.SubElement(zaglavlje, etree.QName(FISCAL_TYPES_NS, "DatumVrijeme")).text = _format_dt_xml(
        timezone.now()
    )

    racun = etree.SubElement(root, etree.QName(FISCAL_TYPES_NS, "Racun"))
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "Oib")).text = config.oib
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "USustPdv")).text = _usustpdv()
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "DatVrijeme")).text = _format_dt_xml(
        invoice.issued_at
    )
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "OznSlijed")).text = _ozn_slijed()

    br_rac = etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "BrRac"))
    etree.SubElement(br_rac, etree.QName(FISCAL_TYPES_NS, "BrOznRac")).text = str(invoice.rm_number)
    etree.SubElement(br_rac, etree.QName(FISCAL_TYPES_NS, "OznPosPr")).text = config.office_code
    etree.SubElement(br_rac, etree.QName(FISCAL_TYPES_NS, "OznNapUr")).text = config.device_code

    # Optional PDV breakdown (recommended; required in many real setups).
    _build_pdv_elements(invoice, racun, nsmap)

    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "IznosUkupno")).text = _format_amount(
        _round_2(invoice.total_amount)
    )
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "NacinPlac")).text = _nacin_placanja(invoice)
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "OibOper")).text = op_oib

    zki = generate_zki(invoice, config)
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "ZastKod")).text = zki
    etree.SubElement(racun, etree.QName(FISCAL_TYPES_NS, "NakDost")).text = "false"

    return root, zki


def _sign_racun_zahtjev(racun_zahtjev_el, *, key, cert, reference_uri: str):
    from cryptography.hazmat.primitives import serialization
    from signxml import XMLSigner, methods
    import signxml.signer

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    # Fiskalizacija protocol still requires SHA1-based XMLDSig.
    # signxml 4.x blocks SHA1 by default; temporarily bypass that guard for this call.
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

    # signxml needs to know which attribute is the ID for reference resolution.
    signed = signer.sign(
        racun_zahtjev_el,
        key=key,
        cert=cert_pem,
        reference_uri=reference_uri,
        id_attribute="Id",
    )
    return signed


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

    # Pull first error if present.
    code = doc.xpath("string(.//tns:Greska/tns:SifraGreske)", namespaces=ns).strip()
    msg = doc.xpath("string(.//tns:Greska/tns:PorukaGreske)", namespaces=ns).strip()
    if code or msg:
        return "", f"{code}: {msg}".strip(": ").strip()

    # SOAP Fault
    fault = doc.xpath("string(.//soapenv:Fault/faultstring)", namespaces=ns).strip()
    if fault:
        return "", fault

    return "", "Nepoznat odgovor (nema JIR ni greske)."


def send_sales_invoice(invoice: SalesInvoice, config: FiscalConfig) -> SendResult:
    """
    Sends RacunZahtjev to CIS and returns JIR + request/response XML.
    """
    if not is_send_enabled():
        raise RuntimeError("Slanje nije omoguceno (FISCAL_SEND_ENABLED=false).")

    racun_zahtjev, zki = build_racun_zahtjev(invoice, config)
    req_id = racun_zahtjev.get("Id")
    key, cert = _load_key_and_cert(config)
    signed = _sign_racun_zahtjev(racun_zahtjev, key=key, cert=cert, reference_uri=f"#{req_id}")

    soap_bytes = _wrap_soap(signed)
    url = _get_service_url(config)

    ca_path = os.getenv("FISCAL_TLS_CA_PATH", "").strip()
    verify = ca_path if ca_path else True
    timeout = float(os.getenv("FISCAL_HTTP_TIMEOUT", "15"))

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

    return SendResult(
        jir=jir,
        xml_request=soap_bytes.decode("utf-8", errors="replace"),
        xml_response=resp_xml.decode("utf-8", errors="replace"),
    )
