"""Members who cannot pay every month.

Three tools, agreed with the committee (2026-11-20):

- Excused month: an admin agrees the member owes nothing for that month (e.g. no work).
  A member can also ask from the app; an admin approves or rejects. Excused months are not
  owed, get no reminders, and show as "Excused" in statements, reports and the paid list.
  A setting can limit how many months a member may be excused in one year, Jan-Dec (0 = no limit).
  A month that is paid (or sent for approval) cannot be excused; a payment always wins.
- Yearly pledge (seasonal members): for one year (Jan-Dec) the member promises a total amount
  instead of paying every month. They pay whenever they can, at their usual monthly fee or
  any amount an admin records; months are not owed one by one. What is left of the pledge is
  owed by the end of July. No monthly reminders in a pledge year.
- Not a monthly member (``members.monthly_member = False``): owes no monthly fees at all,
  e.g. someone who only gives one-time contributions until they agree to a monthly fee.

``Book`` loads all of this for many members at once, for reports.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Challan, ChallanStatus, ChallanType, ExcusedMonth, Member, MemberPledge, User
from app.utils.timezone import current_month_business

APPROVED, REQUESTED, REJECTED = "approved", "requested", "rejected"
MAX_REASON = 300


# ---------------------------------------------------------------- small helpers
# The organisation's year is the calendar year, January to December (until 2026-11-23 it was
# August to July). Pledges and the excused-months limit count per year.
def fy_of(month: str) -> int:
    """The year a month belongs to: 2026-03 -> 2026."""
    return int(month[:4])


def fy_label(year: int) -> str:
    return str(year)


def fy_months(year: int) -> list[str]:
    return [f"{year}-{m:02d}" for m in range(1, 13)]


def is_monthly(member: Member) -> bool:
    return getattr(member, "monthly_member", True) is not False


def _valid_month(value: str) -> str:
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m").strftime("%Y-%m")
    except ValueError:
        raise HTTPException(status_code=400, detail="Months must look like 2026-01")


def _clean(text: Optional[str], limit: int = MAX_REASON) -> Optional[str]:
    cleaned = (text or "").strip()
    if len(cleaned) > limit:
        raise HTTPException(status_code=400, detail=f"Please keep it under {limit} characters.")
    return cleaned or None


class Book:
    """Excused months, pledges and the monthly-member flag for many members, in two queries."""

    def __init__(self, db: Session, members: Iterable[Member]):
        self.members = {m.id: m for m in members}
        self.excused: dict[int, dict[str, Optional[str]]] = defaultdict(dict)  # member -> month -> reason
        self.pledges: dict[int, dict[int, MemberPledge]] = defaultdict(dict)   # member -> year -> pledge
        ids = list(self.members)
        if not ids:
            return
        for e in db.query(ExcusedMonth).filter(ExcusedMonth.member_id.in_(ids), ExcusedMonth.status == APPROVED).all():
            self.excused[e.member_id][e.month] = e.reason
        for p in db.query(MemberPledge).filter(MemberPledge.member_id.in_(ids)).all():
            self.pledges[p.member_id][p.year] = p

    def not_monthly(self, member_id: int) -> bool:
        m = self.members.get(member_id)
        return m is not None and not is_monthly(m)

    def is_excused(self, member_id: int, month: str) -> bool:
        return month in self.excused.get(member_id, {})

    def reason(self, member_id: int, month: str) -> Optional[str]:
        return self.excused.get(member_id, {}).get(month)

    def pledge(self, member_id: int, month_or_year) -> Optional[MemberPledge]:
        year = month_or_year if isinstance(month_or_year, int) else fy_of(month_or_year)
        return self.pledges.get(member_id, {}).get(year)

    def open_state(self, member_id: int, month: str) -> Optional[str]:
        """For a month with nothing paid: why it is not owed (None = it is owed)."""
        if self.not_monthly(member_id):
            return "not_monthly"
        if self.is_excused(member_id, month):
            return "excused"
        if self.pledge(member_id, month) is not None:
            return "pledge"
        return None


def owes_month(db: Session, member: Member, month: str) -> bool:
    """Is a monthly fee owed for this month (ignoring whether it is paid)? For reminders."""
    return Book(db, [member]).open_state(member.id, month) is None


def pledge_summaries(book: Book, member_id: int, rows: list[dict]) -> list[dict]:
    """Each pledge year of this member that the rows cover: promised, paid, waiting, left."""
    out = []
    years = sorted({fy_of(r["month"]) for r in rows})
    for year in years:
        p = book.pledge(member_id, year)
        if p is None:
            continue
        inside = [r for r in rows if fy_of(r["month"]) == year]
        paid = round(sum(r["amount"] for r in inside if r["state"] == "paid"), 2)
        waiting = round(sum(r["amount"] for r in inside if r["state"] == "waiting"), 2)
        out.append({
            "year": year, "label": fy_label(year), "amount": float(p.amount), "note": p.note,
            "paid": paid, "waiting": waiting, "left": round(max(float(p.amount) - paid - waiting, 0), 2),
            "ended": year < fy_of(current_month_business()),
        })
    return out


# ---------------------------------------------------------------- reading
def _excused_json(e: ExcusedMonth, names: dict[int, str]) -> dict:
    return {
        "id": e.id, "member_id": e.member_id, "month": e.month, "status": e.status, "reason": e.reason,
        "requested_by": names.get(e.requested_by_user_id), "decided_by": names.get(e.decided_by_user_id),
        "decided_at": e.decided_at.isoformat() if e.decided_at else None, "decision_note": e.decision_note,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _by(db: Session, user_id: Optional[int]) -> str:
    from app.utils.admin_codes import actor_label_for

    return actor_label_for(db, user_id, staff=False) or "the committee"  # told to the member


def _names(db: Session, ids) -> dict[int, str]:
    """Admins as "admin (A12)" (never their name), members by name."""
    from app.utils.admin_codes import actor_labels

    return actor_labels(db, ids)


def overview(db: Session, member: Member) -> dict:
    """Everything about one member's excused months and pledges (newest first)."""
    excused = (db.query(ExcusedMonth).filter(ExcusedMonth.member_id == member.id)
               .order_by(ExcusedMonth.month.desc()).all())
    pledges = db.query(MemberPledge).filter(MemberPledge.member_id == member.id).order_by(MemberPledge.year.desc()).all()
    names = _names(db, [e.requested_by_user_id for e in excused] + [e.decided_by_user_id for e in excused]
                   + [p.created_by_user_id for p in pledges])
    current = fy_of(current_month_business())
    limit = excused_limit(db)
    used = sum(1 for e in excused if e.status == APPROVED and fy_of(e.month) == current)
    paid_by_year: dict[int, float] = defaultdict(float)
    waiting_by_year: dict[int, float] = defaultdict(float)
    if pledges:
        from app.services.challan_state import is_submitted

        for c in db.query(Challan).filter(Challan.member_id == member.id, Challan.type == ChallanType.MONTHLY,
                                          Challan.month.isnot(None)).all():
            st = getattr(c.status, "value", c.status)
            if st == "approved":
                paid_by_year[fy_of(c.month)] += float(c.amount or 0)
            elif st == "pending" and is_submitted(c):
                waiting_by_year[fy_of(c.month)] += float(c.amount or 0)
    return {
        "member_id": member.id,
        "monthly_member": is_monthly(member),
        "monthly_fee": float(member.monthly_amount or 0),
        "excused_limit_per_year": limit,
        "excused_this_year": used,
        "current_year": current, "current_year_label": fy_label(current),
        "excused": [_excused_json(e, names) for e in excused],
        "pledges": [{
            "id": p.id, "year": p.year, "label": fy_label(p.year), "amount": float(p.amount), "note": p.note,
            "paid": round(paid_by_year[p.year], 2), "waiting": round(waiting_by_year[p.year], 2),
            "left": round(max(float(p.amount) - paid_by_year[p.year] - waiting_by_year[p.year], 0), 2),
            "set_by": names.get(p.created_by_user_id),
        } for p in pledges],
    }


