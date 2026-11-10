"""Superadmin-configurable platform settings with enforced ranges.

Values live in the app_settings key/value table; missing keys fall back to the
registry default. Separation-of-duties, maker-checker rules, the superadmin-only
approval of admin password resets and the business timezone are deliberately
NOT configurable.
"""
import re
import threading
import time
from datetime import date
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings as env_settings
from app.models.models import AppSetting
from app.utils.timezone import today_business

CACHE_TTL_SECONDS = 60

THEME_PRESETS = ["default", "ramadan", "eid", "independence_day", "campaign_drive"]
ANNOUNCEMENT_STYLES = ["info", "success", "warning", "festive"]
DEFAULT_ORG_NAME = "PMB GCC PORTAL"
DEFAULT_INVITE_TEMPLATE = (
    "You've been invited to join {org_name}!\n\n"
    "Use this invite code to register:\n{invite_code}\n\n"
    "Open your registration link:\n{registration_url}\n\n{expiry_note}"
)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _entry(key, type_, default, label, description, category, public=False,
           min_=None, max_=None, unit="", choices=None, max_len=None,
           multiline=False, placeholders=None, fmt=None, required=False, branding=False):
    return {
        "choices": choices,
        "max_len": max_len,
        "multiline": multiline,
        "placeholders": placeholders,
        "fmt": fmt,
        "required": required,
        "branding": branding,
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
    _entry("remember_me_days", "int", 30, "Remember me duration",
           "How long a login with \"Remember me\" ticked stays signed in on that device. "
           "Such sessions end early if the account is deactivated or its password changes.",
           "Security", public=True, min_=1, max_=90, unit="days"),
    _entry("self_activation_enabled", "bool", True, "Member self-activation",
           "Existing members can activate their own account with their Member ID "
           "from the login page; an admin approves each request.", "Security"),
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
    _entry("monthly_reminder_day", "int", 1, "Default reminder day",
           "Day of the month (IST) for members who have not picked their own reminder day. "
           "Members can choose any day from 1 to 28; unpaid members get one follow-up 7 days later.",
           "Reminders & messaging",
           min_=1, max_=28, unit="day"),
    _entry("whatsapp_payment_receipts", "bool", False, "WhatsApp payment receipts",
           "Send a WhatsApp receipt when a payment is approved.", "Reminders & messaging"),
    # Visibility
    _entry("member_stats_visible", "bool", False, "Member stats visible",
           "Show member statistics to members.", "Visibility", public=True),
    # Part E: theme & season (dates are entered by the superadmin; moon-sighting dates are never computed)
    _entry("active_theme", "enum", "default", "Active theme",
           "Theme shown to everyone (or the scheduled theme, when scheduling is on).",
           "Theme & season", choices=THEME_PRESETS),
    _entry("theme_schedule_enabled", "bool", False, "Schedule theme",
           "Use the theme only between the start and end dates (IST, inclusive); default theme otherwise.",
           "Theme & season"),
    _entry("theme_start_date", "date", "", "Theme start date", "First day (IST) the theme is shown.",
           "Theme & season"),
    _entry("theme_end_date", "date", "", "Theme end date", "Last day (IST) the theme is shown.",
           "Theme & season"),
    # Announcement banner
    _entry("announcement_enabled", "bool", False, "Show announcement",
           "Show the banner at the top of every page.", "Announcement"),
    _entry("announcement_text", "string", "", "Announcement text", "Plain text, up to 200 characters.",
           "Announcement", max_len=200),
    _entry("announcement_style", "enum", "info", "Announcement style", "Banner colour.",
           "Announcement", choices=ANNOUNCEMENT_STYLES),
    _entry("announcement_link_url", "url", "", "Announcement link", "Optional https link.", "Announcement"),
    _entry("announcement_start_date", "date", "", "Announcement start date (IST)", "Optional.", "Announcement"),
    _entry("announcement_end_date", "date", "", "Announcement end date (IST)", "Optional.", "Announcement"),
    _entry("announcement_dismissible", "bool", True, "Members can dismiss",
           "Let members hide the banner for themselves.", "Announcement"),
    # Organisation & payment details
    _entry("org_display_name", "string", DEFAULT_ORG_NAME, "Organisation name",
           "Shown in the header, login page, reports and messages.",
           "Organisation & payment details", public=True, branding=True, max_len=80, required=True),
    _entry("org_tagline", "string", "", "Tagline", "Short line under the name.",
           "Organisation & payment details", public=True, branding=True, max_len=120),
    _entry("org_logo_url", "image", "", "Logo", "Image upload, up to 1 MB.",
           "Organisation & payment details", public=True, branding=True),
    _entry("support_whatsapp_number", "string", "", "Support WhatsApp number",
           "Digits with optional country code.", "Organisation & payment details",
           public=True, max_len=20, fmt="phone"),
    _entry("support_email", "string", "", "Support email", "", "Organisation & payment details",
           public=True, max_len=120, fmt="email"),
    _entry("payment_upi_id", "string", "", "UPI ID", "", "Organisation & payment details",
           public=True, max_len=80),
    _entry("payment_upi_qr_image_url", "image", "", "UPI QR image", "Image upload, up to 1 MB.",
           "Organisation & payment details", public=True),
    _entry("payment_bank_name", "string", "", "Bank name", "", "Organisation & payment details",
           public=True, max_len=80),
    _entry("payment_account_name", "string", "", "Account name", "", "Organisation & payment details",
           public=True, max_len=80),
    _entry("payment_account_number_masked_display", "string", "", "Account number (masked)",
           "Type it as it should appear, e.g. XXXX XXXX 4417.", "Organisation & payment details",
           public=True, max_len=40),
    _entry("payment_ifsc_or_iban", "string", "", "IFSC / IBAN", "", "Organisation & payment details",
           public=True, max_len=40),
    _entry("payment_instructions_text", "string", "", "Payment instructions",
           "Plain text with line breaks, up to 500 characters.", "Organisation & payment details",
           public=True, max_len=500, multiline=True),
    # Message wording (in-app notifications and share links only)
    _entry("msg_monthly_reminder", "template",
           "Your monthly membership contribution for {month} is due. Amount: {amount}.",
           "Monthly reminder message", "In-app reminder text.", "Messages", max_len=500,
           multiline=True, placeholders=["member_name", "month", "amount", "org_name"]),
    _entry("msg_monthly_reminder_followup", "template",
           "A gentle reminder: your monthly contribution for {month} ({amount}) is still due. "
           "Please ignore this if you have already paid.",
           "Follow-up reminder message", "Sent 7 days after the first reminder if still unpaid.", "Messages",
           max_len=500, multiline=True, placeholders=["member_name", "month", "amount", "org_name"]),
    _entry("msg_payment_approved", "template", "Your {payment} has been approved.",
           "Payment approved message", "In-app notification text.", "Messages", max_len=500,
           multiline=True, placeholders=["member_name", "month", "amount", "payment", "org_name"]),
    _entry("msg_payment_rejected", "template",
           "Your {payment} was rejected. Reason: {reason}. "
           "Please re-upload your payment proof from the Challans page.",
           "Payment rejected message", "In-app notification text.", "Messages", max_len=500,
           multiline=True, placeholders=["member_name", "month", "amount", "payment", "reason", "org_name"]),
    _entry("msg_welcome", "template",
           "Your account is ready. Complete your profile and begin your charity journey.",
           "Welcome message", "Sent after registration.", "Messages", max_len=500,
           multiline=True, placeholders=["member_name", "org_name"]),
    _entry("msg_invite_share", "template", DEFAULT_INVITE_TEMPLATE,
           "Invite share message", "Text shared with an invite link.", "Messages", max_len=500,
           multiline=True, placeholders=["org_name", "invite_code", "registration_url", "expiry_note"]),
    # Landing / login
    _entry("landing_headline", "string", "", "Landing headline", "Up to 80 characters.",
           "Landing & login", public=True, branding=True, max_len=80),
    _entry("landing_subtext", "string", "", "Landing sub-text", "Up to 200 characters.",
           "Landing & login", public=True, branding=True, max_len=200),
    _entry("landing_hero_image_url", "image", "", "Landing hero image", "Optional, up to 1 MB.",
           "Landing & login", public=True, branding=True),
    _entry("login_welcome_text", "string", "", "Login welcome text", "Up to 120 characters.",
           "Landing & login", public=True, branding=True, max_len=120),
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
    if spec["type"] == "int":
        return int(str(raw).strip())
    return str(raw)


def _serialize(spec: dict, value: Any) -> str:
    if spec["type"] == "bool":
        return "1" if value else "0"
    if spec["type"] == "int":
        return str(int(value))
    return str(value)


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
    if row is not None and row.value is not None and (row.value != "" or spec["type"] in _TEXT_TYPES):
        try:
            value = _parse(spec, row.value)
        except (TypeError, ValueError):
            value = spec["default"]
        if spec.get("required") and value == "":
            value = spec["default"]

    with _cache_lock:
        _cache[key] = (now, value)
    return value


_TEXT_TYPES = ("string", "template", "date", "enum", "url", "image")
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_PHONE_RE = re.compile(r"^\+?[0-9 ()-]{6,20}$")
_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


def _validate_text(spec: dict, value: Any) -> str:
    label = spec["label"]
    kind = spec["type"]
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{label} must be text")
    text = value.strip()
    if spec.get("required") and not text:
        raise HTTPException(status_code=400, detail=f"{label} cannot be empty")

    if kind == "enum":
        if text not in spec["choices"]:
            raise HTTPException(status_code=400, detail=f"{label} must be one of: {', '.join(spec['choices'])}")
        return text

    if kind == "date":
        if text:
            try:
                date.fromisoformat(text)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"{label} must be a date in YYYY-MM-DD format")
        return text

    max_len = spec.get("max_len") or 500
    if len(text) > max_len:
        raise HTTPException(status_code=400, detail=f"{label} must be at most {max_len} characters")

    # Plain text only: no markup, no control characters (line breaks only where allowed).
    if "<" in text or ">" in text:
        raise HTTPException(status_code=400, detail=f"{label} must be plain text (no < or > characters)")
    allowed_controls = "\n\r" if spec.get("multiline") else ""
    if any(ord(ch) < 32 and ch not in allowed_controls for ch in text):
        raise HTTPException(status_code=400, detail=f"{label} contains invalid characters")

    if kind == "url":
        if text and (not text.lower().startswith("https://") or any(c.isspace() for c in text)):
            raise HTTPException(status_code=400, detail=f"{label} must be an https:// link")
    elif kind == "image":
        if text and not (text.lower().startswith("https://") or text.startswith("/uploads/")):
            raise HTTPException(status_code=400, detail=f"{label} must be an uploaded image")
        if ".." in text:
            raise HTTPException(status_code=400, detail=f"{label} must be an uploaded image")
    elif kind == "template":
        stripped = _PLACEHOLDER_RE.sub("", text)
        if "{" in stripped or "}" in stripped:
            raise HTTPException(status_code=400, detail=f"{label} has an unmatched {{ or }}")
        unknown = sorted({n for n in _PLACEHOLDER_RE.findall(text) if n not in spec["placeholders"]})
        if unknown:
            allowed = ", ".join("{" + p + "}" for p in spec["placeholders"])
            raise HTTPException(
                status_code=400,
                detail=f"{label} uses unknown placeholder(s): {', '.join('{' + n + '}' for n in unknown)}. Allowed: {allowed}",
            )
    elif spec.get("fmt") == "phone" and text and not _PHONE_RE.match(text):
        raise HTTPException(status_code=400, detail=f"{label} must be a valid phone number")
    elif spec.get("fmt") == "email" and text and not _EMAIL_RE.match(text):
        raise HTTPException(status_code=400, detail=f"{label} must be a valid email address")
    return text


