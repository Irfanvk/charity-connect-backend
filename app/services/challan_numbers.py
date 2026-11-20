"""Real payment numbers: ``<prefix>-<yy><yy+1>-<running number>``, e.g. PG-2526-0042.

The year is the organisation's Aug-Jul financial year (the same as the reports) of the day
the payment is started, in India time. The running number starts at 0001 each year. One
number per payment: months paid together with one proof share it.

The counter row is locked (SELECT ... FOR UPDATE on Postgres) until the caller commits, so
two payments can never get the same number. Older and imported challans have no number and
are shown as CH-<id>.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import NumberSequence
from app.utils.timezone import today_business

DEFAULT_PREFIX = "PG"


def _prefix(db: Session) -> str:
    from app.services.settings_service import get_setting

    try:
        raw = get_setting(db, "challan_number_prefix")
    except Exception:
        raw = DEFAULT_PREFIX
    cleaned = re.sub(r"[^A-Z0-9]", "", str(raw or "").upper())[:6]
    return cleaned or DEFAULT_PREFIX


def series_key(db: Session, day: date | None = None) -> str:
    day = day or today_business()
    start = day.year if day.month >= 8 else day.year - 1
    return f"{_prefix(db)}-{start % 100:02d}{(start + 1) % 100:02d}"


def next_number(db: Session, day: date | None = None) -> str:
    """The next payment number. Call inside the transaction that saves the payment."""
    key = series_key(db, day)
    row = db.query(NumberSequence).filter(NumberSequence.key == key).with_for_update().first()
    if row is None:
        try:
            with db.begin_nested():
                db.add(NumberSequence(key=key, last=0))
        except IntegrityError:
            pass  # another request created the series first
        row = db.query(NumberSequence).filter(NumberSequence.key == key).with_for_update().first()
    row.last = int(row.last or 0) + 1
    db.flush()
    return f"{key}-{row.last:04d}"


def display_number(challan) -> str:
    """What people see: the real number, or CH-<id> for older rows."""
    return getattr(challan, "challan_no", None) or f"CH-{challan.id}"
