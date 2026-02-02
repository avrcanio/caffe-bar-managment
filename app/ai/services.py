import json
import os
import re
from urllib.parse import quote
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import requests
from django.db.models import Count, Sum, Q
from django.utils import timezone

from artikli.models import Artikl, ArtiklDetail, Normativ, DrinkCategory
from sales.models import SalesPriceItem
from orders.models import SupplierPriceItem
from django.contrib.auth import get_user_model
from contacts.models import Supplier
from orders.models import PurchaseOrder, PurchaseOrderItem
from sales.models import SalesInvoice, SalesInvoiceItem
from orders.models import WarehouseInput, WarehouseInputItem
from stock.models import WarehouseId, WarehouseStock


@dataclass
class ToolResult:
    name: str
    arguments: Dict[str, Any]
    result: Any


def _openai_settings():
    return {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "timeout": int(os.getenv("OPENAI_TIMEOUT", "30")),
        "org": os.getenv("OPENAI_ORG", ""),
        "project": os.getenv("OPENAI_PROJECT", ""),
    }


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(value).date()


def _parse_datetime(value: Optional[str]) -> datetime:
    if not value:
        return timezone.now()
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.get_current_timezone())
    return datetime.fromisoformat(value)

def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(val) for key, val in value.items()}
    return value

def _json_dumps(value: Any) -> str:
    return json.dumps(_normalize(value), ensure_ascii=False)


def _extract_time_filter(normalized_question: str, today: date):
    q = (normalized_question or "").lower()
    q_ascii = (
        q.replace("č", "c")
        .replace("ć", "c")
        .replace("ž", "z")
        .replace("š", "s")
        .replace("đ", "dj")
    )
    if "danas" in q_ascii:
        return {"label": "danas", "start": today, "end": today}
    if "jucer" in q_ascii:
        target = today - timedelta(days=1)
        return {"label": "jucer", "start": target, "end": target}
    if "prekjucer" in q_ascii:
        target = today - timedelta(days=2)
        return {"label": "prekjucer", "start": target, "end": target}
    if "prosli tjedan" in q_ascii:
        week_start = today - timedelta(days=today.weekday())
        target_start = week_start - timedelta(days=7)
        target_end = week_start - timedelta(days=1)
        return {"label": "prosli tjedan", "start": target_start, "end": target_end}
    if "prosli mjesec" in q_ascii:
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        first_prev_month = last_prev_month.replace(day=1)
        return {"label": "prosli mjesec", "start": first_prev_month, "end": last_prev_month}
    match = re.search(r"prije\s+(\d+)\s+dana", q_ascii)
    if match:
        days = int(match.group(1))
        if days >= 1:
            target = today - timedelta(days=days)
            return {"label": f"prije {days} dana", "start": target, "end": target}
    match = re.search(r"prije\s+([a-z]+)\s+dana", q_ascii)
    if match:
        word = match.group(1)
        word_map = {
            "jedan": 1,
            "dva": 2,
            "tri": 3,
            "cetiri": 4,
            "pet": 5,
            "sest": 6,
            "sedam": 7,
            "osam": 8,
            "devet": 9,
            "deset": 10,
        }
        if word in word_map:
            days = word_map[word]
            target = today - timedelta(days=days)
            return {"label": f"prije {days} dana", "start": target, "end": target}
    return None


def _match_drink_category(normalized_question: str) -> Optional[Dict[str, Any]]:
    q = (normalized_question or "").lower()
    q_ascii = (
        q.replace("č", "c")
        .replace("ć", "c")
        .replace("ž", "z")
        .replace("š", "s")
        .replace("đ", "dj")
    )
    synonym_groups = [
        ("pivo", ["pivo", "piva", "pive"]),
        ("vino", ["vino", "vina"]),
        ("sok", ["sok", "sokovi"]),
        ("voda", ["voda", "vode"]),
        ("rakija", ["rakija", "rakije"]),
        ("kava", ["kava", "kave"]),
    ]
    for canonical, tokens in synonym_groups:
        if any(token in q_ascii for token in tokens):
            qs = DrinkCategory.objects.filter(is_active=True)
            token_q = Q()
            for token in tokens:
                token_q |= Q(name__icontains=token)
            matches = list(qs.filter(token_q))
            if matches:
                min_level = min(cat.level for cat in matches)
                top_matches = [cat for cat in matches if cat.level == min_level]
                ids: List[int] = []
                for cat in top_matches:
                    ids.extend(
                        list(cat.get_descendants(include_self=True).values_list("id", flat=True))
                    )
                label = top_matches[0].name if len(top_matches) == 1 else "kategorije"
                return {"label": label, "ids": list(sorted(set(ids)))}
    categories = list(DrinkCategory.objects.filter(is_active=True).values_list("id", "name"))
    for category_id, name in categories:
        if not name:
            continue
        name_ascii = (
            name.lower()
            .replace("č", "c")
            .replace("ć", "c")
            .replace("ž", "z")
            .replace("š", "s")
            .replace("đ", "dj")
        )
        if name_ascii and name_ascii in q_ascii:
            cat = DrinkCategory.objects.filter(id=category_id).first()
            if not cat:
                return {"label": name, "ids": [category_id]}
            root = cat.get_root()
            ids = list(root.get_descendants(include_self=True).values_list("id", flat=True))
            return {"label": root.name, "ids": ids}
    return None


def _find_artikl(query: str) -> Optional[Artikl]:
    query = (query or "").strip()
    if not query:
        return None
    lowered = query.lower()
    if lowered.startswith("id "):
        query = query[3:].strip()
    elif lowered.startswith("rm_id "):
        query = query[6:].strip()
    elif lowered.startswith("rmid "):
        query = query[5:].strip()
    elif lowered.startswith("rm "):
        query = query[3:].strip()
    if query.isdigit():
        pk = int(query)
        artikl = Artikl.objects.filter(id=pk).first()
        if artikl:
            return artikl
        artikl = Artikl.objects.filter(rm_id=pk).first()
        if artikl:
            return artikl
    artikl = Artikl.objects.filter(code__iexact=query).first()
    if artikl:
        return artikl
    return Artikl.objects.filter(name__icontains=query).order_by("name").first()


def _extract_artikl_query(question: str) -> str:
    query = (question or "").strip()
    if not query:
        return ""
    lowered = query.lower().replace("đ", "dj")
    prefixes = [
        "pronadi mi artikl ",
        "pronadji mi artikl ",
        "pronadi artikl ",
        "pronadji artikl ",
        "pronadi mi ",
        "pronadji mi ",
    ]
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return query[len(prefix) :].strip()
    return query


