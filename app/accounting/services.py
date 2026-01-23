from accounting.models import Ledger


def get_single_ledger() -> Ledger:
    ledger = Ledger.objects.first()
    if not ledger:
        raise RuntimeError("Ne postoji Ledger u bazi. Kreiraj ga prvo.")
    return ledger
