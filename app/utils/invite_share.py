from datetime import datetime, timezone
from math import ceil
from urllib.parse import quote

from app.config import settings
from app.utils.message_format import with_islamic_greeting


def _normalize_base_url() -> str:
    base_url = str(settings.FRONTEND_BASE_URL or "").strip().rstrip("/")
    return base_url or "http://localhost:5173"


def _to_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def build_invite_registration_url(invite_code: str) -> str:
    normalized_code = str(invite_code or "").strip()
    if not normalized_code:
        return f"{_normalize_base_url()}/register"
    return f"{_normalize_base_url()}/register?invite_code={quote(normalized_code)}"


def build_invite_expiry_label(expiry_date: datetime | None) -> str | None:
    normalized_expiry = _to_utc_naive(expiry_date)
    if normalized_expiry is None:
        return None

    remaining_seconds = (normalized_expiry - datetime.utcnow()).total_seconds()
    if remaining_seconds <= 0:
        return "This invite has expired."

    if remaining_seconds < 86400:
        hours = max(1, ceil(remaining_seconds / 3600))
        unit = "hour" if hours == 1 else "hours"
        return f"This invite expires in {hours} {unit}."

    days = max(1, ceil(remaining_seconds / 86400))
    unit = "day" if days == 1 else "days"
    return f"This invite expires in {days} {unit}."


def build_invite_share_message(invite_code: str, expiry_date: datetime | None = None) -> str:
    normalized_code = str(invite_code or "").strip()
    registration_url = build_invite_registration_url(normalized_code)
    parts = [
        "You've been invited to join CharityHub!",
        "",
        "Use this invite code to register:",
        normalized_code,
        "",
        "Open your registration link:",
        registration_url,
    ]

    expiry_label = build_invite_expiry_label(expiry_date)
    if expiry_label:
        parts.extend(["", expiry_label])

    return with_islamic_greeting("\n".join(parts))


def build_invite_whatsapp_share_url(invite_code: str, expiry_date: datetime | None = None) -> str:
    share_message = build_invite_share_message(invite_code, expiry_date)
    return f"https://wa.me/?text={quote(share_message)}"