def validate_value(key: str, value: Any) -> Any:
    """Validate type and range; returns the normalised value or raises 400."""
    spec = _spec(key)
    if spec["type"] in _TEXT_TYPES:
        return _validate_text(spec, value)
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
    _validate_cross_fields(db, validated)
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


def _validate_cross_fields(db: Session, validated: dict) -> None:
    """Checks that involve several settings, evaluated on the merged result."""
    def effective(key):
        return validated[key] if key in validated else get_setting(db, key)

    if not any(k.startswith(("theme_", "announcement_")) for k in validated):
        return

    t_start, t_end = effective("theme_start_date"), effective("theme_end_date")
    if effective("theme_schedule_enabled") and (not t_start or not t_end):
        raise HTTPException(status_code=400, detail="Theme schedule needs both a start and an end date")
    if t_start and t_end and t_end < t_start:
        raise HTTPException(status_code=400, detail="Theme end date must be on or after the start date")

    a_start, a_end = effective("announcement_start_date"), effective("announcement_end_date")
    if a_start and a_end and a_end < a_start:
        raise HTTPException(status_code=400, detail="Announcement end date must be on or after the start date")
    if effective("announcement_enabled") and not effective("announcement_text"):
        raise HTTPException(status_code=400, detail="Announcement text is required to show the banner")


