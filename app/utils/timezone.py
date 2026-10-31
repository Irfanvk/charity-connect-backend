"""Business-time helpers. Timestamps are stored as naive UTC; business dates use BUSINESS_TZ."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings

BUSINESS_TZ = ZoneInfo(settings.BUSINESS_TIMEZONE)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_business() -> datetime:
    return now_utc().astimezone(BUSINESS_TZ)


def today_business() -> date:
    return now_business().date()


def current_month_business() -> str:
    return now_business().strftime("%Y-%m")


def to_business(dt: datetime) -> datetime:
    """Convert a naive-UTC or aware datetime to BUSINESS_TZ (naive is treated as UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BUSINESS_TZ)


def business_to_naive_utc(dt: datetime) -> datetime:
    """Convert an aware business-time datetime to naive UTC for comparing with stored columns."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