def _extract_list_query(question: str) -> str:
    query = (question or "").strip()
    if not query:
        return ""
    lowered = query.lower().replace("đ", "dj").replace("š", "s").replace("č", "c").replace("ć", "c").replace("ž", "z")
    prefixes = [
        "prikazi mi artikle ",
        "pokazi mi artikle ",
        "prikazi artikle ",
        "pokazi artikle ",
        "prikazi mi ",
        "pokazi mi ",
        "prikazi ",
        "pokazi ",
    ]
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return query[len(prefix) :].strip()
    return query


def _extract_artikl_list_query(question: str) -> str:
    query = (question or "").strip()
    if not query:
        return ""
    lowered = query.lower().replace("đ", "dj").replace("š", "s").replace("č", "c").replace("ć", "c").replace("ž", "z")
    prefixes = [
        "artikli ",
        "artikle ",
        "artikl ",
    ]
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return query[len(prefix) :].strip()
    return ""


def _extract_price_query(question: str) -> str:
    query = (question or "").strip()
    if not query:
        return ""
    lowered = query.lower().replace("đ", "dj")
    prefixes = [
        "koja je prodajna cijena ",
        "koja je cijena ",
        "prodajna cijena ",
        "cijena ",
    ]
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return query[len(prefix) :].strip()
    return query


def _find_sales_price_item(artikl: Artikl, warehouse_rm_id: Optional[int] = None):
    now = timezone.now()
    qs = SalesPriceItem.objects.select_related("price_list").filter(
        artikl=artikl,
        is_active=True,
        price_list__is_active=True,
        price_list__valid_from__lte=now,
    ).filter(Q(price_list__valid_to__isnull=True) | Q(price_list__valid_to__gte=now))
    if warehouse_rm_id is not None:
        qs = qs.filter(price_list__warehouse__rm_id=warehouse_rm_id)
    qs_default = qs.filter(price_list__is_default=True).order_by("-price_list__valid_from")
    item = qs_default.first()
    if item:
        return item
    return qs.order_by("-price_list__valid_from").first()


def _find_supplier_price_item(artikl: Artikl):
    today = timezone.localdate()
    qs = SupplierPriceItem.objects.select_related("price_list", "price_list__supplier").filter(
        artikl=artikl,
        price_list__is_active=True,
    )
    qs = qs.filter(
        Q(price_list__valid_from__isnull=True) | Q(price_list__valid_from__lte=today)
    ).filter(Q(price_list__valid_to__isnull=True) | Q(price_list__valid_to__gte=today))
    return qs.order_by("-price_list__created_at").first()


def _build_artikl_info(artikl: Artikl, warehouse_rm_id: Optional[int] = None) -> str:
    base = (
        f"{artikl.name} (id {artikl.id}, rm_id {artikl.rm_id}, sifra {artikl.code}, "
        f"prodajni {'da' if artikl.is_sellable else 'ne'}, skladisni {'da' if artikl.is_stock_item else 'ne'})"
    )
    lines = [f"{base}."]
    price_item = _find_sales_price_item(artikl, warehouse_rm_id=warehouse_rm_id)
    if price_item:
        lines.append(f"Prodajna cijena: {price_item.unit_price_gross} EUR.")
    if artikl.is_stock_item:
        stock_qs = WarehouseStock.objects.filter(product_id=artikl.rm_id)
        if warehouse_rm_id is not None:
            stock_qs = stock_qs.filter(warehouse_id=warehouse_rm_id)
        stock_rows = list(
            stock_qs.values("warehouse_id", "internal_quantity", "unit", "product_name")
        )
        if stock_rows:
            warehouse_map = {
                wh.rm_id: wh.name for wh in WarehouseId.objects.filter(
                    rm_id__in=[row["warehouse_id"] for row in stock_rows]
                )
            }
            stock_parts = []
            for row in stock_rows:
                wh_label = warehouse_map.get(row["warehouse_id"]) or row["warehouse_id"]
                stock_parts.append(
                    f"skladiste {wh_label}: {row['internal_quantity']} {row.get('unit') or ''}".strip()
                )
            lines.append("Stanje:")
            for part in stock_parts:
                lines.append(f"{part};")
        supplier_price = _find_supplier_price_item(artikl)
        if supplier_price:
            lines.append(
                "Nabavna cijena: "
                f"{supplier_price.price} {supplier_price.price_list.currency} "
                f"({supplier_price.price_list.supplier.name})."
            )
    try:
        normativ = artikl.normativ
    except Normativ.DoesNotExist:
        normativ = None
    if normativ:
        items = list(normativ.items.select_related("ingredient").order_by("id"))
        if items:
            parts = []
            glasses_info = None
            for item in items:
                parts.append(f"{item.ingredient.name} x {item.qty}")
                if (
                    "1 l" in (item.ingredient.name or "").lower()
                    and item.qty
                    and item.qty > 0
                ):
                    try:
                        glasses = (Decimal("1") / item.qty).quantize(Decimal("0.01"))
                        glasses_info = (
                            f"Iz 1 l dobijes ~{glasses} casa za {artikl.name}."
                        )
                    except Exception:
                        glasses_info = None
            lines.append("Normativ: " + ", ".join(parts) + ".")
            if glasses_info:
                lines.append(f"{glasses_info}.")
            for item in items:
                if "1 l" in (item.ingredient.name or "").lower():
                    supplier_price = _find_supplier_price_item(item.ingredient)
                    if supplier_price:
                        lines.append(
                            f"Nabavna cijena {item.ingredient.name}: "
                            f"{supplier_price.price} {supplier_price.price_list.currency} "
                            f"({supplier_price.price_list.supplier.name})."
                        )
                    break
    return "\n".join(lines)


def tool_get_stock_balance(
    query: str,
    warehouse_rm_id: Optional[int] = None,
    waiter_user_id: Optional[int] = None,
    waiter_name: Optional[str] = None,
):
    _ = waiter_user_id, waiter_name
    artikl = _find_artikl(query)
    if not artikl:
        return {"error": "Artikl nije pronaden."}
    if not artikl.is_stock_item:
        result = {
            "error": "Artikl nije skladisni (is_stock_item = False).",
            "artikl_id": artikl.id,
            "rm_id": artikl.rm_id,
            "name": artikl.name,
        }
        try:
            normativ = artikl.normativ
        except Normativ.DoesNotExist:
            normativ = None
        if normativ:
            items = list(normativ.items.select_related("ingredient").order_by("id"))
            if items:
                result["normativ"] = [
                    {"ingredient": item.ingredient.name, "qty": str(item.qty)}
                    for item in items
                ]
        return result
    qs = WarehouseStock.objects.filter(product_id=artikl.rm_id)
    if warehouse_rm_id is not None:
        qs = qs.filter(warehouse_id=warehouse_rm_id)
    rows = list(
        qs.values(
            "warehouse_id",
            "quantity",
            "internal_quantity",
            "unit",
            "product_name",
        )
    )
    return {
        "artikl_id": artikl.id,
        "rm_id": artikl.rm_id,
        "name": artikl.name,
        "rows": rows,
    }