def excused_limit(db: Session) -> int:
    from app.services.settings_service import get_setting

    try:
        return int(get_setting(db, "excused_months_per_year") or 0)
    except Exception:
        return 0


# ---------------------------------------------------------------- excused months
def _month_handed_in(db: Session, member_id: int, month: str) -> bool:
    from app.services.challan_state import submitted_clause

    return db.query(Challan.id).filter(
        Challan.member_id == member_id, Challan.type == ChallanType.MONTHLY, Challan.month == month,
        Challan.status != ChallanStatus.REJECTED, submitted_clause(),
    ).first() is not None


def _check_limit(db: Session, member_id: int, months: list[str], ignore_ids: Iterable[int] = ()) -> None:
    limit = excused_limit(db)
    if limit <= 0:
        return
    ignore = set(ignore_ids)
    by_year: dict[int, int] = defaultdict(int)
    for e in db.query(ExcusedMonth).filter(ExcusedMonth.member_id == member_id, ExcusedMonth.status == APPROVED).all():
        if e.id not in ignore and e.month not in months:
            by_year[fy_of(e.month)] += 1
    for m in months:
        by_year[fy_of(m)] += 1
    over = [y for y, n in by_year.items() if n > limit]
    if over:
        raise HTTPException(status_code=400, detail=(
            f"At most {limit} excused months per year are allowed ({', '.join(fy_label(y) for y in sorted(over))}). "
            "A yearly pledge may suit this member better, or change the limit in Settings."))


