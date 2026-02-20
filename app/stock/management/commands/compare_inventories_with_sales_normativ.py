from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone as dt_timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import re

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from artikli.models import Artikl
from sales.models import SalesInvoice
from sales.services import build_stock_out_lines_for_invoice
from stock.models import Inventory, InventoryItem


FOURPLACES = Decimal("0.0001")
_RE_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_RE_PACKAGE = re.compile(
    r"^\s*(?P<base>.+?)\s+0[,\.]7\s*L\s*\+\s*4\s+(?P<mix>SOKA|RED\s*BULLA)\s*$",
    re.IGNORECASE,
)


def _q4(x: Decimal) -> Decimal:
    return (x or Decimal("0.0000")).quantize(FOURPLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class _InvRow:
    artikl_rm_id: int
    code: str
    name: str
    qty_bottles: Decimal  # as counted in inventory (often Komad, may be fractional)
    unit: str
    qty_in_suom: Decimal | None  # e.g. 0.7000 (liters per bottle)
    suom_name: str | None  # e.g. "Litra"

    def to_suom(self) -> tuple[Decimal, str]:
        """
        Return (quantity, unit_label) in "standard UoM".
        If quantity_in_suom is present, interpret qty_bottles as bottles and convert.
        Otherwise return qty_bottles as-is.
        """
        if self.qty_in_suom is not None and self.suom_name:
            return _q4(self.qty_bottles * self.qty_in_suom), self.suom_name
        return _q4(self.qty_bottles), (self.unit or "")


def _fmt(x: Decimal | None) -> str:
    if x is None:
        return "-"
    return str(_q4(Decimal(str(x))))

def _norm_key(s: str) -> str:
    # Uppercase, strip accents/punct by keeping only A-Z0-9.
    # Good enough for matching invoice product_name to inventory artikl names.
    s = (s or "").upper()
    s = s.replace("'", " ")
    return _RE_NON_ALNUM.sub(" ", s).strip()


def _best_match_package_base(
    base: str,
    inv_rows: dict[int, _InvRow],
    *,
    target_qty_in_suom: Decimal | None = None,
) -> _InvRow | None:
    """
    Map package base name (e.g. 'TITO'S VODKA') to an inventory artikl row.
    Strategy: word-overlap scoring against inventory artikl names.
    """
    base_k = _norm_key(base)
    if not base_k:
        return None
    base_words = [w for w in base_k.split() if w]
    if not base_words:
        return None

    best: tuple[int, Decimal, int, _InvRow] | None = None  # (overlap, suom_dist, name_len, row)
    for row in inv_rows.values():
        name_k = _norm_key(row.name)
        if not name_k:
            continue
        # Count how many base words exist in the inventory name.
        overlap = sum(1 for w in base_words if w in name_k)
        if overlap <= 0:
            continue
        suom_dist = Decimal("9999")
        if target_qty_in_suom is not None and row.qty_in_suom is not None:
            suom_dist = abs(row.qty_in_suom - target_qty_in_suom)
        cand = (overlap, suom_dist, len(name_k), row)
        if best is None:
            best = cand
            continue
        if cand[0] > best[0]:
            best = cand
            continue
        if cand[0] == best[0] and cand[1] < best[1]:
            best = cand
            continue
        if cand[0] == best[0] and cand[1] == best[1] and cand[2] > best[2]:
            best = cand

    return best[3] if best else None


class Command(BaseCommand):
    help = (
        "Compare two inventories by subtracting sales consumption in between, using Normativ to "
        "map sold products to ingredient consumption (optionally converted via ArtiklDetail.quantity_in_suom)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--inv-from", type=int, required=True, help="Source inventory id (start).")
        parser.add_argument("--inv-to", type=int, required=True, help="Target inventory id (end).")
        parser.add_argument(
            "--out",
            type=str,
            default="documents/stock/inv_compare_normativ.md",
            help="Output markdown file path.",
        )
        parser.add_argument(
            "--limit-invoices",
            type=int,
            default=None,
            help="Optional invoice limit for testing.",
        )
        parser.add_argument(
            "--sales-warehouse-rm-id",
            type=int,
            default=None,
            help="Optional filter: SalesInvoice.warehouse rm_id. If omitted, invoices are not filtered by warehouse.",
        )
        parser.add_argument(
            "--include-packages",
            action="store_true",
            help=(
                "Include heuristic mapping of invoice lines like 'X 0,7L + 4 SOKA' / '+ 4 RED BULLA' "
                "as bottle consumption (uses ArtiklDetail.quantity_in_suom). Default: off."
            ),
        )

    def handle(self, *args, **options):
        inv_from_id = int(options["inv_from"])
        inv_to_id = int(options["inv_to"])
        out_path = Path(str(options["out"]))
        limit_invoices = options.get("limit_invoices")
        sales_wh_rm_id = options.get("sales_warehouse_rm_id")
        include_packages = bool(options.get("include_packages"))

        inv_from = Inventory.objects.select_related("warehouse").filter(id=inv_from_id).first()
        inv_to = Inventory.objects.select_related("warehouse").filter(id=inv_to_id).first()
        if not inv_from or not inv_to:
            raise CommandError("Inventura nije pronađena (provjeri --inv-from/--inv-to).")
        if not inv_from.submitted_at or not inv_to.submitted_at:
            raise CommandError("Obje inventure moraju imati submitted_at.")
        if inv_from.warehouse_id != inv_to.warehouse_id:
            raise CommandError("Inventure nisu na istom skladištu.")

        wh_rm_id = inv_from.warehouse_id

        start_local = timezone.localtime(inv_from.submitted_at)
        end_local = timezone.localtime(inv_to.submitted_at)
        if start_local > end_local:
            start_local, end_local = end_local, start_local
            inv_from, inv_to = inv_to, inv_from
            inv_from_id, inv_to_id = inv_to_id, inv_from_id

        # Load inventory items and artikl details (to_field=rm_id on InventoryItem.artikl).
        artikl_ids = set(
            InventoryItem.objects.filter(inventory_id__in=[inv_from_id, inv_to_id])
            .values_list("artikl_id", flat=True)
        )
        artikl_map = {
            a.rm_id: a
            for a in Artikl.objects.select_related("detail", "detail__unit_of_measure").filter(rm_id__in=artikl_ids)
        }

        def load_inv(inv_id: int) -> dict[int, _InvRow]:
            m: dict[int, _InvRow] = {}
            for it in (
                InventoryItem.objects.select_related("unit")
                .filter(inventory_id=inv_id)
                .order_by("id")
            ):
                if not it.artikl_id:
                    continue
                a = artikl_map.get(it.artikl_id)
                code = getattr(a, "code", "") or ""
                name = getattr(a, "name", "") or ""
                detail = getattr(a, "detail", None) if a else None
                qty_in_suom = getattr(detail, "quantity_in_suom", None)
                suom_name = getattr(detail, "standard_uom_name", None) if detail else None
                qty = it.quantity if it.quantity is not None else Decimal("0.0000")
                unit = it.unit.name if it.unit else ""
                m[it.artikl_id] = _InvRow(
                    artikl_rm_id=it.artikl_id,
                    code=code,
                    name=name,
                    qty_bottles=Decimal(str(qty)),
                    unit=unit,
                    qty_in_suom=Decimal(str(qty_in_suom)) if qty_in_suom is not None else None,
                    suom_name=(suom_name or "").strip() or None,
                )
            return m

        inv_a = load_inv(inv_from_id)
        inv_b = load_inv(inv_to_id)
        inv_all = {**inv_a, **inv_b}  # for mapping package lines to artikli that exist in either inventory

        # Sales invoices in between.
        inv_qs = SalesInvoice.objects.filter(
            issued_at__gte=start_local.astimezone(dt_timezone.utc),
            issued_at__lte=end_local.astimezone(dt_timezone.utc),
        )
        if sales_wh_rm_id is not None:
            inv_qs = inv_qs.filter(warehouse_id=int(sales_wh_rm_id))
        inv_qs = inv_qs.prefetch_related("items", "items__artikl")

        if limit_invoices:
            inv_qs = inv_qs.order_by("id")[: int(limit_invoices)]

        consumption: dict[int, Decimal] = {}  # ingredient rm_id -> qty in "normativ base" (typically SUOM)
        invoice_count = 0
        skipped_msgs: list[str] = []
        mapped_pkg_msgs: list[str] = []

        # Iterate normally so prefetch_related is honored.
        for invoice in inv_qs:
            invoice_count += 1
            lines, skipped = build_stock_out_lines_for_invoice(invoice)
            skipped_msgs.extend(skipped)
            for ln in lines:
                ing = ln.get("artikl")
                qty = ln.get("quantity") or Decimal("0.0000")
                if not ing or not getattr(ing, "rm_id", None):
                    continue
                rm_id = ing.rm_id
                consumption[rm_id] = (consumption.get(rm_id) or Decimal("0.0000")) + Decimal(str(qty))

            if include_packages:
                # Heuristic: package lines without artikl, map to bottle artikl that exists in inventories.
                # We only count bottle consumption here (mixers are ignored unless they exist as inventory artikli).
                for it in getattr(invoice, "items", []).all():
                    if it.artikl_id:
                        continue
                    m = _RE_PACKAGE.match(it.product_name or "")
                    if not m:
                        continue
                    base = (m.group("base") or "").strip()
                    qty_bottles = Decimal(str(it.quantity or Decimal("0.0000")))
                    row = _best_match_package_base(base, inv_all, target_qty_in_suom=Decimal("0.7000"))
                    if not row:
                        skipped_msgs.append(f"Package '{it.product_name}' nije mapiran na artikl iz inventure.")
                        continue
                    # If we have quantity_in_suom we can consume qty_bottles * qty_in_suom; otherwise assume qty_bottles.
                    if row.qty_in_suom is not None and row.suom_name:
                        cons = _q4(qty_bottles * row.qty_in_suom)
                    else:
                        cons = _q4(qty_bottles)
                    consumption[row.artikl_rm_id] = (consumption.get(row.artikl_rm_id) or Decimal("0.0000")) + cons
                    mapped_pkg_msgs.append(
                        f"{it.product_name} -> {row.code or row.artikl_rm_id} ({row.name}) x {qty_bottles}"
                    )

        # Compare only artikli that exist in both inventories (intersection), like we did before.
        common_ids = sorted(set(inv_a.keys()) & set(inv_b.keys()))

        rows = []
        for rm_id in common_ids:
            a = inv_a[rm_id]
            b = inv_b[rm_id]
            start_qty_suom, unit_label = a.to_suom()
            end_qty_suom, _ = b.to_suom()
            sold_suom = _q4(consumption.get(rm_id, Decimal("0.0000")))
            expected_end = _q4(start_qty_suom - sold_suom)
            diff = _q4(end_qty_suom - expected_end)

            # Also show "bottles" diff if we can convert.
            diff_bottles = None
            if a.qty_in_suom is not None and a.qty_in_suom != 0:
                diff_bottles = _q4(diff / a.qty_in_suom)

            rows.append(
                {
                    "code": a.code,
                    "name": a.name,
                    "start_inv": start_qty_suom,
                    "sold": sold_suom,
                    "expected_end": expected_end,
                    "end_inv": end_qty_suom,
                    "diff": diff,
                    "unit": unit_label,
                    "diff_bottles": diff_bottles,
                }
            )

        rows.sort(key=lambda r: abs(r["diff"]), reverse=True)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            f.write("# Usporedba inventura uz normativ (sales -> sastojci)\n\n")
            f.write(f"- Inventory from: `{inv_from_id}` ({inv_from.warehouse.name if inv_from.warehouse else wh_rm_id})\n")
            f.write(f"- Inventory to: `{inv_to_id}` ({inv_to.warehouse.name if inv_to.warehouse else wh_rm_id})\n")
            f.write(f"- Warehouse rm_id: `{wh_rm_id}`\n")
            f.write(f"- Period local: `{start_local:%Y-%m-%d %H:%M}` -> `{end_local:%Y-%m-%d %H:%M}`\n")
            f.write(f"- SalesInvoice warehouse filter: `{sales_wh_rm_id if sales_wh_rm_id is not None else 'none'}`\n")
            f.write(f"- Include packages: `{include_packages}`\n")
            f.write(f"- Invoices in window: `{invoice_count}`\n")
            f.write(f"- Common artikli (both inventories): `{len(common_ids)}`\n\n")

            f.write("## Tablica (po artiklu)\n\n")
            f.write(
                "code | name | inv_from | sold(normativ) | expected_inv_to | inv_to | diff | unit | diff_as_bottles\n"
            )
            f.write("--- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---:\n")
            for r in rows:
                f.write(
                    f"{r['code']} | {r['name']} | {_fmt(r['start_inv'])} | {_fmt(r['sold'])} | "
                    f"{_fmt(r['expected_end'])} | {_fmt(r['end_inv'])} | {_fmt(r['diff'])} | "
                    f"{r['unit']} | {_fmt(r['diff_bottles'])}\n"
                )

            # Skipped summary (cap)
            if skipped_msgs:
                f.write("\n## Skipped (normativ)\n\n")
                uniq: dict[str, int] = {}
                for msg in skipped_msgs:
                    uniq[msg] = uniq.get(msg, 0) + 1
                for msg, cnt in sorted(uniq.items(), key=lambda x: x[1], reverse=True)[:30]:
                    f.write(f"- {cnt}x {msg}\n")

            if mapped_pkg_msgs:
                f.write("\n## Mapped Packages (heuristic)\n\n")
                for msg in mapped_pkg_msgs[:50]:
                    f.write(f"- {msg}\n")

        self.stdout.write(f"Wrote report: {out_path}")