def tool_list_warehouses(include_hidden: bool = False):
    qs = WarehouseId.objects.all()
    if not include_hidden:
        qs = qs.filter(hidden=False)
    rows = list(
        qs.order_by("ordinal", "name").values(
            "rm_id",
            "name",
            "hidden",
            "external_location_id",
        )
    )
    return {"warehouses": rows}

def tool_list_suppliers(limit: Optional[int] = None):
    qs = Supplier.objects.all().order_by("name")
    if limit is not None:
        qs = qs[: max(1, min(int(limit or 0), 200))]
    rows = list(
        qs.values(
            "id",
            "rm_id",
            "name",
            "town",
            "tax_number",
            "orders_email",
        )
    )
    return {"suppliers": rows}


def tool_get_sales_summary(
    date_from: str,
    date_to: str,
    warehouse_rm_id: Optional[int] = None,
    waiter_user_id: Optional[int] = None,
    waiter_name: Optional[str] = None,
):
    start = _parse_date(date_from)
    end = _parse_date(date_to)
    if not start or not end:
        return {"error": "date_from i date_to su obavezni."}
    qs = SalesInvoice.objects.filter(issued_on__gte=start, issued_on__lte=end)
    if warehouse_rm_id is not None:
        qs = qs.filter(warehouse_id=warehouse_rm_id)
    if waiter_user_id is not None:
        qs = qs.filter(user_id=waiter_user_id)
    elif waiter_name:
        qs = qs.filter(waiter_name__icontains=waiter_name)
    agg = qs.aggregate(
        count=Count("id"),
        net=Sum("net_amount"),
        vat=Sum("vat_amount"),
        total=Sum("total_amount"),
    )
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "warehouse_rm_id": warehouse_rm_id,
        "count": agg["count"],
        "net": str(agg["net"] or 0),
        "vat": str(agg["vat"] or 0),
        "total": str(agg["total"] or 0),
    }


def tool_get_top_selling_items(
    date_from: str,
    date_to: str,
    warehouse_rm_id: Optional[int] = None,
    waiter_user_id: Optional[int] = None,
    waiter_name: Optional[str] = None,
    limit: int = 10,
    order_by: str = "qty",
):
    start = _parse_date(date_from)
    end = _parse_date(date_to)
    if not start or not end:
        return {"error": "date_from i date_to su obavezni."}
    qs = SalesInvoiceItem.objects.select_related("invoice", "artikl").filter(
        invoice__issued_on__gte=start,
        invoice__issued_on__lte=end,
    )
    if warehouse_rm_id is not None:
        qs = qs.filter(invoice__warehouse_id=warehouse_rm_id)
    if waiter_user_id is not None:
        qs = qs.filter(invoice__user_id=waiter_user_id)
    elif waiter_name:
        qs = qs.filter(invoice__waiter_name__icontains=waiter_name)
    rows = qs.values("artikl_id", "product_name").annotate(
        qty=Sum("quantity"), amount=Sum("amount")
    )
    order_field = "amount" if order_by == "amount" else "qty"
    rows = rows.order_by(f"-{order_field}")[: max(1, min(int(limit or 10), 50))]
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "warehouse_rm_id": warehouse_rm_id,
        "order_by": order_field,
        "items": [
            {
                "artikl_id": row["artikl_id"],
                "product_name": row["product_name"],
                "qty": str(row["qty"] or 0),
                "amount": str(row["amount"] or 0),
            }
            for row in rows
        ],
    }


def tool_get_sales_by_product(
    date_from: str,
    date_to: str,
    query: str,
    warehouse_rm_id: Optional[int] = None,
    waiter_user_id: Optional[int] = None,
    waiter_name: Optional[str] = None,
):
    start = _parse_date(date_from)
    end = _parse_date(date_to)
    if not start or not end:
        return {"error": "date_from i date_to su obavezni."}
    if not query:
        return {"error": "query je obavezan."}
    qs = SalesInvoiceItem.objects.select_related("invoice").filter(
        invoice__issued_on__gte=start,
        invoice__issued_on__lte=end,
    )
    if warehouse_rm_id is not None:
        qs = qs.filter(invoice__warehouse_id=warehouse_rm_id)
    if waiter_user_id is not None:
        qs = qs.filter(invoice__user_id=waiter_user_id)
    elif waiter_name:
        qs = qs.filter(invoice__waiter_name__icontains=waiter_name)
    qs = qs.filter(product_name__icontains=query)
    agg = qs.aggregate(qty=Sum("quantity"), amount=Sum("amount"), count=Count("id"))
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "warehouse_rm_id": warehouse_rm_id,
        "query": query,
        "count": agg["count"],
        "qty": str(agg["qty"] or 0),
        "amount": str(agg["amount"] or 0),
    }


def tool_create_purchase_order(
    supplier_id: int,
    ordered_at: Optional[str] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    payment_type_id: Optional[int] = None,
):
    if not supplier_id:
        return {"error": "supplier_id je obavezan."}
    if not items:
        return {"error": "items je obavezan."}
    ordered_at_dt = _parse_datetime(ordered_at)
    order = PurchaseOrder.objects.create(
        supplier_id=supplier_id,
        ordered_at=ordered_at_dt,
        payment_type_id=payment_type_id,
        status=PurchaseOrder.STATUS_CREATED,
    )
    created_items = []
    for item in items:
        artikl_id = item.get("artikl_id")
        quantity = item.get("quantity")
        price = item.get("price")
        if not artikl_id or quantity is None:
            continue
        artikl = Artikl.objects.filter(id=int(artikl_id)).first()
        if not artikl:
            continue
        unit = None
        detail = ArtiklDetail.objects.filter(artikl=artikl).select_related("unit_of_measure").first()
        if detail and detail.unit_of_measure:
            unit = detail.unit_of_measure
        if not unit:
            raise ValueError(f"Artikl {artikl.id} nema unit_of_measure.")
        created = PurchaseOrderItem.objects.create(
            order=order,
            artikl=artikl,
            quantity=Decimal(str(quantity)),
            unit_of_measure=unit,
            price=Decimal(str(price)) if price is not None else None,
        )
        created_items.append(created.id)
    order.refresh_from_db()
    return {
        "order_id": order.id,
        "status": order.status,
        "total_net": str(order.total_net),
        "total_gross": str(order.total_gross),
        "total_deposit": str(order.total_deposit),
        "items_created": created_items,
    }


