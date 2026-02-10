import json
import os
import re
from urllib.parse import quote
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils import timezone

from artikli.models import Artikl, ArtiklDetail, Normativ, DrinkCategory
from sales.models import SalesPriceItem
from orders.models import SupplierPriceItem
from django.contrib.auth import get_user_model
from contacts.models import Supplier
from orders.models import PurchaseOrder, PurchaseOrderItem
from sales.models import SalesInvoice, SalesInvoiceItem
from orders.models import WarehouseInput, WarehouseInputItem
from sales.models import Representation, RepresentationItem, RepresentationReason
from stock.models import WarehouseId, WarehouseStock, StockLot


@dataclass
class ToolResult:
    name: str
    arguments: Dict[str, Any]
    result: Any

    def __post_init__(self) -> None:
        # Tool results are persisted into JSONField and returned via DRF JSON rendering.
        # Ensure we don't leak non-JSON types (datetime/Decimal/etc).
        self.result = _normalize(self.result)


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
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(val) for key, val in value.items()}
    return value

def _json_dumps(value: Any) -> str:
    return json.dumps(_normalize(value), ensure_ascii=False)


def _strip_json_object(text: str) -> Optional[str]:
    """
    Best-effort extractor for a single JSON object from model output.
    Handles accidental code fences / extra text.
    """
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        return match.group(0)
    return None