def _remove_unpaid_rows(db: Session, member_id: int, months: list[str]) -> int:
    """'Not paid yet' rows (nothing handed in) for excused months are no longer needed."""
    from app.services.challan_state import unpaid_monthly_clause

    rows = db.query(Challan).filter(Challan.member_id == member_id, Challan.month.in_(months),
                                    unpaid_monthly_clause()).all()
    for c in rows:
        db.delete(c)
    return len(rows)


def excuse_months(db: Session, member: Member, months: list[str], reason: Optional[str], actor_id: int) -> dict:
    """An admin excuses months (approves any request for them too). Commits."""
    if not is_monthly(member):
        raise HTTPException(status_code=400, detail="This member is not a monthly member, so no month is owed.")
    months = sorted({_valid_month(m) for m in months or []})
    if not months:
        raise HTTPException(status_code=400, detail="Choose at least one month.")
    if len(months) > 12:
        raise HTTPException(status_code=400, detail="At most 12 months at a time.")
    reason = _clean(reason)
    if not reason:
        raise HTTPException(status_code=400, detail="Please give a reason, e.g. no work these months.")
    paid = [m for m in months if _month_handed_in(db, member.id, m)]
    if paid:
        raise HTTPException(status_code=400, detail="Already paid or sent for approval: " + ", ".join(paid))
    existing = {e.month: e for e in db.query(ExcusedMonth).filter(ExcusedMonth.member_id == member.id,
                                                                   ExcusedMonth.month.in_(months)).all()}
    _check_limit(db, member.id, months, ignore_ids=[e.id for e in existing.values()])
    now = datetime.utcnow()
    approved_requests = []
    for m in months:
        e = existing.get(m)
        if e is None:
            e = ExcusedMonth(member_id=member.id, month=m)
            db.add(e)
        elif e.status == REQUESTED:
            approved_requests.append(m)
        e.status, e.reason, e.decided_by_user_id, e.decided_at = APPROVED, reason, actor_id, now
    removed = _remove_unpaid_rows(db, member.id, months)
    db.commit()
    if approved_requests:
        _tell_member(db, member, "Excused months approved",
                     f"Your request was approved by {_by(db, actor_id)}: nothing is owed for {_label(approved_requests)}.")
    return {"excused": months, "removed_unpaid_rows": removed}