def tool_get_supplier_inputs(
    supplier_query: str,
    date_from: str,
    date_to: str,
):
    start = _parse_date(date_from)
    end = _parse_date(date_to)
    if not start or not end:
        return {"error": "date_from i date_to su obavezni."}
    if not supplier_query:
        return {"error": "supplier_query je obavezan."}
    inputs = WarehouseInput.objects.select_related("supplier", "payment_type").filter(
        supplier__name__icontains=supplier_query,
        date__gte=start,
        date__lte=end,
        is_canceled=False,
    )
    supplier_name = inputs.values_list("supplier__name", flat=True).first()
    inputs_rows = list(
        inputs.values(
            "id",
            "date",
            "supplier__name",
            "payment_type__name",
            "total",
        )
    )
    total_sum = inputs.aggregate(total=Sum("total"))["total"] or 0
    items = WarehouseInputItem.objects.select_related("warehouse_input", "artikl").filter(
        warehouse_input__in=inputs
    )
    item_rows = (
        items.values("artikl_id", "artikl__name")
        .annotate(qty=Sum("quantity"), amount=Sum("total"))
        .order_by("-amount")
    )
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "supplier_query": supplier_query,
        "supplier_name": supplier_name,
        "total": str(total_sum),
        "inputs": [
            {
                "id": row["id"],
                "date": row["date"].isoformat() if row["date"] else None,
                "supplier": row["supplier__name"],
                "payment_type": row["payment_type__name"],
                "total": str(row["total"] or 0),
            }
            for row in inputs_rows
        ],
        "items": [
            {
                "artikl_id": row["artikl_id"],
                "artikl_name": row["artikl__name"],
                "qty": str(row["qty"] or 0),
                "amount": str(row["amount"] or 0),
            }
            for row in item_rows
        ],
    }


def _tool_definitions():
    return [
        {
            "type": "function",
            "name": "list_warehouses",
            "description": "Vrati popis skladista (rm_id i naziv).",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_hidden": {"type": "boolean", "nullable": True},
                },
            },
        },
        {
            "type": "function",
            "name": "list_suppliers",
            "description": "Vrati popis dobavljaca.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "nullable": True},
                },
            },
        },
        {
            "type": "function",
            "name": "get_stock_balance",
            "description": "Vrati stanje artikla na skladistu (po nazivu, sifri ili ID-u).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "warehouse_rm_id": {"type": "integer", "nullable": True},
                    "waiter_user_id": {"type": "integer", "nullable": True},
                    "waiter_name": {"type": "string", "nullable": True},
                },
                "required": ["query"],
            },
        },
        {
            "type": "function",
            "name": "get_sales_summary",
            "description": "Sazetak prodaje za raspon datuma.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "warehouse_rm_id": {"type": "integer", "nullable": True},
                    "waiter_user_id": {"type": "integer", "nullable": True},
                    "waiter_name": {"type": "string", "nullable": True},
                },
                "required": ["date_from", "date_to"],
            },
        },
        {
            "type": "function",
            "name": "get_top_selling_items",
            "description": "Top prodavani artikli u rasponu datuma.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "warehouse_rm_id": {"type": "integer", "nullable": True},
                    "waiter_user_id": {"type": "integer", "nullable": True},
                    "waiter_name": {"type": "string", "nullable": True},
                    "limit": {"type": "integer", "nullable": True},
                    "order_by": {"type": "string", "nullable": True},
                },
                "required": ["date_from", "date_to"],
            },
        },
        {
            "type": "function",
            "name": "get_supplier_inputs",
            "description": "Primke po dobavljacu i razdoblju.",
            "parameters": {
                "type": "object",
                "properties": {
                    "supplier_query": {"type": "string"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                },
                "required": ["supplier_query", "date_from", "date_to"],
            },
        },
        {
            "type": "function",
            "name": "get_sales_by_product",
            "description": "Prodaja po artiklu (filtrirano po nazivu artikla).",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "query": {"type": "string"},
                    "warehouse_rm_id": {"type": "integer", "nullable": True},
                    "waiter_user_id": {"type": "integer", "nullable": True},
                    "waiter_name": {"type": "string", "nullable": True},
                },
                "required": ["date_from", "date_to", "query"],
            },
        },
        {
            "type": "function",
            "name": "create_purchase_order",
            "description": "Kreira narudzbu i stavke. Jedini dozvoljeni write.",
            "parameters": {
                "type": "object",
                "properties": {
                    "supplier_id": {"type": "integer"},
                    "ordered_at": {"type": "string", "nullable": True},
                    "payment_type_id": {"type": "integer", "nullable": True},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "artikl_id": {"type": "integer"},
                                "quantity": {"type": "number"},
                                "price": {"type": "number", "nullable": True},
                            },
                            "required": ["artikl_id", "quantity"],
                        },
                    },
                },
                "required": ["supplier_id", "items"],
            },
        },
    ]


def _call_openai(
    instructions: str,
    input_items: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    previous_response_id: Optional[str] = None,
):
    conf = _openai_settings()
    if not conf["api_key"]:
        raise RuntimeError("OPENAI_API_KEY nije postavljen.")
    payload = {
        "model": conf["model"],
        "instructions": instructions,
        "input": input_items,
        "tools": tools,
    }
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id
    headers = {
        "Authorization": f"Bearer {conf['api_key']}",
        "Content-Type": "application/json",
    }
    if conf["org"]:
        headers["OpenAI-Organization"] = conf["org"]
    if conf["project"]:
        headers["OpenAI-Project"] = conf["project"]
    resp = requests.post(
        f"{conf['base_url'].rstrip('/')}/responses",
        headers=headers,
        json=payload,
        timeout=conf["timeout"],
    )
    if not resp.ok:
        raise RuntimeError(f"OpenAI error {resp.status_code}: {resp.text}")
    return resp.json()


