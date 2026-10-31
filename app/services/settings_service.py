"""Superadmin-configurable platform settings with enforced ranges.

Values live in the app_settings key/value table; missing keys fall back to the
registry default. Separation-of-duties, maker-checker rules, the superadmin-only
approval of admin password resets and the business timezone are deliberately
NOT configurable.
"""
import threading
import time
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings as env_settings
from app.models.models import AppSetting

CACHE_TTL_SECONDS = 60


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _entry(key, type_, default, label, description, category, public=False,
           min_=None, max_=None, unit=""):
    return {
        "key": key,
        "type": type_,
        "default": default,
        "min": min_,
        "max": max_,
        "unit": unit,
        "label": label,
        "description": description,
        "category": category,
        "public": public,
    }


_ENTRIES = [
    # Security
    _entry("password_reset_link_expiry_minutes", "int", 30, "Password reset link expiry",
           "How long an approved password reset link stays valid.", "Security",
           min_=15, max_=1440, unit="minutes"),
    _entry("session_timeout_minutes", "int",
           _clamp(int(env_settings.ACCESS_TOKEN_EXPIRE_MINUTES), 30, 720),
           "Session timeout", "Lifetime of a login session (JWT access token).", "Security",
           min_=30, max_=720, unit="minutes"),
    _entry("login_max_failed_attempts", "int", 10, "Max failed login attempts",
           "Failed attempts before a login is temporarily locked.", "Security",
           min_=3, max_=20, unit="attempts"),
    _entry("login_lockout_minutes", "int", 15, "Login lockout duration",
           "How long a locked login must wait.", "Security",
           min_=5, max_=120, unit="minutes"),
    _entry("min_reason_length", "int", 10, "Minimum reason length",
           "Minimum characters for reject / revert / reversal reasons.", "Security",
           min_=10, max_=200, unit="characters"),
    # Payments
    _entry("proof_max_upload_mb", "int", 5, "Max proof upload size",
           "Largest file accepted for payment proofs and uploads.", "Payments", public=True,
           min_=1, max_=10, unit="MB"),
    _entry("upcoming_months_payable", "int", 3, "Advance months payable",
           "How many future months a member may pay in advance.", "Payments", public=True,
           min_=0, max_=12, unit="months"),
    _entry("max_months_per_payment", "int", 12, "Max months per payment",
           "Most months that can be covered by one payment.", "Payments", public=True,
           min_=1, max_=24, unit="months"),
    _entry("default_campaign_min_amount", "int", 100, "Default campaign minimum",
           "Minimum donation applied to new campaigns when none is given.", "Payments",
           public=True, min_=1, max_=100000, unit="₹"),
    # Members & invites
    _entry("invite_default_expiry_days", "int", 7, "Invite default expiry",
           "Expiry used when an invite is created without an explicit date.",
           "Members & invites", min_=1, max_=90, unit="days"),
    # Reminders & messaging
    _entry("monthly_reminder_enabled", "bool", True, "Monthly reminders",
           "Send the monthly membership reminders.", "Reminders & messaging"),
    _entry("monthly_reminder_day", "int", 1, "Reminder day of month",
           "Day of the month (IST) on which reminders are sent.", "Reminders & messaging",
           min_=1, max_=28, unit="day"),
    _entry("whatsapp_payment_receipts", "bool", False, "WhatsApp payment receipts",
           "Send a WhatsApp receipt when a payment is approved.", "Reminders & messaging"),
    # Visibility
    _entry("member_stats_visible", "bool", False, "Member stats visible",
           "Show member statistics to members.", "Visibility", public=True),
]

SETTINGS_REGISTRY: dict[str, dict] = {e["key"]: e for e in _ENTRIES}

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _spec(key: str) -> dict:
    spec = SETTINGS_REGISTRY.get(key)
    if spec is None:
        raise KeyError(f"Unknown setting: {key}")
    return spec


def _parse(spec: dict, raw: str) -> Any:
    if spec["type"] == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    return int(str(raw).strip())


def _serialize(spec: dict, value: Any) -> str:
    if spec["type"] == "bool":
        return "1" if value else "0"
    return str(int(value))


def invalidate_cache(key: Optional[str] = None) -> None:
    with _cache_lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)


def get_setting(db: Session, key: str) -> Any:
    """Return the typed value for a setting (cached for 60 s)."""
    spec = _spec(key)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]

    value = spec["default"]
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is not None and row.value not in (None, ""):
        try:
            value = _parse(spec, row.value)
        except (TypeError, ValueError):
            value = spec["default"]

    with _cache_lock:
        _cache[key] = (now, value)
    return value


def validate_value(key: str, value: Any) -> Any:
    """Validate type and range; returns the normalised value or raises 400."""
    spec = _spec(key)
    if spec["type"] == "bool":
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail=f"{spec['label']} must be true or false")
        return value

    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise HTTPException(
            status_code=400,
            detail=f"{spec['label']} must be a whole number between {spec['min']} and {spec['max']} {spec['unit']}".strip(),
        )
    number = int(value)
    if number < spec["min"] or number > spec["max"]:
        raise HTTPException(
            status_code=400,
            detail=f"{spec['label']} must be between {spec['min']} and {spec['max']} {spec['unit']}".strip(),
        )
    return number


def _row_meta(db: Session, key: str):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row


def serialize_setting(db: Session, key: str, updated_by_names: Optional[dict] = None) -> dict:
    spec = _spec(key)
    row = _row_meta(db, key)
    updated_by = None
    if row is not None and row.updated_by_user_id is not None and updated_by_names is not None:
        updated_by = updated_by_names.get(row.updated_by_user_id)
    return {
        **spec,
        "value": get_setting(db, key),
        "updated_at": row.updated_at if row is not None else None,
        "updated_by": updated_by,
    }


def update_settings(db: Session, changes: dict, actor_user_id: Optional[int]) -> dict:
    """All-or-nothing update. Returns {key: (old, new)} for changed keys."""
    unknown = [k for k in changes if k not in SETTINGS_REGISTRY]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown setting(s): {', '.join(sorted(unknown))}")

    validated = {key: validate_value(key, value) for key, value in changes.items()}

    diff: dict[str, tuple[Any, Any]] = {}
    for key, new_value in validated.items():
        old_value = get_setting(db, key)
        _store(db, key, new_value, actor_user_id)
        diff[key] = (old_value, new_value)
    db.commit()
    for key in validated:
        invalidate_cache(key)
    return diff


def reset_setting(db: Session, key: str, actor_user_id: Optional[int]) -> tuple[Any, Any]:
    spec = _spec(key)
    old_value = get_setting(db, key)
    _store(db, key, spec["default"], actor_user_id)
    db.commit()
    invalidate_cache(key)
    return old_value, spec["default"]


def _store(db: Session, key: str, value: Any, actor_user_id: Optional[int]) -> None:
    spec = _spec(key)
    raw = _serialize(spec, value)
    row = _row_meta(db, key)
    if row is None:
        db.add(AppSetting(key=key, value=raw, updated_by_user_id=actor_user_id))
    else:
        row.value = raw
        row.updated_by_user_id = actor_user_id


def public_settings(db: Session) -> dict:
    return {key: get_setting(db, key) for key, spec in SETTINGS_REGISTRY.items() if spec["public"]}