def remove_excused(db: Session, member: Member, excused_id: int) -> None:
    """Undo an excused month (or delete a request/rejection). The month is owed again. Commits."""
    e = db.query(ExcusedMonth).filter(ExcusedMonth.id == excused_id, ExcusedMonth.member_id == member.id).first()
    if e is None:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(e)
    db.commit()


def request_months(db: Session, user_id: int, months: list[str], reason: Optional[str]) -> dict:
    """A member asks to be excused for some months. Admins are told. Commits."""
    member = db.query(Member).filter(Member.user_id == user_id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="There is no member record for your account.")
    if not is_monthly(member):
        raise HTTPException(status_code=400, detail="No monthly fee is owed on your account.")
    months = sorted({_valid_month(m) for m in months or []})
    if not months or len(months) > 12:
        raise HTTPException(status_code=400, detail="Choose between 1 and 12 months.")
    reason = _clean(reason)
    if not reason or len(reason) < 5:
        raise HTTPException(status_code=400, detail="Please tell the committee why, e.g. no work these months.")
    paid = [m for m in months if _month_handed_in(db, member.id, m)]
    if paid:
        raise HTTPException(status_code=400, detail="Already paid or sent: " + ", ".join(paid))
    existing = {e.month: e for e in db.query(ExcusedMonth).filter(ExcusedMonth.member_id == member.id,
                                                                   ExcusedMonth.month.in_(months)).all()}
    added = []
    for m in months:
        e = existing.get(m)
        if e is not None and e.status == APPROVED:
            continue
        if e is None:
            e = ExcusedMonth(member_id=member.id, month=m)
            db.add(e)
        e.status, e.reason, e.requested_by_user_id = REQUESTED, reason, user_id
        e.decided_by_user_id = e.decided_at = e.decision_note = None
        added.append(m)
    if not added:
        raise HTTPException(status_code=400, detail="These months are already excused.")
    db.commit()
    _tell_admins(db, member, added, reason)
    return {"requested": added}


def decide_request(db: Session, member: Member, excused_id: int, approve: bool, note: Optional[str], actor_id: int) -> dict:
    """Approve or reject one waiting request (approving checks the same rules as excusing). Commits."""
    e = db.query(ExcusedMonth).filter(ExcusedMonth.id == excused_id, ExcusedMonth.member_id == member.id).first()
    if e is None or e.status != REQUESTED:
        raise HTTPException(status_code=404, detail="This request was already decided or removed.")
    note = _clean(note)
    if approve:
        if _month_handed_in(db, member.id, e.month):
            raise HTTPException(status_code=400, detail=f"{e.month} is already paid or sent for approval.")
        _check_limit(db, member.id, [e.month], ignore_ids=[e.id])
        e.status = APPROVED
        _remove_unpaid_rows(db, member.id, [e.month])
    else:
        if not note:
            raise HTTPException(status_code=400, detail="Please say why it is rejected.")
        e.status = REJECTED
    e.decided_by_user_id, e.decided_at, e.decision_note = actor_id, datetime.utcnow(), note
    db.commit()
    if approve:
        _tell_member(db, member, "Excused month approved",
                     f"Approved by {_by(db, actor_id)}: nothing is owed for {_label([e.month])}.")
    else:
        _tell_member(db, member, "Excused month not approved",
                     f"Your request for {_label([e.month])} was not approved by {_by(db, actor_id)}: {note}")
    return {"status": e.status}