def resolve_theme(db: Session, today: Optional[date] = None) -> str:
    """Theme for today (IST). Scheduled themes revert to 'default' outside their dates."""
    theme = get_setting(db, "active_theme")
    if not get_setting(db, "theme_schedule_enabled"):
        return theme
    start, end = get_setting(db, "theme_start_date"), get_setting(db, "theme_end_date")
    if not start or not end:
        return "default"
    today = today or today_business()
    return theme if start <= today.isoformat() <= end else "default"


def active_announcement(db: Session, today: Optional[date] = None) -> Optional[dict]:
    if not get_setting(db, "announcement_enabled"):
        return None
    text = get_setting(db, "announcement_text")
    if not text:
        return None
    today_iso = (today or today_business()).isoformat()
    start, end = get_setting(db, "announcement_start_date"), get_setting(db, "announcement_end_date")
    if (start and today_iso < start) or (end and today_iso > end):
        return None
    stamps = [
        r.updated_at for r in db.query(AppSetting).filter(AppSetting.key.like("announcement_%")).all()
        if r.updated_at is not None
    ]
    return {
        "text": text,
        "style": get_setting(db, "announcement_style"),
        "link_url": get_setting(db, "announcement_link_url") or None,
        "dismissible": bool(get_setting(db, "announcement_dismissible")),
        "updated_at": max(stamps).isoformat() if stamps else None,
    }


