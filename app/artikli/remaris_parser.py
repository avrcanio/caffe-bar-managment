from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser


class _HiddenInputParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag != "input":
            return
        attrs = dict(attrs)
        if attrs.get("type") != "hidden":
            return
        input_id = attrs.get("id")
        if not input_id:
            return
        self.values[input_id] = attrs.get("value", "")


def parse_hidden_inputs(html_text):
    parser = _HiddenInputParser()
    parser.feed(html_text)
    return parser.values


def parse_bool(value):
    return str(value).strip().lower() == "true"


def parse_int(value):
    value = str(value or "").strip()
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_decimal(value):
    value = str(value or "").strip()
    if value == "":
        return None
    value = value.replace(".", "").replace(",", ".")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None