def _extract_output_text(response: Dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if output_text:
        return output_text
    texts: List[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if part.get("type") == "output_text":
                texts.append(part.get("text", ""))
    return "".join(texts).strip()


def handle_ai_query(question: str):
    normalized_question = (question or "").lower()
    normalized_question_ascii = normalized_question.replace("đ", "dj")
    today = timezone.localdate()
    time_filter = _extract_time_filter(normalized_question, today)
    drink_category_match = _match_drink_category(normalized_question) if time_filter else None
    waiter_user = None
    waiter_name = None
    if "konobar" in normalized_question:
        cleaned = normalized_question.replace("konobar", "").strip()
        waiter_name = cleaned or None
    User = get_user_model()
    if not waiter_user and normalized_question:
        parts = normalized_question.split()
        if len(parts) >= 2:
            first = parts[0]
            last = parts[1]
            waiter_user = User.objects.filter(first_name__iexact=first, last_name__iexact=last).first()
        if not waiter_user:
            waiter_user = User.objects.filter(username__iexact=normalized_question).first()
        if not waiter_user:
            waiter_user = User.objects.filter(first_name__iexact=normalized_question).first()
        if not waiter_user:
            waiter_user = User.objects.filter(last_name__iexact=normalized_question).first()
    if waiter_user:
        waiter_name = None
    warehouse_match = None
    for wh in WarehouseId.objects.all():
        name = (wh.name or "").lower()
        if name and name in normalized_question:
            warehouse_match = wh
            break
    warehouse_rm_id = warehouse_match.rm_id if warehouse_match else None

    if "prikaz" in normalized_question_ascii or "pokaz" in normalized_question_ascii:
        query = _extract_list_query(question)
        if query:
            matches = list(
                Artikl.objects.filter(name__icontains=query).order_by("name")[:50]
            )
            if not matches:
                return f"Nema artikala za upit: {query}.", []
            lines = [
                (
                    f"- [{a.name}](/admin/artikli/artikl/{a.id}/change/) "
                    f"(id {a.id}, rm_id {a.rm_id}, sifra {a.code}) "
                    f"detalji: /ai?q={quote(a.name)}"
                )
                for a in matches
            ]
            return "Artikli:\n" + "\n".join(lines), []

    artikl_list_query = _extract_artikl_list_query(question)
    if artikl_list_query:
        matches = list(
            Artikl.objects.filter(name__icontains=artikl_list_query).order_by("name")[:50]
        )
        if not matches:
            return f"Nema artikala za upit: {artikl_list_query}.", []
        lines = [
            (
                f"- [{a.name}](/admin/artikli/artikl/{a.id}/change/) "
                f"(id {a.id}, rm_id {a.rm_id}, sifra {a.code}) "
                f"detalji: /ai?q={quote(a.name)}"
            )
            for a in matches
        ]
        return "Artikli:\n" + "\n".join(lines), []

    if "skladist" in normalized_question:
        query = _extract_artikl_query(question)
        artikl = _find_artikl(query)
        if artikl and not artikl.is_stock_item:
            try:
                normativ = artikl.normativ
            except Normativ.DoesNotExist:
                normativ = None
            if normativ:
                items = list(normativ.items.select_related("ingredient").order_by("id"))
                if items:
                    parts = [f"{item.ingredient.name} x {item.qty}" for item in items]
                    return (
                        f"{artikl.name} nije skladisni artikl (is_stock_item = False). "
                        f"Normativ: {', '.join(parts)}.",
                        [],
                    )
            return (
                f"{artikl.name} nije skladisni artikl (is_stock_item = False).",
                [],
            )

    if not any(
        key in normalized_question
        for key in (
            "prodaja",
            "promet",
            "dobavljac",
            "dobavljač",
            "nema prodaje",
            "jucer",
            "jučer",
            "danas",
            "skladist",
            "cijena",
            "konobar",
            "daj sve informacije",
        )
    ):
        query = (question or "").strip()
        if query:
            list_candidate = (
                query.lower()
                .replace("id", "")
                .replace("artikl", "")
                .replace("artikli", "")
                .strip()
            )
            if re.sub(r"[0-9,\s;]", "", list_candidate) == "":
                ids = [int(match) for match in re.findall(r"\b\d+\b", list_candidate)]
                if len(ids) >= 2:
                    parts = []
                    for idx, artikl_id in enumerate(ids, start=1):
                        artikl = _find_artikl(str(artikl_id))
                        if not artikl:
                            parts.append(f"{idx}. Artikl {artikl_id} nije pronaden.")
                        else:
                            parts.append(f"{idx}. {_build_artikl_info(artikl, warehouse_rm_id=warehouse_rm_id)}")
                    return "Stanje artikala:\n" + "\n\n".join(parts), []
            query_lower = query.lower()
            if query.isdigit() or query_lower.startswith(("id ", "rm_id ", "rmid ", "rm ")):
                artikl = _find_artikl(query)
                if artikl:
                    return _build_artikl_info(artikl, warehouse_rm_id=warehouse_rm_id), []
            matches = list(
                Artikl.objects.filter(name__icontains=query).order_by("name")[:50]
            )
            if len(matches) > 1:
                lines = [
                    f"- {a.name} (id {a.id}, rm_id {a.rm_id})"
                    for a in matches
                ]
                return "Artikli:\n" + "\n".join(lines), []
            artikl = matches[0] if matches else None
            if artikl:
                return _build_artikl_info(artikl, warehouse_rm_id=warehouse_rm_id), []

    if "cijena" in normalized_question:
        query = _extract_price_query(question)
        artikl = _find_artikl(query)
        if artikl:
            item = _find_sales_price_item(artikl, warehouse_rm_id=warehouse_rm_id)
            if item:
                price = item.unit_price_gross
                pricelist = item.price_list.name
                return (
                    f"Prodajna cijena za {artikl.name} je {price} EUR (cjenik: {pricelist}).",
                    [],
                )
            return f"Nemam prodajnu cijenu za {artikl.name}.", []

    if "artikl" in normalized_question_ascii and (
        "pronadi" in normalized_question_ascii or "pronadji" in normalized_question_ascii
    ):
        query = _extract_artikl_query(question)
        if query:
            matches = list(
                Artikl.objects.filter(name__icontains=query).order_by("name")[:10]
            )
            if not matches:
                return f"Nema artikla za upit: {query}.", []
            lines = []
            for artikl in matches:
                lines.append("- " + _build_artikl_info(artikl, warehouse_rm_id=warehouse_rm_id))
            return "Pronadjeni artikli:\n" + "\n".join(lines), []

    if "daj sve informacije" in normalized_question:
        warehouses = tool_list_warehouses()
        warehouses = _normalize(warehouses)
        lines = [
            f"- {row['name']} (ID: {row['rm_id']})"
            for row in warehouses.get("warehouses", [])
        ]
        return (
            "Mogu dati ove informacije:\n"
            "- popis skladista\n"
            "- popis dobavljaca\n"
            "- prodaju za datum/raspon\n"
            "- top artikle za datum/raspon\n"
            "- stanje artikla\n\n"
            "Skladista:\n" + "\n".join(lines),
            [ToolResult(name="list_warehouses", arguments={"include_hidden": False}, result=warehouses)],
        )

    if "dobavljac" in normalized_question or "dobavljač" in normalized_question:
        suppliers = tool_list_suppliers()
        suppliers = _normalize(suppliers)
        rows = suppliers.get("suppliers", [])
        if rows:
            lines = [
                f"- {row.get('name')} (ID: {row.get('id')}, RM: {row.get('rm_id')})"
                for row in rows
            ]
            answer = "Dobavljaci:\n" + "\n".join(lines)
        else:
            answer = "Nema dobavljaca."
        return answer, [
            ToolResult(
                name="list_suppliers",
                arguments={"limit": None},
                result=suppliers,
            )
        ]

    if "nema prodaje" in normalized_question:
        target = today - timedelta(days=1)
        summary = tool_get_sales_summary(
            date_from=target.isoformat(),
            date_to=target.isoformat(),
            warehouse_rm_id=warehouse_rm_id,
            waiter_user_id=waiter_user.id if waiter_user else None,
            waiter_name=waiter_name,
        )
        summary = _normalize(summary)
        count = summary.get("count", 0)
        net = summary.get("net", "0")
        vat = summary.get("vat", "0")
        total = summary.get("total", "0")
        if count:
            answer = (
                f"Jucerasnja prodaja ({target.isoformat()}) ima {count} racuna. "
                f"Neto {net}, PDV {vat}, ukupno {total}."
            )
        else:
            answer = f"Jucerasnja prodaja ({target.isoformat()}) je 0, bez racuna."
        return answer, [
            ToolResult(
                name="get_sales_summary",
                arguments={"date_from": target.isoformat(), "date_to": target.isoformat(), "warehouse_rm_id": warehouse_rm_id},
                result=summary,
            )
        ]

    def _coffee_sales_response(label: str, date_from: date, date_to: date):
        qs = SalesInvoiceItem.objects.select_related("invoice", "artikl").filter(
            invoice__issued_on__gte=date_from,
            invoice__issued_on__lte=date_to,
            artikl__drink_category__name__icontains="kava",
        )
        if warehouse_rm_id is not None:
            qs = qs.filter(invoice__warehouse_id=warehouse_rm_id)
        rows = (
            qs.values("artikl_id", "product_name", "artikl__name")
            .annotate(qty=Sum("quantity"), amount=Sum("amount"))
            .order_by("-amount")
        )
        items = [
            {
                "artikl_id": row["artikl_id"],
                "product_name": row.get("artikl__name") or row.get("product_name"),
                "qty": str(row["qty"] or 0),
                "amount": str(row["amount"] or 0),
            }
            for row in rows
        ]
        if items:
            lines = [
                f"{idx+1}. {item['product_name']} ({item['qty']} kom, {item['amount']} EUR)"
                for idx, item in enumerate(items)
            ]
            scope = f" za skladiste {warehouse_rm_id}" if warehouse_rm_id else ""
            answer = f"Prodaja kave {label}{scope}:\n" + "\n".join(lines)
        else:
            answer = f"Nema prodaje kave {label}."
        return answer, [
            ToolResult(
                name="get_sales_by_product",
                arguments={
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                    "query": "kava (drink_category)",
                    "warehouse_rm_id": warehouse_rm_id,
                },
                result={"items": items, "date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            )
        ]

    def _drink_category_sales_response(category_label: str, category_ids: List[int], label: str, date_from: date, date_to: date):
        qs = SalesInvoiceItem.objects.select_related("invoice", "artikl").filter(
            invoice__issued_on__gte=date_from,
            invoice__issued_on__lte=date_to,
            artikl__drink_category_id__in=category_ids,
        )
        if warehouse_rm_id is not None:
            qs = qs.filter(invoice__warehouse_id=warehouse_rm_id)
        rows = (
            qs.values("artikl_id", "product_name", "artikl__name")
            .annotate(qty=Sum("quantity"), amount=Sum("amount"))
            .order_by("-amount")
        )
        items = [
            {
                "artikl_id": row["artikl_id"],
                "product_name": row.get("artikl__name") or row.get("product_name"),
                "qty": str(row["qty"] or 0),
                "amount": str(row["amount"] or 0),
            }
            for row in rows
        ]
        if items:
            lines = [
                f"{idx+1}. {item['product_name']} ({item['qty']} kom, {item['amount']} EUR)"
                for idx, item in enumerate(items)
            ]
            scope = f" za skladiste {warehouse_rm_id}" if warehouse_rm_id else ""
            answer = f"Prodaja {category_label} {label}{scope}:\n" + "\n".join(lines)
        else:
            answer = f"Nema prodaje {category_label} {label}."
        return answer, [
            ToolResult(
                name="get_sales_by_product",
                arguments={
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                    "query": f"{category_label} (drink_category)",
                    "warehouse_rm_id": warehouse_rm_id,
                },
                result={"items": items, "date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            )
        ]

    if time_filter and drink_category_match and ("kupljeno" in normalized_question or "primka" in normalized_question):
        supplier_match = re.search(r"kod\s+(.+)$", normalized_question, flags=re.IGNORECASE)
        supplier_query = None
        if supplier_match:
            supplier_query = supplier_match.group(1).strip()
            supplier_query = re.sub(
                r"(pro(s|š)li\s+mjesec|pro(s|š)li\s+tjedan|danas|ju(č|c)er|prekjucer|prekjučer|prije\s+\d+\s+dana|prije\s+[a-zčćžšđ]+\s+dana)$",
                "",
                supplier_query,
                flags=re.IGNORECASE,
            ).strip()
            supplier_query_norm = supplier_query.lower().strip()
            if supplier_query_norm in {"koktel", "koktela", "koktelu"}:
                supplier_query = "koktel"
        if supplier_query:
            inputs = WarehouseInput.objects.select_related("supplier").filter(
                supplier__name__icontains=supplier_query,
                date__gte=time_filter["start"],
                date__lte=time_filter["end"],
                is_canceled=False,
            )
            supplier_name = inputs.values_list("supplier__name", flat=True).first() or supplier_query
            items_qs = WarehouseInputItem.objects.select_related("warehouse_input", "artikl").filter(
                warehouse_input__in=inputs,
                artikl__drink_category_id__in=drink_category_match["ids"],
            )
            rows = (
                items_qs.values("artikl_id", "artikl__name")
                .annotate(qty=Sum("quantity"), amount=Sum("total"))
                .order_by("-amount")
            )
            items = [
                {
                    "artikl_id": row["artikl_id"],
                    "artikl_name": row["artikl__name"],
                    "qty": str(row["qty"] or 0),
                    "amount": str(row["amount"] or 0),
                }
                for row in rows
            ]
            if items:
                lines = [
                    f"{idx+1}. {item['artikl_name']} ({item['qty']} kom, {item['amount']} EUR)"
                    for idx, item in enumerate(items)
                ]
                answer = (
                    f"Kupljeno {drink_category_match['label']} kod {supplier_name} "
                    f"({time_filter['start'].isoformat()} do {time_filter['end'].isoformat()}):\n"
                    + "\n".join(lines)
                )
            else:
                answer = (
                    f"Nema kupljenog {drink_category_match['label']} kod {supplier_name} "
                    f"u razdoblju {time_filter['start'].isoformat()} do {time_filter['end'].isoformat()}."
                )
            return answer, []

    if drink_category_match and time_filter:
        return _drink_category_sales_response(
            drink_category_match["label"],
            drink_category_match["ids"],
            time_filter["label"],
            time_filter["start"],
            time_filter["end"],
        )

    if "kava" in normalized_question:
        if time_filter:
            return _coffee_sales_response(
                time_filter["label"], time_filter["start"], time_filter["end"]
            )

    if time_filter and ("prodaja" in normalized_question or "promet" in normalized_question):
        if not any(
            key in normalized_question
            for key in ("najbolje", "najprodavaniji", "prodavali", "top", "artikl", "artikli", "kava")
        ):
            summary = tool_get_sales_summary(
                date_from=time_filter["start"].isoformat(),
                date_to=time_filter["end"].isoformat(),
                warehouse_rm_id=warehouse_rm_id,
                waiter_user_id=waiter_user.id if waiter_user else None,
                waiter_name=waiter_name,
            )
            summary = _normalize(summary)
            count = summary.get("count", 0)
            net = summary.get("net", "0")
            vat = summary.get("vat", "0")
            total = summary.get("total", "0")
            label = time_filter["label"]
            if count:
                answer = (
                    f"Prodaja {label} ({time_filter['start'].isoformat()} do {time_filter['end'].isoformat()}) "
                    f"ima {count} racuna. Neto {net}, PDV {vat}, ukupno {total}."
                )
            else:
                answer = (
                    f"Prodaja {label} ({time_filter['start'].isoformat()} do {time_filter['end'].isoformat()}) "
                    f"je 0, bez racuna."
                )
            return answer, [
                ToolResult(
                    name="get_sales_summary",
                    arguments={
                        "date_from": time_filter["start"].isoformat(),
                        "date_to": time_filter["end"].isoformat(),
                        "warehouse_rm_id": warehouse_rm_id,
                    },
                    result=summary,
                )
            ]

    if time_filter and ("kupljeno" in normalized_question or "primka" in normalized_question):
        supplier_match = re.search(r"kod\s+(.+)$", normalized_question, flags=re.IGNORECASE)
        supplier_query = None
        if supplier_match:
            supplier_query = supplier_match.group(1).strip()
            supplier_query = re.sub(r"(pro(s|š)li\s+mjesec|pro(s|š)li\s+tjedan|danas|ju(č|c)er|prekjucer|prekjučer|prije\s+\d+\s+dana|prije\s+[a-zčćžšđ]+\s+dana)$", "", supplier_query, flags=re.IGNORECASE).strip()
            supplier_query_norm = supplier_query.lower().strip()
            if supplier_query_norm in {"koktel", "koktela", "koktelu"}:
                supplier_query = "koktel"
        if supplier_query:
            result = tool_get_supplier_inputs(
                supplier_query=supplier_query,
                date_from=time_filter["start"].isoformat(),
                date_to=time_filter["end"].isoformat(),
            )
            result = _normalize(result)
            inputs = result.get("inputs", [])
            items = result.get("items", [])
            total_sum = result.get("total")
            supplier_full_name = result.get("supplier_name") or supplier_query
            if items:
                item_lines = [
                    f"{idx+1}. {item.get('artikl_name')} ({item.get('qty')} kom, {item.get('amount')} EUR)"
                    for idx, item in enumerate(items)
                ]
                answer = (
                    f"Kupljeno kod {supplier_full_name} ({time_filter['start'].isoformat()} do {time_filter['end'].isoformat()}):\n"
                    + "\n".join(item_lines)
                )
                if inputs:
                    input_lines = [
                        f"- Primka {row.get('id')}: {row.get('date')} / {row.get('payment_type')} / {row.get('total')} EUR"
                        for row in inputs
                    ]
                    answer += "\n\nPrimke:\n" + "\n".join(input_lines)
                if total_sum is not None:
                    answer += f"\n\nUkupno: {total_sum} EUR"
            else:
                answer = f"Nema primki za {supplier_query} u razdoblju {time_filter['start'].isoformat()} do {time_filter['end'].isoformat()}."
            return answer, [
                ToolResult(
                    name="get_supplier_inputs",
                    arguments={
                        "supplier_query": supplier_query,
                        "date_from": time_filter["start"].isoformat(),
                        "date_to": time_filter["end"].isoformat(),
                    },
                    result=result,
                )
            ]

    if "jucer" in normalized_question or "jučer" in normalized_question:
        if "datum" in normalized_question:
            target = today - timedelta(days=1)
            return (
                f"Jucer je bio datum {target.isoformat()}.",
                [],
            )
        if normalized_question.strip() in {"jucer", "jučer", "pa jucer", "pa jučer"}:
            target = today - timedelta(days=1)
            summary = tool_get_sales_summary(
                date_from=target.isoformat(),
                date_to=target.isoformat(),
                warehouse_rm_id=warehouse_rm_id,
                waiter_user_id=waiter_user.id if waiter_user else None,
                waiter_name=waiter_name,
            )
            summary = _normalize(summary)
            count = summary.get("count", 0)
            net = summary.get("net", "0")
            vat = summary.get("vat", "0")
            total = summary.get("total", "0")
            if count:
                answer = (
                    f"Jucerasnja prodaja ({target.isoformat()}) ima {count} racuna. "
                    f"Neto {net}, PDV {vat}, ukupno {total}."
                )
            else:
                answer = f"Jucerasnja prodaja ({target.isoformat()}) je 0, bez racuna."
            return answer, [
                ToolResult(
                    name="get_sales_summary",
                    arguments={"date_from": target.isoformat(), "date_to": target.isoformat(), "warehouse_rm_id": warehouse_rm_id},
                    result=summary,
                )
            ]
        if (
            "najbolje" in normalized_question
            or "prodavali" in normalized_question
            or "artikl" in normalized_question
            or "artikli" in normalized_question
        ):
            target = today - timedelta(days=1)
            order_by = "amount" if "financijski" in normalized_question else "qty"
            top = tool_get_top_selling_items(
                date_from=target.isoformat(),
                date_to=target.isoformat(),
                warehouse_rm_id=warehouse_rm_id,
                waiter_user_id=waiter_user.id if waiter_user else None,
                waiter_name=waiter_name,
                limit=10,
                order_by=order_by,
            )
            top = _normalize(top)
            items = top.get("items", [])
            if items:
                lines = [
                    (
                        f"{idx+1}. {item.get('product_name')} ({item.get('amount')})"
                        if order_by == "amount"
                        else f"{idx+1}. {item.get('product_name')} ({item.get('qty')})"
                    )
                    for idx, item in enumerate(items)
                ]
                scope = f" za skladiste {warehouse_rm_id}" if warehouse_rm_id else ""
                label = "Najprodavaniji artikli (financijski)" if order_by == "amount" else "Najprodavaniji artikli"
                answer = (
                    f"{label} za {target.isoformat()}{scope}:\n"
                    + "\n".join(lines)
                )
            else:
                answer = f"Za {target.isoformat()} nema prodaje po stavkama."
            return answer, [
                ToolResult(
                    name="get_top_selling_items",
                    arguments={
                        "date_from": target.isoformat(),
                        "date_to": target.isoformat(),
                        "warehouse_rm_id": warehouse_rm_id,
                        "limit": 10,
                        "order_by": order_by,
                    },
                    result=top,
                )
            ]
        if "prodalo" in normalized_question:
            target = today - timedelta(days=1)
            query = normalized_question.replace("koliko se prodalo", "").replace("jucer", "").replace("jučer", "")
            query = query.replace("na", "").strip()
            if query:
                result = tool_get_sales_by_product(
                    date_from=target.isoformat(),
                    date_to=target.isoformat(),
                    query=query,
                    warehouse_rm_id=warehouse_rm_id,
                    waiter_user_id=waiter_user.id if waiter_user else None,
                    waiter_name=waiter_name,
                )
                result = _normalize(result)
                qty = result.get("qty", "0")
                amount = result.get("amount", "0")
                answer = f"Jucer ({target.isoformat()}) prodano: {qty} kom, iznos {amount}."
                return answer, [
                    ToolResult(
                        name="get_sales_by_product",
                        arguments={
                            "date_from": target.isoformat(),
                            "date_to": target.isoformat(),
                            "query": query,
                            "warehouse_rm_id": warehouse_rm_id,
                        },
                        result=result,
                    )
                ]
        if "prodaja" in normalized_question or "promet" in normalized_question:
            target = today - timedelta(days=1)
            summary = tool_get_sales_summary(
                date_from=target.isoformat(),
                date_to=target.isoformat(),
                warehouse_rm_id=warehouse_rm_id,
                waiter_user_id=waiter_user.id if waiter_user else None,
                waiter_name=waiter_name,
            )
            summary = _normalize(summary)
            count = summary.get("count", 0)
            net = summary.get("net", "0")
            vat = summary.get("vat", "0")
            total = summary.get("total", "0")
            if count:
                answer = (
                    f"Jucerasnja prodaja ({target.isoformat()}) ima {count} racuna. "
                    f"Neto {net}, PDV {vat}, ukupno {total}."
                )
            else:
                answer = f"Jucerasnja prodaja ({target.isoformat()}) je 0, bez racuna."
            return answer, [ToolResult(name="get_sales_summary", arguments={"date_from": target.isoformat(), "date_to": target.isoformat()}, result=summary)]
    if "danas" in normalized_question and ("prodaja" in normalized_question or "promet" in normalized_question):
        summary = tool_get_sales_summary(
            date_from=today.isoformat(),
            date_to=today.isoformat(),
            warehouse_rm_id=warehouse_rm_id,
            waiter_user_id=waiter_user.id if waiter_user else None,
            waiter_name=waiter_name,
        )
        summary = _normalize(summary)
        count = summary.get("count", 0)
        net = summary.get("net", "0")
        vat = summary.get("vat", "0")
        total = summary.get("total", "0")
        if count:
            answer = (
                f"Danasnja prodaja ({today.isoformat()}) ima {count} racuna. "
                f"Neto {net}, PDV {vat}, ukupno {total}."
            )
        else:
            answer = f"Danasnja prodaja ({today.isoformat()}) je 0, bez racuna."
        return answer, [ToolResult(name="get_sales_summary", arguments={"date_from": today.isoformat(), "date_to": today.isoformat()}, result=summary)]

    instructions = (
        "Ti si ERP asistent za restoran/kafic. "
        "Baza je read-only osim kreiranja narudzbi (PurchaseOrder/Item). "
        "Ako trebas podatke, koristi alate. "
        "Ne radi SQL, ne pisi u druge tablice. "
        "Odgovori kratko i jasno na hrvatskom."
    )
    input_items = [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": question}],
        }
    ]
    tools = _tool_definitions()
    tool_results: List[ToolResult] = []

    response = _call_openai(instructions, input_items, tools)
    tool_calls = [item for item in response.get("output", []) if item.get("type") == "function_call"]

    if tool_calls:
        output_items: List[Dict[str, Any]] = []
        for tool_call in tool_calls:
            name = tool_call["name"]
            args = json.loads(tool_call.get("arguments") or "{}")
            if name == "list_warehouses":
                result = tool_list_warehouses(**args)
            elif name == "list_suppliers":
                result = tool_list_suppliers(**args)
            elif name == "get_stock_balance":
                result = tool_get_stock_balance(**args)
            elif name == "get_sales_summary":
                result = tool_get_sales_summary(**args)
            elif name == "get_top_selling_items":
                result = tool_get_top_selling_items(**args)
            elif name == "get_sales_by_product":
                result = tool_get_sales_by_product(**args)
            elif name == "get_supplier_inputs":
                result = tool_get_supplier_inputs(**args)
            elif name == "create_purchase_order":
                result = tool_create_purchase_order(**args)
            else:
                result = {"error": "Nepoznat alat."}
            result = _normalize(result)
            tool_results.append(ToolResult(name=name, arguments=args, result=result))
            output_items.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_call["call_id"],
                    "output": _json_dumps(result),
                }
            )

        response = _call_openai(
            instructions,
            output_items,
            tools,
            previous_response_id=response.get("id"),
        )

    return _extract_output_text(response) or "", tool_results
