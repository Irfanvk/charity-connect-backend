"""Who did something, in words that suit the person looking.

Admins, superadmins and executives ("staff") see codes: "admin (A12)", "executive (E12)".
Members (and anyone not signed in, e.g. the public receipt page) see only "the committee",
never a name or a code. Members who did something themselves are shown by their own name.

Codes come from the person's member ID: MEM-0012 -> A12 (admin) / E12 (executive). Without a
member record: AD<user number> / EX<user number>, so codes never clash. Nothing is stored.

The viewer is set once per request by ``get_current_user`` (``set_viewer``); without it the
member wording is used, so nothing leaks by mistake.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.orm import Session

from app.models.models import Member

_DIGITS = re.compile(r"(\d+)")
COMMITTEE = "the committee"
ADMIN_ROLES = ("admin", "superadmin")
STAFF_ROLES = ("admin", "superadmin", "executive")

_viewer_is_staff: ContextVar[bool] = ContextVar("viewer_is_staff", default=False)


def _role(value) -> str:
    role = getattr(value, "role", value)
    return str(getattr(role, "value", role) or "").lower()


def set_viewer(role) -> None:
    """Called for every signed-in request: staff see codes, members see "the committee"."""
    _viewer_is_staff.set(_role(role) in STAFF_ROLES)


def viewer_is_staff() -> bool:
    return _viewer_is_staff.get()


@contextmanager
def viewing_as(staff: bool):
    """Temporarily word labels for staff (True) or members (False), e.g. in tests or jobs."""
    token = _viewer_is_staff.set(staff)
    try:
        yield
    finally:
        _viewer_is_staff.reset(token)


def code_from(member_code: str | None, user_id: int | None, prefix: str = "A") -> str:
    match = _DIGITS.search(str(member_code or "")) if str(member_code or "").upper().startswith("MEM") else None
    if match:
        return f"{prefix}{int(match.group(1))}"
    fallback = "EX" if prefix == "E" else "AD"
    return f"{fallback}{user_id}" if user_id is not None else "Admin"


def is_admin_user(user) -> bool:
    return _role(user) in ADMIN_ROLES


def is_staff_user(user) -> bool:
    return _role(user) in STAFF_ROLES


def admin_label(code: str) -> str:
    """The words staff see for an admin who did something: "admin (A12)"."""
    return f"admin ({code})"


def staff_code(user) -> str | None:
    """A12 for an admin, E12 for an executive, None for a member."""
    if user is None or not is_staff_user(user):
        return None
    member = getattr(user, "member", None)
    prefix = "E" if _role(user) == "executive" else "A"
    return code_from(getattr(member, "member_code", None), user.id, prefix)


def actor_label(user, staff: bool | None = None) -> str | None:
    """How the person who did something is shown.

    Staff viewer: "admin (A12)" / "executive (E12)". Member viewer: "the committee".
    A member who did it themself: their own name. ``staff`` overrides the request's viewer
    (e.g. False for a notification that goes to a member)."""
    if user is None:
        return None
    if is_staff_user(user):
        if not (viewer_is_staff() if staff is None else staff):
            return COMMITTEE
        kind = "executive" if _role(user) == "executive" else "admin"
        return f"{kind} ({staff_code(user)})"
    return getattr(user, "full_name", None) or getattr(user, "username", None)


def actor_label_for(db: Session, user_id: int | None, staff: bool | None = None) -> str | None:
    if user_id is None:
        return None
    from app.models.models import User
    return actor_label(db.query(User).filter(User.id == user_id).first(), staff)


def actor_labels(db: Session, user_ids, staff: bool | None = None) -> dict:
    """{user_id: label} for many users in one query."""
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    from app.models.models import User
    return {u.id: actor_label(u, staff) for u in db.query(User).filter(User.id.in_(ids)).all()}


def admin_code(db: Session, user_id: int | None) -> str:
    """A12 / E12 code for a user (receipts list filter, staff only)."""
    if user_id is None:
        return "Admin"
    from app.models.models import User
    user = db.query(User).filter(User.id == user_id).first()
    if user is not None and is_staff_user(user):
        return staff_code(user)
    member_code = db.query(Member.member_code).filter(Member.user_id == user_id).scalar()
    return code_from(member_code, user_id)
