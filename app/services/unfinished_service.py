"""Payments a member started but never finished (no proof handed in).

A challan is "unfinished" when the member created it themselves (entry_source
"self"), it is still generated/pending, and nothing was handed in (see
challan_state.submitted_clause). The "not paid yet" rows from the 2026-04
import and admin entries are never included.

- Members get a reminder 48 hours after creating one, and one follow-up at 7 days.
  Several due on the same run are sent as one notification.
- Admins get one summary each morning (from 09:00 IST) listing those open 48+ hours.
- A month that was since paid with another challan is a leftover: no reminders,
  shown to admins as "already paid" so they can cancel it.
Every send is logged in ``nudge_logs`` by a unique key, so nothing goes twice.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, func, not_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.models import (
    Challan, ChallanStatus, ChallanType, Member, Notification, NudgeLog, User, UserRole,
)
from app.services.challan_state import submitted_clause
from app.services.settings_service import get_setting
from app.utils.timezone import now_business, now_utc

logger = logging.getLogger(__name__)

FIRST_AFTER = timedelta(hours=48)
FOLLOW_UP_AFTER = timedelta(days=7)
MIN_GAP = timedelta(days=3)          # never two reminders for one challan closer than this
DIGEST_FROM_HOUR = 9                 # IST
DIGEST_MAX_LINES = 8
MEMBER_LINK = "/Challans?unfinished=1"
ADMIN_LINK = "/Unfinished"


def _now_naive(db: Session) -> datetime:
    """"Now" on the database's own clock, the one that stamped created_at / sent_at
    (server_default now() follows the database's time zone, which may not be UTC)."""
    value = db.query(func.now()).scalar()
    if isinstance(value, str):  # SQLite returns text in UTC
        value = datetime.fromisoformat(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return now_utc().replace(tzinfo=None)


def _unfinished_clause():
    # created_by_user_id: the 2026-04 import also marked its "not paid yet" rows "self",
    # but without a creator; a payment a member really started always has one.
    return and_(
        func.coalesce(Challan.entry_source, "") == "self",
        Challan.created_by_user_id.isnot(None),
        Challan.status.in_([ChallanStatus.GENERATED, ChallanStatus.PENDING]),
        not_(submitted_clause()),
    )


def _paid_months(db: Session, member_ids: set[int]) -> set[tuple[int, str]]:
    """(member_id, month) pairs already approved or handed in with another challan."""
    if not member_ids:
        return set()
    rows = db.query(Challan.member_id, Challan.month).filter(
        Challan.member_id.in_(member_ids),
        Challan.type == ChallanType.MONTHLY,
        Challan.status.in_([ChallanStatus.APPROVED, ChallanStatus.PENDING]),
        submitted_clause(),
    ).all()
    return {(m, month) for m, month in rows if month}


def _sent_keys(db: Session, prefixes: list[str]) -> dict[str, datetime]:
    if not prefixes:
        return {}
    rows = db.query(NudgeLog.key, NudgeLog.sent_at).filter(NudgeLog.key.in_(prefixes)).all()
    return {k: t for k, t in rows}


def _amount(value) -> str:
    v = float(value or 0)
    return f"₹{v:,.0f}" if v.is_integer() else f"₹{v:,.2f}"


def _month_label(month: str | None) -> str:
    try:
        return datetime.strptime(month, "%Y-%m").strftime("%b %Y")
    except (TypeError, ValueError):
        return month or ""


def _what(challan: Challan) -> str:
    if challan.type == ChallanType.MONTHLY:
        return _month_label(challan.month)
    title = challan.campaign.title if challan.campaign is not None else "a campaign"
    return title


def _key(challan_id: int, kind: str) -> str:
    return f"challan:{challan_id}:{kind}"


def _log(db: Session, key: str) -> bool:
    """Claim a key. False if it was already used (another run sent it)."""
    db.add(NudgeLog(key=key))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _notify(db: Session, user_id: int, role, title: str, message: str, link: str, category: str) -> None:
    from app.services.notification_service import NotificationService

    notification = Notification(
        user_id=user_id, title=title, message=message, target_role=role,
        type="payment", category=category, link_url=link,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    try:
        NotificationService.dispatch_notification(db, notification)
    except Exception:
        logger.exception("Push for unfinished-payment notification %s failed", notification.id)


def _rows(db: Session, member_id: int | None = None):
    query = (
        db.query(Challan)
        .options(joinedload(Challan.member).joinedload(Member.user), joinedload(Challan.campaign))
        .filter(_unfinished_clause())
    )
    if member_id is not None:
        query = query.filter(Challan.member_id == member_id)
    return query.order_by(Challan.created_at.asc(), Challan.id.asc()).all()


def list_unfinished(db: Session, min_hours: int = 48, member_id: int | None = None) -> dict:
    now = _now_naive(db)
    challans = [c for c in _rows(db, member_id) if c.created_at is None or now - c.created_at >= timedelta(hours=min_hours)]
    paid = _paid_months(db, {c.member_id for c in challans})
    keys = []
    for c in challans:
        keys += [_key(c.id, "48h"), _key(c.id, "7d"), _key(c.id, f"manual:{now_business().date().isoformat()}")]
    sent = _sent_keys(db, keys)
    items = []
    for c in challans:
        member = c.member
        user = member.user if member is not None else None
        hours = int((now - c.created_at).total_seconds() // 3600) if c.created_at else None
        reminders = [k for k in ("48h", "7d") if _key(c.id, k) in sent]
        items.append({
            "id": c.id,
            "challan_no": c.challan_no or f"CH-{c.id}",
            "member_id": c.member_id,
            "member_code": member.member_code if member is not None else None,
            "member_name": (member.full_name if member is not None else None) or (user.full_name if user else None),
            "phone": user.phone if user else None,
            "type": c.type.value if hasattr(c.type, "value") else c.type,
            "month": c.month,
            "campaign_id": c.campaign_id,
            "campaign_title": c.campaign.title if c.campaign is not None else None,
            "what": _what(c),
            "amount": float(c.amount or 0),
            # real UTC time, worked out from the age (created_at follows the database clock)
            "created_at": (now_utc() - (now - c.created_at)).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
            if c.created_at else None,
            "hours_open": hours,
            "reminders_sent": reminders,
            "reminded_today": _key(c.id, f"manual:{now_business().date().isoformat()}") in sent,
            "already_paid": c.type == ChallanType.MONTHLY and (c.member_id, c.month) in paid,
        })
    return {"items": items, "count": len(items), "min_hours": min_hours}


def _member_message(member: Member, user: User, challans: list[Challan], follow_up: bool) -> tuple[str, str]:
    name = (member.full_name or user.full_name or "").strip()
    lines = ", ".join(f"{_what(c)} ({_amount(c.amount)})" for c in challans)
    many = len(challans) > 1
    title = "Gentle reminder: payment not finished" if follow_up else "Your payment is not finished"
    body = (
        f"Assalamu Alaikum{(' ' + name) if name else ''}. "
        f"You started {'these payments' if many else 'a payment'} but no proof has been uploaded yet: {lines}. "
        f"Please open My payments and upload the proof, or cancel {'them' if many else 'it'} if you started "
        f"{'them' if many else 'it'} by mistake."
    )
    return title, body


def run_member_reminders(db: Session) -> dict:
    now = _now_naive(db)
    challans = _rows(db)
    paid = _paid_months(db, {c.member_id for c in challans})
    keys = [k for c in challans for k in (_key(c.id, "48h"), _key(c.id, "7d"))]
    sent = _sent_keys(db, keys)

    due: dict[int, dict[str, list[Challan]]] = {}
    for c in challans:
        member = c.member
        user = member.user if member is not None else None
        if c.created_at is None or user is None or not user.is_active:
            continue
        if c.type == ChallanType.MONTHLY and (c.member_id, c.month) in paid:
            continue
        age = now - c.created_at
        first_at = sent.get(_key(c.id, "48h"))
        if first_at is None:
            if age >= FIRST_AFTER:
                due.setdefault(c.member_id, {}).setdefault("48h", []).append(c)
        elif _key(c.id, "7d") not in sent and age >= FOLLOW_UP_AFTER and now - first_at >= MIN_GAP:
            due.setdefault(c.member_id, {}).setdefault("7d", []).append(c)

    counts = {"members": 0, "first": 0, "follow_up": 0}
    for groups in due.values():
        for kind, items in groups.items():
            claimed = [c for c in items if _log(db, _key(c.id, kind))]
            if not claimed:
                continue
            member = claimed[0].member
            title, body = _member_message(member, member.user, claimed, follow_up=(kind == "7d"))
            try:
                _notify(db, member.user.id, member.user.role, title, body, MEMBER_LINK, "reminders")
            except Exception:
                logger.exception("Unfinished-payment reminder failed for member %s", member.id)
                db.rollback()
                continue
            counts["members"] += 1
            counts["first" if kind == "48h" else "follow_up"] += len(claimed)
    return counts


def run_admin_digest(db: Session) -> dict:
    now_ist = now_business()
    if now_ist.hour < DIGEST_FROM_HOUR:
        return {"status": "too_early"}
    data = list_unfinished(db, min_hours=48)
    if not data["items"]:
        return {"status": "nothing_open"}
    if not _log(db, f"admin-digest:{now_ist.date().isoformat()}"):
        return {"status": "already_sent"}

    open_items = [i for i in data["items"] if not i["already_paid"]]
    leftovers = len(data["items"]) - len(open_items)
    by_member: dict[int, list[dict]] = {}
    for item in open_items:
        by_member.setdefault(item["member_id"], []).append(item)
    lines = []
    for items in list(by_member.values())[:DIGEST_MAX_LINES]:
        who = items[0]["member_code"] or items[0]["member_name"] or "Member"
        lines.append(f"{who} ({', '.join(i['what'] for i in items)})")
    more = len(by_member) - len(lines)
    parts = []
    if open_items:
        parts.append(
            f"{len(open_items)} payment{'s' if len(open_items) != 1 else ''} started by "
            f"{len(by_member)} member{'s' if len(by_member) != 1 else ''} not finished for 2+ days: "
            + "; ".join(lines) + (f"; and {more} more" if more > 0 else "") + "."
        )
    if leftovers:
        parts.append(f"{leftovers} leftover{'s' if leftovers != 1 else ''} for months already paid can be cancelled.")
    message = " ".join(parts)

    from app.services.notification_service import NotificationService

    admins = db.query(User).filter(User.role.in_([UserRole.ADMIN, UserRole.SUPERADMIN]), User.is_active == True).all()  # noqa: E712
    for admin in admins:
        try:
            _notify(db, admin.id, admin.role, "Unfinished payments", message, ADMIN_LINK, "admin_payment_reviews")
        except Exception:
            logger.exception("Unfinished-payment summary failed for admin %s", admin.id)
            db.rollback()
    return {"status": "sent", "admins": len(admins), "open": len(open_items), "leftovers": leftovers}


def remind_now(db: Session, current_user: dict, challan_id: int) -> dict:
    """An admin sends one reminder now for this challan (at most once a day)."""
    challan = db.query(Challan).filter(Challan.id == challan_id).filter(_unfinished_clause()).first()
    if challan is None:
        raise HTTPException(status_code=404, detail="This payment is no longer unfinished")
    member = challan.member
    user = member.user if member is not None else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="This member has no active login to send a reminder to")
    if not _log(db, _key(challan.id, f"manual:{now_business().date().isoformat()}")):
        raise HTTPException(status_code=409, detail="A reminder for this payment was already sent today")
    title, body = _member_message(member, user, [challan], follow_up=True)
    _notify(db, user.id, user.role, title, body, MEMBER_LINK, "reminders")
    from app.utils.audit import log_audit

    log_audit(
        db, user_id=current_user.get("user_id"), action="challan_unfinished_remind",
        entity_type="Challan", entity_id=challan.id,
        new_values={"member_id": challan.member_id, "what": _what(challan)}, auto_commit=True,
    )
    return {"status": "sent", "challan_id": challan.id}


def run_for_now() -> dict:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if not get_setting(db, "unfinished_payment_reminders"):
            return {"status": "disabled"}
        return {"members": run_member_reminders(db), "admins": run_admin_digest(db)}
    finally:
        db.close()
