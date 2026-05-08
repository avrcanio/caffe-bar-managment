"""
Storno skladišnog povrata vezanog uz primku, brisanje zapisa SupplierReturn i
čišćenje FK-ova na primci — nakon toga možeš ponovo pokrenuti admin akciju
„Kreiraj povrat dobavljaču”.

Primjer (samo pregled, bez promjena):
  python manage.py reset_supplier_return_from_primka --ids 222,223

Izvršenje:
  python manage.py reset_supplier_return_from_primka --ids 222,223 --apply \\
      --user admin

Napomena: stvara storno skladišnog OUT kretanja (FIFO ulaz natrag). Ako postoji
financijsko terećenje povrata (proknjižena temeljnica), poziva se storno te
temeljnice. Obavezno provjeri rezultat u adminu prije ponovnog povrata.
"""

from __future__ import annotations

from argparse import ArgumentTypeError

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounting.models import JournalEntry
from orders.models import WarehouseInput
from stock.models import StockMove, SupplierReturn, SupplierReturnItem
from stock.services import reverse_stock_move


def _parse_ids(s: str) -> list[int]:
    out: list[int] = []
    for part in s.replace(" ", "").split(","):
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError as exc:
            raise ArgumentTypeError(f"Neispravan ID '{part}'.") from exc
    return out


class Command(BaseCommand):
    help = (
        "Storno skladišnog povrata primke, obriši SupplierReturn i očisti primku "
        "(da se može ponovo kreirati povrat iz admina)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--ids",
            type=str,
            required=True,
            help="Zarezom odvojeni ID-evi primki (WarehouseInput), npr. 222,223.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Bez ovoga se samo ispisuje što bi se napravilo.",
        )
        parser.add_argument(
            "--user",
            type=str,
            default="",
            help="Korisnik za storno temeljnice (username). Zadano: prvi superuser.",
        )

    def handle(self, *args, **options):
        ids = _parse_ids(options["ids"])
        if not ids:
            raise CommandError("Navedi barem jedan --ids.")

        apply = options["apply"]
        username = (options["user"] or "").strip()
        User = get_user_model()
        if username:
            user = User.objects.filter(username=username).first()
            if not user:
                raise CommandError(f"Korisnik '{username}' ne postoji.")
        else:
            user = User.objects.filter(is_superuser=True).order_by("id").first()
            if not user:
                raise CommandError("Nema superusera; navedi --user.")

        for wid in ids:
            self._process_one(wid=wid, apply=apply, user=user)

    def _process_one(self, *, wid: int, apply: bool, user):
        wi = WarehouseInput.objects.filter(pk=wid).select_related(
            "supplier_return_stock_move",
            "supplier_return_journal_entry",
        ).first()
        if not wi:
            self.stdout.write(self.style.WARNING(f"Primka {wid}: ne postoji."))
            return

        move_id = wi.supplier_return_stock_move_id
        sr_qs = SupplierReturn.objects.filter(source_warehouse_input_id=wid)
        je = wi.supplier_return_journal_entry

        self.stdout.write(f"Primka {wid}:")
        self.stdout.write(f"  supplier_return_stock_move_id: {move_id or '—'}")
        self.stdout.write(f"  SupplierReturn (izvor primka): {list(sr_qs.values_list('id', flat=True))}")
        self.stdout.write(
            f"  supplier_return_journal_entry: {je.id if je else '—'} "
            f"({je.status if je else ''})"
        )

        if not move_id and not sr_qs.exists():
            self.stdout.write(self.style.WARNING("  Nema vezanog povrata; ništa za reset."))
            return

        if not apply:
            self.stdout.write(self.style.NOTICE("  (dry-run; dodaj --apply za izvršenje)"))
            return

        with transaction.atomic():
            wi_locked = WarehouseInput.objects.select_for_update().get(pk=wid)

            sr_list = list(
                SupplierReturn.objects.select_for_update()
                .filter(source_warehouse_input_id=wid)
                .order_by("id")
            )
            for sr in sr_list:
                srid = sr.id
                SupplierReturnItem.objects.filter(supplier_return=sr).delete()
                sr.delete()
                self.stdout.write(self.style.SUCCESS(f"  Obrisan SupplierReturn #{srid}."))

            move_id = wi_locked.supplier_return_stock_move_id
            if move_id:
                move = StockMove.objects.select_for_update().get(pk=move_id)
                if move.reversed_move_id:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  StockMove #{move.id} već ima storno (reversed_move); "
                            "preskačem storno zalihe."
                        )
                    )
                elif move.move_type != StockMove.MoveType.OUT:
                    raise CommandError(
                        f"Primka {wid}: očekuje se OUT za povrat, tip={move.move_type}."
                    )
                else:
                    rev = reverse_stock_move(
                        move=move,
                        reference=f"Storno povrata primke #{wid}",
                        note=f"reset_supplier_return_from_primka primka {wid}",
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Stornirano skladišno kretanje OUT #{move.id} → IN #{rev.id}."
                        )
                    )

            je = wi_locked.supplier_return_journal_entry
            if je:
                if je.status == JournalEntry.Status.POSTED:
                    rev_je = je.reverse(user=user)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Storno financijskog terećenja: temeljnica #{rev_je.number} (id {rev_je.id})."
                        )
                    )
                elif je.status == JournalEntry.Status.DRAFT:
                    je.void()
                    self.stdout.write(self.style.SUCCESS(f"  Poništena draft temeljnica #{je.id}."))
                else:
                    self.stdout.write(
                        self.style.WARNING(f"  Temeljnica #{je.id} status={je.status}; nije dirano.")
                    )

            wi_locked.supplier_return_stock_move = None
            wi_locked.supplier_return_journal_entry = None
            wi_locked.save(
                update_fields=["supplier_return_stock_move", "supplier_return_journal_entry"]
            )
            self.stdout.write(self.style.SUCCESS(f"  Primka {wid}: očišćeni FK-ovi povrata."))
