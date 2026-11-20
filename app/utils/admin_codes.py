"""Short public codes for admins, shown to members instead of their names.

From the admin's own member ID: MEM-0012 -> A12. Admins without a member record get AD<user
number> (e.g. AD3), so codes never clash. Worked out each time, nothing to store.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.models import Member

_DIGITS = re.compile(r"(\d+)")


def code_from(member_code: str | None, user_id: int | None) -> str:
    match = _DIGITS.search(str(member_code or "")) if str(member_code or "").upper().startswith("MEM") else None
    if match:
        return f"A{int(match.group(1))}"
    return f"AD{user_id}" if user_id is not None else "Admin"


def admin_code(db: Session, user_id: int | None) -> str:
    if user_id is None:
        return "Admin"
    member_code = db.query(Member.member_code).filter(Member.user_id == user_id).scalar()
    return code_from(member_code, user_id)