def waiting_requests(db: Session) -> list[dict]:
    """Every waiting request, oldest first, with the member's code and name (admins)."""
    rows = (db.query(ExcusedMonth, Member).join(Member, Member.id == ExcusedMonth.member_id)
            .filter(ExcusedMonth.status == REQUESTED).order_by(ExcusedMonth.created_at, ExcusedMonth.month).all())
    names = _names(db, [e.requested_by_user_id for e, _ in rows])
    return [{**_excused_json(e, names), "member_code": m.member_code, "member_name": m.full_name} for e, m in rows]


# ---------------------------------------------------------------- pledges
def set_pledge(db: Session, member: Member, year: int, amount: float, note: Optional[str], actor_id: int) -> dict:
    """Create or change the pledge for one year (Jan-Dec). Commits."""
    if not is_monthly(member):
        raise HTTPException(status_code=400, detail="This member is not a monthly member.")
    current = fy_of(current_month_business())
    year = int(year)
    if not 2024 <= year <= current + 1:
        raise HTTPException(status_code=400, detail=f"Choose a year from 2024 to {fy_label(current + 1)}.")
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Enter the pledged amount.")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="The pledged amount must be more than 0.")
    p = db.query(MemberPledge).filter(MemberPledge.member_id == member.id, MemberPledge.year == year).first()
    if p is None:
        p = MemberPledge(member_id=member.id, year=year)
        db.add(p)
    p.amount, p.note, p.created_by_user_id = amount, _clean(note), actor_id
    # In a pledge year months are not owed one by one: the 'not paid yet' rows go.
    _remove_unpaid_rows(db, member.id, fy_months(year))
    db.commit()
    return {"year": year, "label": fy_label(year), "amount": amount}


def remove_pledge(db: Session, member: Member, pledge_id: int) -> None:
    p = db.query(MemberPledge).filter(MemberPledge.id == pledge_id, MemberPledge.member_id == member.id).first()
    if p is None:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(p)
    db.commit()


# ---------------------------------------------------------------- monthly member
def set_monthly_member(db: Session, member: Member, monthly: bool, actor_id: int) -> dict:
    """Turn monthly membership off (no monthly fee owed, fee 0, 'not paid yet' rows removed) or on.
    Turning it on again: set the fee in the member form (it starts next month). Commits."""
    from app.services.challan_state import unpaid_monthly_clause

    removed = 0
    if not monthly:
        rows = db.query(Challan).filter(Challan.member_id == member.id, unpaid_monthly_clause()).all()
        for c in rows:
            db.delete(c)
        removed = len(rows)
        member.monthly_amount = 0
        from app.models.models import MemberFee
        # A fee change still waiting would otherwise switch the fee back on next month.
        db.query(MemberFee).filter(MemberFee.member_id == member.id,
                                   MemberFee.effective_from > current_month_business()).delete()
    member.monthly_member = bool(monthly)
    db.commit()
    return {"monthly_member": bool(monthly), "removed_unpaid_rows": removed}


# ---------------------------------------------------------------- notifications
def _label(months: list[str]) -> str:
    return ", ".join(datetime.strptime(m, "%Y-%m").strftime("%b %Y") for m in sorted(months))


def _tell_member(db: Session, member: Member, title: str, message: str) -> None:
    from app.services.notification_service import NotificationService

    if member.user_id:
        NotificationService._send_status_notification(db, member.user_id, title, message, "info",
                                                      category="requests", link_url="/MyStatement")


def _tell_admins(db: Session, member: Member, months: list[str], reason: str) -> None:
    from app.services.notification_service import NotificationService

    try:
        admin_ids = NotificationService._active_admin_ids(db, exclude_user_id=member.user_id)
    except Exception:
        return
    who = f"{member.full_name or member.member_code} ({member.member_code})"
    for admin_id in admin_ids:
        NotificationService._send_status_notification(
            db, admin_id, "Excused months requested", f"{who} asks to be excused for {_label(months)}: {reason}",
            "info", category="admin_requests", link_url=f"/Members?member={member.id}&tab=seasonal",
        )
