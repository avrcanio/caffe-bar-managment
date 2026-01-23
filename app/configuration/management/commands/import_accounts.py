import re
import xml.etree.ElementTree as ET
from pathlib import Path

from django.core.management.base import BaseCommand

from configuration.models import Account


class Command(BaseCommand):
    help = "Import konta iz RRIF XML dokumenta."

    def add_arguments(self, parser):
        parser.add_argument(
            "--xml",
            default="RRIF-RP2025.xml",
            help="Putanja do RRIF XML datoteke (default: RRIF-RP2025.xml)",
        )
        parser.add_argument(
            "--ledger-id",
            type=int,
            default=None,
            help="Opcionalni ledger_id za import u accounting app (ako je zadan, puni accounting.Account).",
        )

    def handle(self, *args, **options):
        xml_path = Path(options["xml"]).resolve()
        if not xml_path.exists():
            self.stderr.write(f"Datoteka ne postoji: {xml_path}")
            return

        tree = ET.parse(xml_path)
        root = tree.getroot()

        entries = []
        for tr in root.findall(".//Table//TBody//TR"):
            th = tr.find("./TH//P")
            td = tr.find("./TD//P")
            if th is None or td is None:
                continue
            code = (th.text or "").strip()
            name = (td.text or "").strip()
            if not code or not name:
                continue
            # prihvati konta s brojčanim kodom
            if not re.fullmatch(r"\d+", code):
                continue
            entries.append((code, name))

        ledger_id = options.get("ledger_id")
        if ledger_id:
            from accounting.models import Account as AccountingAccount, Ledger

            ledger = Ledger.objects.filter(id=ledger_id).first()
            if not ledger:
                self.stderr.write(f"Ledger ne postoji: {ledger_id}")
                return

            created = 0
            updated = 0
            for code, name in entries:
                safe_name = " ".join(name.split())
                if len(safe_name) > 255:
                    safe_name = safe_name[:255].rstrip()
                _, was_created = AccountingAccount.objects.update_or_create(
                    ledger=ledger,
                    code=code,
                    defaults={"name": safe_name},
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

            self.stdout.write(
                f"Accounting import završen. created={created} updated={updated} total={len(entries)}"
            )
            return

        created = 0
        updated = 0
        for code, name in entries:
            safe_name = " ".join(name.split())
            if len(safe_name) > 255:
                safe_name = safe_name[:255].rstrip()
            _, was_created = Account.objects.update_or_create(
                code=code,
                defaults={"name": safe_name, "is_active": True},
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(f"Import završen. created={created} updated={updated} total={len(entries)}")
