import os

from django.utils import timezone


def pin_verify_ttl_seconds() -> int:
    raw = os.getenv("POS_PIN_VERIFY_TTL_SECONDS", "180")
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        ttl = 180
    return max(0, min(ttl, 900))


def pin_verify_required_for_sensitive_actions() -> bool:
    return os.getenv("POS_REQUIRE_PIN_VERIFY_SENSITIVE", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def mark_pin_verified(profile) -> None:
    profile.pin_verified_at = timezone.now()
    profile.save(update_fields=["pin_verified_at"])


def is_recent_pin_verified(user) -> tuple[bool, int]:
    if not pin_verify_required_for_sensitive_actions():
        return True, 0

    profile = getattr(user, "pos_profile", None)
    if not profile or not profile.pin_hash or not profile.pin_verified_at:
        return False, pin_verify_ttl_seconds()

    ttl = pin_verify_ttl_seconds()
    if ttl <= 0:
        return False, 0

    age = (timezone.now() - profile.pin_verified_at).total_seconds()
    if age <= ttl:
        return True, max(0, int(ttl - age))
    return False, 0
