"""Mobile numbers written different ways are the same number.

"+971 50 123 4567", "00971501234567", "971-50-1234567" and the local "0501234567" all mean the
same mobile. Invites and sign-up compare numbers with ``phones_match`` instead of exact text, so a
member is not stopped by "Phone does not match invite" for a space or a missing +971.
"""
from __future__ import annotations

import re

# A local number must keep at least this many digits to match a number with its country code
# (UAE/Saudi mobiles have 9 after the code, Indian 10).
_MIN_LOCAL_DIGITS = 8


def phone_digits(phone: str | None) -> str:
    """Digits only, without an international 00 or a local leading 0."""
    raw = str(phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and not raw.startswith("+"):
        digits = digits[1:]
    return digits


def phones_match(a: str | None, b: str | None) -> bool:
    da, db = phone_digits(a), phone_digits(b)
    if not da or not db:
        return False
    if da == db:
        return True
    short, long = sorted((da, db), key=len)
    return len(short) >= _MIN_LOCAL_DIGITS and long.endswith(short)


def last_digits(phone: str | None, n: int = 4) -> str:
    return phone_digits(phone)[-n:]


def mask_phone(phone: str | None) -> str | None:
    """"+971501234567" -> "+971 ••••• 4567" (the country code and the last 4 digits)."""
    raw = str(phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 4:
        return None
    m = re.match(r"^\+(\d{1,3})", raw)
    head = f"+{m.group(1)} " if m and len(digits) > 9 else ""
    return f"{head}••••• {digits[-4:]}"


def mask_email(email: str | None) -> str | None:
    """"latheef@gmail.com" -> "l•••@gmail.com"."""
    value = str(email or "").strip()
    if "@" not in value:
        return None
    name, domain = value.split("@", 1)
    return f"{name[:1]}•••@{domain}"


def find_users_by_phone(db, phone: str | None):
    """Users whose mobile is this number, however either was written."""
    from app.models import User

    digits = phone_digits(phone)
    if len(digits) < 4:
        return []
    rows = db.query(User).filter(User.phone.isnot(None), User.phone.like(f"%{digits[-4:]}")).all()
    return [u for u in rows if phones_match(u.phone, phone)]
