"""
Tablica po artiklima: zbroj primki (WarehouseInputItem), prodaja (FIFO stock-out
preko normativa kao u build_stock_out_lines_for_invoice) i inventura.

Primjer:
  python manage.py artikl_primka_prodaja_inventura --inventory-id 39
  python manage.py artikl_primka_prodaja_inventura --inventory-id 39 \\
      --from-date 2026-04-01 --to-date 2026-05-08 --out /tmp/promet.csv
"""

from __future__ import annotations

import csv
import sys
from argparse import ArgumentTypeError
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from artikli.models import Artikl
from orders.models import WarehouseInputItem
from sales.models import SalesInvoice
from sales.services import build_stock_out_lines_for_invoice
from stock.models import Inventory, InventoryItem, WarehouseId


def _parse_date(s: str) -> date:
    try:
        y, m, d = (int(p) for p in s.split("-", 2))
        return date(y, m, d)
    except Exception as exc:
        raise ArgumentTypeError(f"Ocekujem YYYY-MM-DD, dobio '{s}'.") from exc


class Command(BaseCommand):
    help = (
        "Izvadi tablicu (CSV): artikl | zbroj primki | prodaja (normativ) | inventura, "
        "za artikle s odabrane inventure."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--inventory-id",
            type=int,
            required=True,
            help="ID inventure (artikli i zadano skladište uzimaju se iz nje).",
        )
        parser.add_argument(
            "--from-date",
            type=_parse_date,
            default=None,
            help="Početak razdoblja (YYYY-MM-DD) za primke i prodaju. Zadano: ~30 dana prije datuma inventure.",
        )
        parser.add_argument(
            "--to-date",
            type=_parse_date,
            default=None,
            help="Kraj razdoblja (YYYY-MM-DD) uključivo. Zadano: datum inventure (lokalni).",
        )
        parser.add_argument(
            "--warehouse-rm-id",
            type=int,
            default=None,
            help="Filtar skladišta (WarehouseId.rm_id) za primke i račune. Zadano: skladište inventure.",
        )
        parser.add_argument(
            "--include-unposted-primka",
            action="store_true",
            help="Uključi i stavke primki koje još nemaju proknjiženo skladišno kretanje.",
        )
        parser.add_argument(
            "--out",
            type=str,
            default="",
            help="Putanja CSV datoteke. Prazno = ispis na stdout.",
        )
        parser.add_argument(
            "--delimiter",
            type=str,
            default=";",
            help="CSV delimiter (default: ; za Excel HR).",
        )

    def handle(self, *args, **options):
        inv_id = int(options["inventory_id"])
        inv = Inventory.objects.select_related("warehouse").filter(pk=inv_id).first()
        if not inv:
            raise CommandError(f"Inventura id={inv_id} ne postoji.")

        inv_local_date = timezone.localtime(inv.date).date()
        from_date = options["from_date"] or (inv_local_date - timedelta(days=30))
        to_date = options["to_date"] or inv_local_date
        if from_date > to_date:
            raise CommandError("--from-date mora biti prije ili jednak --to-date.")

        wh_rm = options["warehouse_rm_id"]
        if wh_rm is None:
            wh_rm = inv.warehouse_id
        wh_pk: int | None = None
        if wh_rm is not None:
            wh = WarehouseId.objects.filter(rm_id=int(wh_rm)).values_list("id", flat=True).first()
            if not wh:
                raise CommandError(f"Skladište rm_id={wh_rm} ne postoji.")
            wh_pk = int(wh)

        rm_ids = list(
            InventoryItem.objects.filter(inventory_id=inv_id)
            .exclude(artikl_id__isnull=True)
            .values_list("artikl_id", flat=True)
        )
        if not rm_ids:
            raise CommandError("Inventura nema stavaka s artiklom.")

        rm_id_set = sorted(set(rm_ids))
        artikl_by_rm = {
            a.rm_id: a
            for a in Artikl.objects.filter(rm_id__in=rm_id_set).only("id", "rm_id", "code", "name")
        }

        inv_qty: dict[int, Decimal] = defaultdict(lambda: Decimal("0.0000"))
        inv_has_null: set[int] = set()
        for it in InventoryItem.objects.filter(inventory_id=inv_id).exclude(artikl_id__isnull=True):
            rid = it.artikl_id
            if it.quantity is None:
                inv_has_null.add(rid)
            else:
                inv_qty[rid] += Decimal(str(it.quantity))

        prim_totals: dict[int, Decimal] = defaultdict(lambda: Decimal("0.0000"))
        prim_lines: dict[int, int] = defaultdict(int)

        wi_qs = WarehouseInputItem.objects.filter(
            warehouse_input__date__gte=from_date,
            warehouse_input__date__lte=to_date,
            warehouse_input__is_canceled=False,
            artikl__rm_id__in=rm_id_set,
        ).select_related("warehouse_input", "artikl")
        if wh_pk is not None:
            wi_qs = wi_qs.filter(warehouse_input__warehouse_id=wh_pk)
        if not options["include_unposted_primka"]:
            wi_qs = wi_qs.filter(warehouse_input__stock_move__isnull=False)

        for row in wi_qs:
            rid = row.artikl.rm_id
            prim_totals[rid] += Decimal(str(row.quantity or 0))
            prim_lines[rid] += 1

        sale_totals: dict[int, Decimal] = defaultdict(lambda: Decimal("0.0000"))
        inv_qs = SalesInvoice.objects.filter(
            issued_on__gte=from_date,
            issued_on__lte=to_date,
        )
        if wh_pk is not None:
            inv_qs = inv_qs.filter(warehouse_id=wh_pk)
        inv_qs = inv_qs.prefetch_related("items", "items__artikl").order_by("id")

        for invoice in inv_qs:
            lines, _skipped = build_stock_out_lines_for_invoice(invoice)
            for ln in lines:
                a = ln.get("artikl")
                qty = ln.get("quantity") or Decimal("0.0000")
                if not a or a.rm_id not in rm_id_set:
                    continue
                sale_totals[a.rm_id] += Decimal(str(qty))

        delim = str(options["delimiter"] or ";")
        buf = StringIO()
        w = csv.writer(buf, delimiter=delim)
        w.writerow(
            [
                "rm_id",
                "code",
                "name",
                "primka_kolicina",
                "primka_broj_stavki",
                "prodaja_kolicina_normativ",
                "inventura_kolicina",
            ]
        )

        for rm in rm_id_set:
            a = artikl_by_rm.get(rm)
            code = (a.code or "") if a else ""
            name = (a.name or "") if a else ""
            if rm in inv_has_null:
                inv_cell = ""
            else:
                inv_cell = str(inv_qty[rm])
            w.writerow(
                [
                    rm,
                    code,
                    name,
                    str(prim_totals[rm]),
                    prim_lines[rm],
                    str(sale_totals[rm]),
                    inv_cell,
                ]
            )

        body = buf.getvalue()
        meta = (
            f"inventura_id={inv_id}; warehouse_rm_id={wh_rm}; "
            f"from={from_date}; to={to_date}; posted_primka_only={not options['include_unposted_primka']}\n"
        )
        out_path = (options.get("out") or "").strip()
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(meta + body, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Zapisano: {out_path}"))
        else:
            sys.stderr.write(meta)
            self.stdout.write(body)
