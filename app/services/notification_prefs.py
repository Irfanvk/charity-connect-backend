"""Push preferences and quiet hours.

Preferences only control *push*; in-app notification records are always saved.
Urgent notifications (security events) ignore both preferences and quiet hours.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import NotificationPreference, User
from app.utils.timezone import BUSINESS_TZ, now_utc

MEMBER_CATEGORIES = ["payment_updates", "reminders", "announcements"]
ADMIN_CATEGORIES = ["admin_payment_reviews", "admin_requests", "admin_fund_approvals"]

DEFAULT_QUIET_START = "22:00"
DEFAULT_QUIET_END = "07:00"


def uses_simple_settings(user_or_role) -> bool:
    """Admins (not superadmins) only switch push on or off per device: they get every
    notification, with no category switches, quiet hours or reminder choices."""
    role = getattr(user_or_role, "role", user_or_role)
    return str(getattr(role, "value", role) or "").lower() == "admin"


def categories_for_role(role) -> list[str]:
    value = getattr(role, "value", role)
    if str(value).lower() in ("admin", "superadmin"):
        return ADMIN_CATEGORIES + MEMBER_CATEGORIES
    return list(MEMBER_CATEGORIES)


def load_preferences(db: Session, user_id: int, role) -> dict[str, bool]:
    """Return {category: push_enabled}; a missing row means enabled."""
    stored = {
        row.category: bool(row.push_enabled)
        for row in db.query(NotificationPreference).filter(NotificationPreference.user_id == user_id).all()
    }
    return {category: stored.get(category, True) for category in categories_for_role(role)}


def save_preferences(db: Session, user_id: int, role, updates: dict[str, bool]) -> dict[str, bool]:
    allowed = set(categories_for_role(role))
    unknown = sorted(set(updates) - allowed)
    if unknown:
        raise ValueError(f"Unknown notification categories: {', '.join(unknown)}")
    existing = {
        row.category: row
        for row in db.query(NotificationPreference).filter(NotificationPreference.user_id == user_id).all()
    }
    for category, enabled in updates.items():
        row = existing.get(category)
        if row is None:
            db.add(NotificationPreference(user_id=user_id, category=category, push_enabled=bool(enabled)))
        else:
            row.push_enabled = bool(enabled)
    db.commit()
    return load_preferences(db, user_id, role)


def push_allowed(db: Session, user_id: int, category: str | None) -> bool:
    """False only if the user switched this category's push off."""
    if not category:
        return True
    row = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user_id, NotificationPreference.category == category)
        .first()
    )
    return True if row is None else bool(row.push_enabled)


def parse_hhmm(value: str | None, fallback: str) -> time:
    text = (value or fallback).strip()
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


def validate_hhmm(value: str) -> str:
    parsed = parse_hhmm(value, "00:00")
    return parsed.strftime("%H:%M")


def quiet_hours_resume_at(user: User | None, now: datetime | None = None) -> datetime | None:
    """UTC datetime when quiet hours end, or None if the user is not in quiet hours now.

    Handles windows that cross midnight (e.g. 22:00-07:00), evaluated in IST.
    """
    if user is None or not getattr(user, "quiet_hours_enabled", False):
        return None
    current = (now or now_utc()).astimezone(BUSINESS_TZ)
    start = parse_hhmm(user.quiet_hours_start, DEFAULT_QUIET_START)
    end = parse_hhmm(user.quiet_hours_end, DEFAULT_QUIET_END)
    t = current.time().replace(second=0, microsecond=0)

    if start == end:
        return None
    if start < end:
        in_window = start <= t < end
        resume_date = current.date()
    else:
        in_window = t >= start or t < end
        resume_date = current.date() + timedelta(days=1) if t >= start else current.date()
    if not in_window:
        return None
    resume = datetime.combine(resume_date, end, tzinfo=BUSINESS_TZ)
    return resume.astimezone(timezone.utc)
