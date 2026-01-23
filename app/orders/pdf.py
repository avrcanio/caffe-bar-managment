from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


def build_order_pdf(order, company):
    font_regular, font_bold = _register_fonts()
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 20 * mm

    if company and company.logo:
        try:
            logo = ImageReader(company.logo.path)
            c.drawImage(logo, 20 * mm, y - 20 * mm, width=30 * mm, height=20 * mm, preserveAspectRatio=True)
        except OSError:
            pass

    x_text = 60 * mm
    if company:
        c.setFont(font_bold, 12)
        c.drawString(x_text, y, company.name)
        c.setFont(font_regular, 10)
        y -= 5 * mm
        if company.address:
            c.drawString(x_text, y, company.address)
            y -= 5 * mm
        city_line = " ".join(filter(None, [company.postal_code, company.city]))
        if city_line:
            c.drawString(x_text, y, city_line)
            y -= 5 * mm
        if company.oib:
            c.drawString(x_text, y, f"OIB: {company.oib}")
            y -= 5 * mm
        contact_line = " | ".join(filter(None, [company.email, company.phone]))
        if contact_line:
            c.drawString(x_text, y, contact_line)

    y = height - 60 * mm
    c.setFont(font_bold, 14)
    c.drawString(20 * mm, y, f"Narudzba #{order.id}")

    y -= 8 * mm
    c.setFont(font_regular, 10)
    c.drawString(20 * mm, y, f"Datum: {order.ordered_at:%Y-%m-%d %H:%M}")
    y -= 5 * mm
    c.drawString(20 * mm, y, f"Dobavljac: {order.supplier.name}")
    y -= 5 * mm
    if order.payment_type:
        c.drawString(20 * mm, y, f"Tip placanja: {order.payment_type.name}")

    y -= 10 * mm
    c.setFont(font_bold, 10)
    y = _draw_table_header(c, y, font_bold)

    y -= 8 * mm
    c.setFont(font_regular, 10)

    row_height = 10 * mm
    code_offset = 0 * mm
    name_offset = 4 * mm

    tax_summary = {}

    for item in order.items.select_related("artikl__tax_group", "artikl__deposit", "unit_of_measure"):
        if y < 25 * mm:
            c.showPage()
            y = height - 20 * mm
            y = _draw_table_header(c, y, font_bold)
            y -= 8 * mm
            c.setFont(font_regular, 10)

        code = (item.artikl.code or "").strip() if item.artikl else ""
        name = (item.artikl.name or "").strip() if item.artikl else ""
        c.drawString(20 * mm, y - code_offset, code[:30])
        c.drawString(20 * mm, y - name_offset, name[:80])
        c.drawRightString(105 * mm, y - code_offset, _fmt_decimal(item.quantity))
        c.drawString(110 * mm, y - code_offset, item.unit_of_measure.name if item.unit_of_measure else "—")

        price = item.price or Decimal("0")
        line_net = Decimal(price) * Decimal(item.quantity or 0)
        tax_group = item.artikl.tax_group if item.artikl else None
        tax_rate = tax_group.rate if tax_group else Decimal("0")
        line_gross = line_net * (Decimal("1") + Decimal(tax_rate))

        c.drawRightString(145 * mm, y - code_offset, _fmt_decimal(price))
        c.drawRightString(165 * mm, y - code_offset, _fmt_percent(tax_rate))
        c.drawRightString(190 * mm, y - code_offset, _fmt_decimal(line_net))
        y -= row_height

        if tax_group:
            key = tax_group.pk
            if key not in tax_summary:
                tax_summary[key] = {
                    "tax_group": tax_group,
                    "rate": Decimal(tax_rate),
                    "tax": Decimal("0"),
                }
            tax_summary[key]["tax"] += line_net * tax_rate

    if y < 35 * mm:
        c.showPage()
        y = height - 20 * mm

    c.line(120 * mm, y, 190 * mm, y)
    y -= 6 * mm
    c.setFont(font_regular, 10)
    c.drawRightString(165 * mm, y, "Neto:")
    c.drawRightString(190 * mm, y, f"{_fmt_decimal(order.total_net)} EUR")
    for item in sorted(tax_summary.values(), key=lambda entry: (entry["rate"], entry["tax_group"].name)):
        y -= 6 * mm
        tax = item["tax"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if tax == Decimal("0"):
            continue
        rate_label = _fmt_percent_two(item["rate"])
        label = f"PDV ({item['tax_group'].name} {rate_label}):"
        c.drawRightString(165 * mm, y, label)
        c.drawRightString(190 * mm, y, f"{_fmt_decimal(tax)} EUR")
    y -= 6 * mm
    c.drawRightString(165 * mm, y, "Povratna naknada:")
    c.drawRightString(190 * mm, y, f"{_fmt_decimal(order.total_deposit)} EUR")
    y -= 6 * mm
    c.setFont(font_bold, 10)
    c.drawRightString(165 * mm, y, "UKUPNO (EUR):")
    c.drawRightString(190 * mm, y, f"{_fmt_decimal(order.total_gross)} EUR")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def _register_fonts():
    font_dir = "/usr/share/fonts/truetype/dejavu"
    regular_path = os.path.join(font_dir, "DejaVuSans.ttf")
    bold_path = os.path.join(font_dir, "DejaVuSans-Bold.ttf")

    if os.path.exists(regular_path) and os.path.exists(bold_path):
        if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVuSans", regular_path))
        if "DejaVuSans-Bold" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", bold_path))
        return "DejaVuSans", "DejaVuSans-Bold"

    return "Helvetica", "Helvetica-Bold"


def _draw_table_header(c, y, font_bold):
    c.setFont(font_bold, 10)
    c.drawString(20 * mm, y, "Artikl")
    c.drawRightString(105 * mm, y, "Kolicina")
    c.drawString(110 * mm, y, "JM")
    c.drawRightString(145 * mm, y, "Cijena")
    c.drawRightString(165 * mm, y, "PDV")
    c.drawRightString(190 * mm, y, "Iznos")
    c.line(20 * mm, y - 2 * mm, 190 * mm, y - 2 * mm)
    return y


def _fmt_decimal(value):
    if value is None:
        return "0,00"
    try:
        dec = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return "0,00"
    return f"{dec:.2f}".replace(".", ",")


def _fmt_percent(value):
    try:
        dec = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return "0%"
    return f"{(dec * 100):.0f}%"


def _fmt_percent_two(value):
    try:
        dec = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return "0,00%"
    return f"{(dec * 100):.2f}%".replace(".", ",")