def _extract_time_filter_ai(question: str, today: date) -> Optional[Dict[str, Any]]:
    """
    Paid fallback: ask OpenAI to extract date range from the user's text.
    Only used when local heuristics fail.
    """
    if os.getenv("AI_TIME_FILTER_FALLBACK", "1").strip() in {"0", "false", "False"}:
        return None
    tz_name = str(timezone.get_current_timezone())
    dow = ["pon", "uto", "sri", "cet", "pet", "sub", "ned"][today.weekday()]
    instructions = (
        "Iz teksta korisnika izvuci vremenski filter kao datum/e.\n"
        f"Danas je {today.isoformat()} ({dow}) u vremenskoj zoni {tz_name}.\n"
        "Vrati ISKLJUCIVO jedan JSON objekt bez dodatnog teksta.\n"
        "Schema:\n"
        "{\n"
        '  "label": string|null,\n'
        '  "date_from": "YYYY-MM-DD"|null,\n'
        '  "date_to": "YYYY-MM-DD"|null\n'
        "}\n"
        "Pravila:\n"
        "- Ako nema vremenskog izraza, sva polja nek budu null.\n"
        '- Ako je jedan dan ("prosla subota", "jucer"), date_from=date_to.\n'
        "- date_from mora biti <= date_to.\n"
    )
    input_items = [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": question or ""}],
        }
    ]
    try:
        resp = _call_openai(instructions=instructions, input_items=input_items, tools=[])
    except Exception:
        return None

    raw = _extract_output_text(resp) or ""
    json_text = _strip_json_object(raw)
    if not json_text:
        return None
    try:
        obj = json.loads(json_text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None

    date_from_raw = obj.get("date_from")
    date_to_raw = obj.get("date_to")
    label = obj.get("label")
    if not date_from_raw and not date_to_raw:
        return None
    try:
        date_from = _parse_date(date_from_raw)
        date_to = _parse_date(date_to_raw)
    except Exception:
        return None
    if not date_from or not date_to:
        return None
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    # Basic sanity guard: avoid far-future / far-past hallucinations.
    if date_from > today + timedelta(days=1):
        return None
    if date_from < today - timedelta(days=366 * 3):
        return None

    return {
        "label": (str(label).strip() if isinstance(label, str) and label.strip() else "ai"),
        "start": date_from,
        "end": date_to,
    }


def _drink_category_outflow_response(
    *,
    date_from: date,
    date_to: date,
    category_label: str,
    category_ids: List[int],
    label: str,
    warehouse_rm_id: Optional[int],
) -> Tuple[str, List[ToolResult]]:
    """
    "Izlaz" = prodaja (SalesInvoice/SalesInvoiceItem) + reprezentacija
    (Representation/RepresentationItem + RepresentationReason) za zadanu drink kategoriju.
    """
    max_detail_rows = int(os.getenv("AI_MAX_DETAIL_ROWS", "500"))
    max_text_rows = int(os.getenv("AI_MAX_TEXT_ROWS", "120"))
    include_details = os.getenv("AI_INCLUDE_OUTFLOW_DETAILS", "0").strip() in {"1", "true", "True"}

    # 1) Prodaja (racuni)
    sales_qs = SalesInvoiceItem.objects.select_related("invoice", "artikl").filter(
        invoice__issued_on__gte=date_from,
        invoice__issued_on__lte=date_to,
        artikl__drink_category_id__in=category_ids,
    )
    if warehouse_rm_id is not None:
        sales_qs = sales_qs.filter(invoice__warehouse_id=warehouse_rm_id)
    sales_agg = sales_qs.aggregate(
        qty=Sum("quantity"),
        amount=Sum("amount"),
        invoice_count=Count("invoice_id", distinct=True),
        item_count=Count("id"),
    )
    sales_rows = (
        sales_qs.values("artikl_id", "product_name", "artikl__name")
        .annotate(qty=Sum("quantity"), amount=Sum("amount"))
        .order_by("-amount")[:max_detail_rows]
    )
    sales_items = [
        {
            "artikl_id": row["artikl_id"],
            "product_name": row.get("artikl__name") or row.get("product_name"),
            "qty": str(row["qty"] or 0),
            "amount": str(row["amount"] or 0),
        }
        for row in sales_rows
    ]

    # 2) Reprezentacija
    reps_qs = Representation.objects.select_related("warehouse", "user", "reason").filter(
        occurred_at__date__gte=date_from,
        occurred_at__date__lte=date_to,
    )
    if warehouse_rm_id is not None:
        reps_qs = reps_qs.filter(warehouse_id=warehouse_rm_id)
    rep_items_qs = RepresentationItem.objects.select_related(
        "representation",
        "representation__warehouse",
        "representation__user",
        "representation__reason",
        "artikl",
    ).filter(
        representation__in=reps_qs,
        artikl__drink_category_id__in=category_ids,
    )
    rep_amount_expr = ExpressionWrapper(
        F("quantity") * F("price"),
        output_field=DecimalField(max_digits=18, decimal_places=6),
    )
    rep_agg = rep_items_qs.aggregate(
        qty=Sum("quantity"),
        amount=Sum(rep_amount_expr),
        representation_count=Count("representation_id", distinct=True),
        item_count=Count("id"),
    )
    rep_rows = (
        rep_items_qs.values("artikl_id", "artikl__name")
        .annotate(qty=Sum("quantity"), amount=Sum(rep_amount_expr))
        .order_by("-amount")[:max_detail_rows]
    )
    rep_items_summary = [
        {
            "artikl_id": row["artikl_id"],
            "artikl_name": row["artikl__name"],
            "qty": str(row["qty"] or 0),
            "amount": str(row["amount"] or 0),
        }
        for row in rep_rows
    ]

    # 3) Kumulativno po artiklu (prodaja + reprezentacija)
    combined: Dict[int, Dict[str, Any]] = {}
    for item in sales_items:
        artikl_id = int(item["artikl_id"])
        row = combined.setdefault(
            artikl_id,
            {
                "artikl_id": artikl_id,
                "name": item.get("product_name") or "",
                "sales_qty": Decimal("0"),
                "rep_qty": Decimal("0"),
                "sales_amount": Decimal("0"),
                "rep_amount": Decimal("0"),
            },
        )
        if not row["name"]:
            row["name"] = item.get("product_name") or ""
        try:
            row["sales_qty"] += Decimal(str(item.get("qty") or "0"))
        except Exception:
            pass
        try:
            row["sales_amount"] += Decimal(str(item.get("amount") or "0"))
        except Exception:
            pass

    for item in rep_items_summary:
        artikl_id = int(item["artikl_id"])
        row = combined.setdefault(
            artikl_id,
            {
                "artikl_id": artikl_id,
                "name": item.get("artikl_name") or "",
                "sales_qty": Decimal("0"),
                "rep_qty": Decimal("0"),
                "sales_amount": Decimal("0"),
                "rep_amount": Decimal("0"),
            },
        )
        if not row["name"]:
            row["name"] = item.get("artikl_name") or ""
        try:
            row["rep_qty"] += Decimal(str(item.get("qty") or "0"))
        except Exception:
            pass
        try:
            row["rep_amount"] += Decimal(str(item.get("amount") or "0"))
        except Exception:
            pass

    combined_rows = []
    for row in combined.values():
        total_qty = row["sales_qty"] + row["rep_qty"]
        total_amount = row["sales_amount"] + row["rep_amount"]
        combined_rows.append(
            {
                "artikl_id": row["artikl_id"],
                "name": row["name"],
                "sales_qty": str(row["sales_qty"]),
                "rep_qty": str(row["rep_qty"]),
                "total_qty": str(total_qty),
                "sales_amount": str(row["sales_amount"]),
                "rep_amount": str(row["rep_amount"]),
                "total_amount": str(total_amount),
            }
        )
    combined_rows.sort(key=lambda r: Decimal(str(r.get("total_qty") or "0")), reverse=True)

    # "Navedi sva polja" (za relevantne zapise u tom periodu/kategoriji)
    rep_ids = list(
        rep_items_qs.values_list("representation_id", flat=True).distinct()[:max_detail_rows]
    )
    reps_full = list(
        Representation.objects.select_related("warehouse", "user", "reason")
        .filter(id__in=rep_ids)
        .values(
            "id",
            "occurred_at",
            "warehouse_id",
            "user_id",
            "reason_id",
            "note",
        )[:max_detail_rows]
    )
    reason_ids = sorted({row["reason_id"] for row in reps_full if row.get("reason_id")})
    reasons_full = list(
        RepresentationReason.objects.filter(id__in=reason_ids).values(
            "id",
            "code",
            "name",
            "is_active",
            "sort_order",
        )[:max_detail_rows]
    )
    reason_name_by_id = {row["id"]: row.get("name") for row in reasons_full if row.get("id")}
    rep_items_full = list(
        rep_items_qs.values(
            "id",
            "representation_id",
            "artikl_id",
            "quantity",
            "price",
            "transfer_posted_at",
        )[:max_detail_rows]
    )
    rep_notes = [
        {
            "id": row.get("id"),
            "occurred_at": row.get("occurred_at"),
            "warehouse_id": row.get("warehouse_id"),
            "user_id": row.get("user_id"),
            "reason_id": row.get("reason_id"),
            "reason_name": reason_name_by_id.get(row.get("reason_id")),
            "note": (row.get("note") or "").strip(),
        }
        for row in reps_full
        if (row.get("note") or "").strip()
    ]

    scope = f" za skladiste {warehouse_rm_id}" if warehouse_rm_id else ""
    date_label = f"{label} ({date_from.isoformat()}" + (
        f" do {date_to.isoformat()})" if date_to != date_from else ")"
    )

    sales_qty = str(sales_agg.get("qty") or 0)
    sales_amount = str(sales_agg.get("amount") or 0)
    sales_invoice_count = sales_agg.get("invoice_count") or 0

    rep_qty = str(rep_agg.get("qty") or 0)
    rep_amount = str(rep_agg.get("amount") or 0)
    rep_count = rep_agg.get("representation_count") or 0

    parts: List[str] = []
    parts.append(f"Izlaz {category_label} {date_label}{scope}:")
    parts.append("")
    parts.append(
        f"1) Prodaja (racuni): {sales_qty} kom, {sales_amount} EUR, {sales_invoice_count} racuna."
    )
    parts.append("")
    parts.append(
        f"Kumulativno artikli (prodaja + reprezentacija), sortirano po kolicini (max {max_text_rows} redova):"
    )
    if combined_rows:
        shown = combined_rows[:max_text_rows]
        parts.extend(
            [
                (
                    f"{idx+1}. {row['name']} "
                    f"(prodaja {row['sales_qty']}, repr {row['rep_qty']}, ukupno {row['total_qty']})"
                )
                for idx, row in enumerate(shown)
            ]
        )
        if len(combined_rows) > len(shown):
            parts.append(f"... ({len(combined_rows) - len(shown)} jos, skraceno)")
    else:
        parts.append("Nema stavki u tom periodu.")

    parts.append("")
    parts.append(f"2) Reprezentacija: {rep_qty} kom, {rep_amount} EUR, {rep_count} reprezentacija.")
    if rep_items_summary:
        parts.append("Reprezentacija po artiklu (top):")
        parts.extend(
            [
                f"{idx+1}. {item['artikl_name']} ({item['qty']} kom, {item['amount']} EUR)"
                for idx, item in enumerate(rep_items_summary[:min(30, max_text_rows)])
            ]
        )
    else:
        parts.append("Reprezentacija: nema stavki.")

    parts.append("")
    parts.append("Napomene reprezentacije:")
    if rep_notes:
        parts.extend(
            [
                (
                    f"{idx+1}. [{n.get('occurred_at')}] rep_id {n.get('id')}, "
                    f"reason {n.get('reason_name') or n.get('reason_id')}, "
                    f"user {n.get('user_id')}: {re.sub(r'\s+', ' ', n.get('note') or '').strip()}"
                )
                for idx, n in enumerate(rep_notes[:max_text_rows])
            ]
        )
        if len(rep_notes) > max_text_rows:
            parts.append(f"... ({len(rep_notes) - max_text_rows} jos, skraceno)")
    else:
        parts.append("Nema napomena.")

    if include_details:
        parts.append("")
        parts.append("Detalji (sva polja):")
        # For sales we output aggregated per artikl rows (not the entire invoice/items tables).
        parts.append(_json_dumps({"sales_salesinvoiceitem_agg": sales_items}))
        parts.append(_json_dumps({"combined_agg": combined_rows}))
        parts.append(_json_dumps({"sales_representation": reps_full}))
        parts.append(_json_dumps({"sales_representationreason": reasons_full}))
        parts.append(_json_dumps({"sales_representationitem": rep_items_full}))

    answer = "\n".join(parts).strip()
    rep_tool_payload: Dict[str, Any] = {
        "summary": _normalize(rep_agg),
        "items": rep_items_summary,
        "notes": rep_notes,
    }
    if include_details:
        rep_tool_payload.update(
            {
                "representation": reps_full,
                "representationreason": reasons_full,
                "representationitem": rep_items_full,
            }
        )
    return answer, [
        ToolResult(
            name="get_sales_by_product",
            arguments={
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "query": f"{category_label} (drink_category)",
                "warehouse_rm_id": warehouse_rm_id,
            },
            result={"summary": _normalize(sales_agg), "items": sales_items},
        ),
        ToolResult(
            name="get_representation_report",
            arguments={
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "query": f"{category_label} (drink_category)",
                "warehouse_rm_id": warehouse_rm_id,
            },
            result=rep_tool_payload,
        ),
    ]


def _format_representation_item(idx: int, item: Dict[str, Any]) -> str:
    artikl = item.get("artikl")
    qty = item.get("quantity")
    breakdown = item.get("normativ_breakdown") or []
    if breakdown:
        normativ_cost = item.get("normativ_cost")
        if len(breakdown) == 1:
            part = breakdown[0]
            per_unit = part.get("unit_cost_total")
            total = normativ_cost
            try:
                per_unit_dec = Decimal(str(per_unit)).quantize(Decimal("0.01"))
            except Exception:
                per_unit_dec = per_unit
            try:
                qty_dec = Decimal(str(qty)).quantize(Decimal("0.01"))
            except Exception:
                qty_dec = qty
            try:
                total_dec = Decimal(str(total)).quantize(Decimal("0.001"))
            except Exception:
                total_dec = total
            return (
                f"{idx+1}. {artikl} x {qty_dec} x {per_unit_dec} Ukupno {total_dec} EUR"
            )
        return (
            f"{idx+1}. {artikl} x {qty} Ukupno {normativ_cost} EUR"
        )
    return (
        f"{idx+1}. {artikl} x {qty} "
        f"(cijena {item.get('price')}, iznos {item.get('amount')})"
    )


def _extract_time_filter(normalized_question: str, today: date):
    q = (normalized_question or "").lower()
    q_ascii = (
        q.replace("č", "c")
        .replace("ć", "c")
        .replace("ž", "z")
        .replace("š", "s")
        .replace("đ", "dj")
    )
    q_ascii = q_ascii.replace("porsli", "prosli").replace("por sli", "prosli")
    if "danas" in q_ascii:
        return {"label": "danas", "start": today, "end": today}
    if "jucer" in q_ascii:
        target = today - timedelta(days=1)
        return {"label": "jucer", "start": target, "end": target}
    if "prekjucer" in q_ascii:
        target = today - timedelta(days=2)
        return {"label": "prekjucer", "start": target, "end": target}
    # "proslu subotu" => uvijek prosla (ne danasnja) subota.
    if re.search(r"\bprosl[aieuo]\s+subot", q_ascii):
        # Python: Monday=0 .. Sunday=6, Saturday=5
        delta = (today.weekday() - 5) % 7
        if delta == 0:
            delta = 7
        target = today - timedelta(days=delta)
        return {"label": "prosla subota", "start": target, "end": target}
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
            target = None
            for anc in cat.get_ancestors(include_self=True):
                anc_ascii = (
                    (anc.name or "")
                    .lower()
                    .replace("č", "c")
                    .replace("ć", "c")
                    .replace("ž", "z")
                    .replace("š", "s")
                    .replace("đ", "dj")
                )
                if anc_ascii and anc_ascii in q_ascii:
                    target = anc
            if target is None:
                target = cat
            ids = list(target.get_descendants(include_self=True).values_list("id", flat=True))
            return {"label": target.name, "ids": ids}
    synonym_groups = [
        ("pivo", ["pivo", "piva", "pive"]),
        ("vino", ["vino", "vina"]),
        ("sok", ["sok", "sokovi"]),
        ("voda", ["voda", "vode"]),
        ("rakija", ["rakija", "rakije"]),
        ("kava", ["kava", "kave"]),
        ("pelinkovac", ["pelinkovac", "pelinkovca", "pelinkovcu"]),
    ]
    for canonical, tokens in synonym_groups:
        if any(token in q_ascii for token in tokens):
            qs = DrinkCategory.objects.filter(is_active=True, name__icontains=canonical)
            matches = list(qs)
            if matches:
                min_level = min(cat.level for cat in matches)
                top_matches = [cat for cat in matches if cat.level == min_level]
                ids: List[int] = []
                for cat in top_matches:
                    ids.extend(
                        list(cat.get_descendants(include_self=True).values_list("id", flat=True))
                    )
                label = top_matches[0].name if len(top_matches) == 1 else canonical
                return {"label": label, "ids": list(sorted(set(ids)))}
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


def tool_get_representation_report(date_from: str, date_to: str):
    start = _parse_date(date_from)
    end = _parse_date(date_to)
    if not start or not end:
        return {"error": "date_from i date_to su obavezni."}
    reps = (
        Representation.objects.select_related("reason", "warehouse")
        .prefetch_related("items__artikl__normativ__items__ingredient")
        .filter(occurred_at__date__gte=start, occurred_at__date__lte=end)
        .order_by("occurred_at")
    )
    rows = []
    total_amount = Decimal("0")
    total_cost = Decimal("0")
    reason_totals: Dict[str, Dict[str, Any]] = {}
    for rep in reps:
        for item in rep.items.all():
            amount = (item.price or Decimal("0")) * (item.quantity or Decimal("0"))
            total_amount += amount
            normativ_cost = None
            normativ_breakdown: List[Dict[str, Any]] = []
            if getattr(item.artikl, "normativ", None):
                normativ = item.artikl.normativ
                if normativ and normativ.is_active:
                    cost_sum = Decimal("0")
                    has_cost = False
                    for nitem in normativ.items.all():
                        lot = (
                            StockLot.objects.filter(
                                warehouse_id=rep.warehouse_id,
                                artikl_id=nitem.ingredient.rm_id,
                                qty_remaining__gt=0,
                            )
                            .order_by("-received_at")
                            .first()
                        )
                        if lot and lot.unit_cost is not None:
                            has_cost = True
                            ingredient_qty = nitem.qty or Decimal("0")
                            unit_cost = lot.unit_cost
                            cost_sum += ingredient_qty * unit_cost
                            normativ_breakdown.append(
                                {
                                    "ingredient": nitem.ingredient.name,
                                    "ingredient_qty": str(ingredient_qty),
                                    "unit_cost": str(unit_cost),
                                    "unit_cost_total": str(ingredient_qty * unit_cost),
                                }
                            )
                    if has_cost:
                        normativ_cost = cost_sum * (item.quantity or Decimal("0"))
                        total_cost += normativ_cost
            if normativ_cost is None:
                lot = (
                    StockLot.objects.filter(
                        warehouse_id=rep.warehouse_id,
                        artikl_id=item.artikl.rm_id,
                        qty_remaining__gt=0,
                    )
                    .order_by("-received_at")
                    .first()
                )
                if lot and lot.unit_cost is not None:
                    per_unit = lot.unit_cost
                    normativ_cost = per_unit * (item.quantity or Decimal("0"))
                    total_cost += normativ_cost
                    normativ_breakdown.append(
                        {
                            "ingredient": item.artikl.name if item.artikl else None,
                            "ingredient_qty": "1",
                            "unit_cost": str(per_unit),
                            "unit_cost_total": str(per_unit),
                        }
                    )
            rows.append(
                {
                    "representation_id": rep.id,
                    "occurred_at": rep.occurred_at.isoformat(),
                    "reason": rep.reason.name if rep.reason else None,
                    "artikl": item.artikl.name if item.artikl else None,
                    "quantity": str(item.quantity),
                    "price": str(item.price),
                    "amount": str(amount),
                    "normativ_cost": str(normativ_cost) if normativ_cost is not None else None,
                    "normativ_breakdown": normativ_breakdown,
                }
            )
            reason_label = rep.reason.name if rep.reason else "Nepoznato"
            reason_entry = reason_totals.setdefault(
                reason_label, {"amount": Decimal("0"), "normativ_cost": Decimal("0"), "items": []}
            )
            reason_entry["amount"] += amount
            if normativ_cost is not None:
                reason_entry["normativ_cost"] += normativ_cost
            reason_entry["items"].append(
                {
                    "artikl": item.artikl.name if item.artikl else None,
                    "quantity": str(item.quantity),
                    "price": str(item.price),
                    "amount": str(amount),
                    "normativ_cost": str(normativ_cost) if normativ_cost is not None else None,
                    "normativ_breakdown": normativ_breakdown,
                }
            )
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "count": len(rows),
        "total_amount": str(total_amount),
        "total_normativ_cost": str(total_cost),
        "items": rows,
        "reasons": {
            key: {
                "amount": str(val["amount"]),
                "normativ_cost": str(val["normativ_cost"]),
                "items": val["items"],
            }
            for key, val in reason_totals.items()
        },
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
            "name": "get_representation_report",
            "description": "Reprezentacija po razdoblju.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                },
                "required": ["date_from", "date_to"],
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
) -> Dict[str, Any]:
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
    try:
        resp = requests.post(
            f"{conf['base_url'].rstrip('/')}/responses",
            headers=headers,
            json=payload,
            timeout=conf["timeout"],
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenAI network error: {exc}") from exc
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


def handle_ai_query(question: str) -> Tuple[str, List[ToolResult]]:
    normalized_question = (question or "").lower()
    normalized_question_ascii = (
        normalized_question.replace("č", "c")
        .replace("ć", "c")
        .replace("ž", "z")
        .replace("š", "s")
        .replace("đ", "dj")
    )
    today = timezone.localdate()
    time_filter = _extract_time_filter(normalized_question, today)
    if not time_filter:
        time_filter = _extract_time_filter_ai(question, today)
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
            category_match = _match_drink_category(query)
            if category_match:
                matches = list(
                    Artikl.objects.filter(
                        drink_category_id__in=category_match["ids"]
                    ).order_by("name")[:50]
                )
            else:
                matches = list(
                    Artikl.objects.filter(name__icontains=query).order_by("name")[:50]
                )
            if not matches:
                return f"Nema artikala za upit: {query}.", []
            lines = [
                (
                    f"- [{a.name}](fill:{a.name}) "
                    f"(id {a.id}, rm_id {a.rm_id}, sifra {a.code}) "
                    f"admin: /admin/artikli/artikl/{a.id}/change/ "
                    f"detalji: /ai?q={quote(a.name)}"
                )
                for a in matches
            ]
            return "Artikli:\n" + "\n".join(lines), []

    artikl_list_query = _extract_artikl_list_query(question)
    if artikl_list_query:
        category_match = _match_drink_category(artikl_list_query)
        if category_match:
            matches = list(
                Artikl.objects.filter(
                    drink_category_id__in=category_match["ids"]
                ).order_by("name")[:50]
            )
        else:
            matches = list(
                Artikl.objects.filter(name__icontains=artikl_list_query).order_by("name")[:50]
            )
        if not matches:
            return f"Nema artikala za upit: {artikl_list_query}.", []
        lines = [
            (
                f"- [{a.name}](fill:{a.name}) "
                f"(id {a.id}, rm_id {a.rm_id}, sifra {a.code}) "
                f"admin: /admin/artikli/artikl/{a.id}/change/ "
                f"detalji: /ai?q={quote(a.name)}"
            )
            for a in matches
        ]
        return "Artikli:\n" + "\n".join(lines), []

    if "skladist" in normalized_question_ascii:
        query = _extract_artikl_query(question)
        cleaned = re.sub(
            r"\\b(stanje|na|u|skladištu|skladistu|skladište|skladiste|skladistu)\\b",
            "",
            query,
            flags=re.IGNORECASE,
        ).strip()
        if cleaned:
            query = cleaned
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
        if artikl:
            result = tool_get_stock_balance(query=str(artikl.id), warehouse_rm_id=warehouse_rm_id)
            result = _normalize(result)
            rows = result.get("rows", [])
            if rows:
                parts = [
                    f"- skladiste {row.get('warehouse_id')}: {row.get('internal_quantity')} {row.get('unit') or ''}".strip()
                    for row in rows
                ]
                return (
                    f"Stanje za {result.get('name')}:\n" + "\n".join(parts),
                    [ToolResult(name="get_stock_balance", arguments={"query": str(artikl.id), "warehouse_rm_id": warehouse_rm_id}, result=result)],
                )
            return f"Nema stanja za {result.get('name')}.", [
                ToolResult(name="get_stock_balance", arguments={"query": str(artikl.id), "warehouse_rm_id": warehouse_rm_id}, result=result),
            ]

    # Must run before the generic "list artikli by category" fallback.
    if (
        time_filter
        and drink_category_match
        and any(
            token in normalized_question_ascii
            for token in (
                "izaslo",
                "izislo",
                "izaso",
                "izasla",
                "izlaz",
                "izaslo je",
                "izislo je",
            )
        )
    ):
        return _drink_category_outflow_response(
            date_from=time_filter["start"],
            date_to=time_filter["end"],
            category_label=drink_category_match["label"],
            category_ids=drink_category_match["ids"],
            label=time_filter["label"],
            warehouse_rm_id=warehouse_rm_id,
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
            exact = Artikl.objects.filter(name__iexact=query).first()
            if exact:
                return _build_artikl_info(exact, warehouse_rm_id=warehouse_rm_id), []
            category_match = _match_drink_category(query)
            if category_match:
                matches = list(
                    Artikl.objects.filter(
                        drink_category_id__in=category_match["ids"]
                    ).order_by("name")[:50]
                )
                if matches:
                    lines = [
                        f"- {a.name} (id {a.id}, rm_id {a.rm_id})"
                        for a in matches
                    ]
                    return "Artikli:\n" + "\n".join(lines), []
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

    if time_filter and (
        "kupljeno" in normalized_question
        or "kupili" in normalized_question
        or "kupnja" in normalized_question
        or "kupnje" in normalized_question
        or "kupio" in normalized_question
        or "kupila" in normalized_question
        or "primka" in normalized_question
    ):
        supplier_match = re.search(r"kod\s+(.+)$", normalized_question, flags=re.IGNORECASE)
        supplier_query = None
        if supplier_match:
            supplier_query = supplier_match.group(1).strip()
            supplier_query = re.sub(r"(por(s|š)li\s+mjesec|pro(s|š)li\s+mjesec|por(s|š)li\s+tjedan|pro(s|š)li\s+tjedan|danas|ju(č|c)er|prekjucer|prekjučer|prije\s+\d+\s+dana|prije\s+[a-zčćžšđ]+\s+dana)$", "", supplier_query, flags=re.IGNORECASE).strip()
            supplier_query_norm = supplier_query.lower().strip()
            if supplier_query_norm in {"koktel", "koktela", "koktelu"}:
                supplier_query = "koktel"
            if supplier_query_norm in {"fructus", "fructusa", "fructusu", "ftuktus", "fruktusu", "fruktusa"}:
                supplier_query = "fructus"
            if supplier_query_norm in {"julius", "juliusa", "juliusu"}:
                supplier_query = "Junus Meinl Bonfenti d.o.o."
        if not supplier_query:
            supplier_names = list(Supplier.objects.values_list("name", flat=True))
            for name in supplier_names:
                if not name:
                    continue
                if name.lower() in normalized_question:
                    supplier_query = name
                    break
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

    if time_filter and "reprezentacij" in normalized_question:
        result = tool_get_representation_report(
            date_from=time_filter["start"].isoformat(),
            date_to=time_filter["end"].isoformat(),
        )
        result = _normalize(result)
        items = result.get("items", [])
        reasons = result.get("reasons", {})
        if reasons:
            groups = []
            for reason, payload in reasons.items():
                lines = [
                    _format_representation_item(idx, item)
                    for idx, item in enumerate(payload.get("items", []))
                ]
                group = (
                    f"Razlog: {reason}\n"
                    + "\n".join(lines)
                    + f"\nUkupno {reason}: {Decimal(str(payload.get('normativ_cost') or payload.get('amount'))).quantize(Decimal('0.01'))} EUR"
                )
                groups.append(group)
            answer = (
                f"Reprezentacija {time_filter['label']} ({time_filter['start'].isoformat()} do {time_filter['end'].isoformat()}):\n"
                + "\n\n".join(groups)
            )
        elif items:
            lines = [
                (
                    f"{idx+1}. {item.get('artikl')} x {item.get('quantity')} "
                    f"(cijena {item.get('price')}, iznos {item.get('amount')})"
                    + (f", normativ {item.get('normativ_cost')}" if item.get("normativ_cost") else "")
                    + (f", razlog {item.get('reason')}" if item.get("reason") else "")
                )
                for idx, item in enumerate(items)
            ]
            answer = (
                f"Reprezentacija {time_filter['label']} ({time_filter['start'].isoformat()} do {time_filter['end'].isoformat()}):\n"
                + "\n".join(lines)
            )
            if result.get("total_amount") is not None:
                answer += f"\n\nUkupno iznos: {result.get('total_amount')} EUR"
            if result.get("total_normativ_cost") is not None:
                answer += f"\nUkupno normativ: {result.get('total_normativ_cost')} EUR"
        else:
            answer = (
                f"Nema reprezentacije u razdoblju {time_filter['start'].isoformat()} do {time_filter['end'].isoformat()}."
            )
        return answer, [
            ToolResult(
                name="get_representation_report",
                arguments={
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
    tool_dispatch = {
        "list_warehouses": tool_list_warehouses,
        "list_suppliers": tool_list_suppliers,
        "get_stock_balance": tool_get_stock_balance,
        "get_sales_summary": tool_get_sales_summary,
        "get_top_selling_items": tool_get_top_selling_items,
        "get_sales_by_product": tool_get_sales_by_product,
        "get_supplier_inputs": tool_get_supplier_inputs,
        "get_representation_report": tool_get_representation_report,
        "create_purchase_order": tool_create_purchase_order,
    }

    max_tool_rounds = int(os.getenv("OPENAI_MAX_TOOL_ROUNDS", "4"))
    for _round in range(max_tool_rounds):
        tool_calls = [
            item for item in response.get("output", []) if item.get("type") == "function_call"
        ]
        if not tool_calls:
            break

        output_items: List[Dict[str, Any]] = []
        for tool_call in tool_calls:
            name = tool_call.get("name") or ""
            call_id = tool_call.get("call_id")
            raw_args = tool_call.get("arguments") or "{}"

            if not call_id:
                tool_results.append(
                    ToolResult(
                        name=name or "unknown_tool",
                        arguments={"raw_arguments": raw_args},
                        result={"error": "Nedostaje call_id."},
                    )
                )
                continue

            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                if not isinstance(args, dict):
                    args = {"_raw": args}
            except Exception as exc:
                args = {}
                result = {"error": "Neispravni tool arguments JSON.", "details": str(exc), "raw_arguments": raw_args}
                result = _normalize(result)
                tool_results.append(ToolResult(name=name or "unknown_tool", arguments={}, result=result))
                output_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": _json_dumps(result),
                    }
                )
                continue

            fn = tool_dispatch.get(name)
            if not fn:
                result = {"error": "Nepoznat alat.", "name": name}
            else:
                try:
                    result = fn(**args)
                except Exception as exc:
                    result = {"error": "Greska pri izvrsavanju alata.", "name": name, "details": str(exc)}

            result = _normalize(result)
            tool_results.append(ToolResult(name=name, arguments=args, result=result))
            output_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": _json_dumps(result),
                }
            )

        prev_id = response.get("id")
        next_input_items = output_items if prev_id else (input_items + output_items)
        response = _call_openai(
            instructions,
            next_input_items,
            tools,
            previous_response_id=prev_id,
        )
    else:
        raise RuntimeError("Prekidanjem: previse uzastopnih tool roundova.")

    return _extract_output_text(response) or "", tool_results