def public_settings(db: Session) -> dict:
    """Everything a logged-in user needs, including payment instructions."""
    data = {key: get_setting(db, key) for key, spec in SETTINGS_REGISTRY.items() if spec["public"]}
    data["theme"] = resolve_theme(db)
    data["announcement"] = active_announcement(db)
    return data


def branding_settings(db: Session) -> dict:
    """Pre-login branding only: never payment details or anything private."""
    data = {key: get_setting(db, key) for key, spec in SETTINGS_REGISTRY.items() if spec["branding"]}
    data["theme"] = resolve_theme(db)
    return data


def org_name(db: Session) -> str:
    return get_setting(db, "org_display_name") or DEFAULT_ORG_NAME


def render_message(db: Session, key: str, context: dict) -> str:
    """Fill a message template. Blank templates fall back to the default text."""
    spec = _spec(key)
    template = get_setting(db, key) or spec["default"]
    values = {"org_name": org_name(db), **context}
    return _PLACEHOLDER_RE.sub(lambda m: str(values.get(m.group(1), "")), template).strip()


def welcome_content(db: Session, member_name: Optional[str] = None) -> tuple[str, str]:
    """(title, message) for the welcome notification."""
    from app.utils.message_format import with_islamic_greeting

    message = render_message(db, "msg_welcome", {"member_name": member_name or ""})
    return f"Welcome to {org_name(db)}", with_islamic_greeting(message)
