from __future__ import annotations

import re

from artikli.models import Artikl

_NON_ALNUM = re.compile(r"[^a-z0-9.]+")


def normalize_product_name(name: str) -> str:
    """Normalize Remaris/Mozart product labels for fuzzy name matching."""
    s = (name or "").strip().lower()
    s = s.replace(",", ".")
    s = _NON_ALNUM.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_artikl_lookup() -> dict[str, int]:
    lookup: dict[str, int] = {}
    for artikl_id, artikl_name in Artikl.objects.values_list("id", "name"):
        key = normalize_product_name(artikl_name)
        if key and key not in lookup:
            lookup[key] = artikl_id
    return lookup


def resolve_artikl_id(
    product_name: str,
    *,
    lookup: dict[str, int] | None = None,
) -> int | None:
    if not product_name:
        return None
    if lookup is None:
        lookup = build_artikl_lookup()
    return lookup.get(normalize_product_name(product_name))
