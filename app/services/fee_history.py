"""Monthly fee history: what a member's fee was in any month.

Rules (agreed with the committee):
- Everyone starts with their current fee for every month (no guessing from old payments).
- A fee change always applies from NEXT month (India time). This month and earlier keep the
  fee that applied then; next month and later take the new fee.
- members.monthly_amount is always the fee of the current month: it changes by itself when
  the new month begins (apply_due_changes, run by the daily scheduler and on startup).
- The first change of a member writes two entries: the old fee from the member's start month
  (join month, not before Aug 2024), and the new fee from next month. Changing it again in the
  same month replaces the waiting change (back to today's fee cancels it).

Lookup: the fee for month M is the latest entry with effective_from <= M (ties: the entry
saved last). Before the first entry, the first entry's fee. No entries: members.monthly_amount.
Reports load all entries once (``FeeBook``) instead of asking per month.
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.models.models import Member, MemberFee
from app.utils.timezone import current_month_business, to_business

PLATFORM_START_MONTH = "2024-08"


def start_month(member: Member) -> str:
    if member.join_date:
        month = to_business(member.join_date).strftime("%Y-%m") if hasattr(member.join_date, "hour") \
            else member.join_date.strftime("%Y-%m")
        return max(month, PLATFORM_START_MONTH)
    return PLATFORM_START_MONTH


class FeeBook:
    """Fee timelines for many members, loaded in one query."""

    def __init__(self, db: Session, members: Iterable[Member]):
        self._members = {m.id: m for m in members}
        self._lines: dict[int, tuple[list[str], list[float]]] = {}
        ids = list(self._members)
        if ids:
            rows = (
                db.query(MemberFee.member_id, MemberFee.effective_from, MemberFee.amount)
                .filter(MemberFee.member_id.in_(ids))
                .order_by(MemberFee.member_id, MemberFee.effective_from, MemberFee.id)
                .all()
            )
            grouped: dict[int, list[tuple[str, float]]] = {}
            for mid, eff, amount in rows:
                line = grouped.setdefault(mid, [])
                if line and line[-1][0] == eff:
                    line[-1] = (eff, float(amount))  # same month changed twice: the later one counts
                else:
                    line.append((eff, float(amount)))
            for mid, line in grouped.items():
                self._lines[mid] = ([e for e, _ in line], [a for _, a in line])

    def fee(self, member_or_id, month: Optional[str]) -> float:
        member = member_or_id if isinstance(member_or_id, Member) else self._members.get(member_or_id)
        mid = member.id if member is not None else member_or_id
        current = float(member.monthly_amount or 0) if member is not None else 0.0
        line = self._lines.get(mid)
        if not line or not month:
            return current
        months, amounts = line
        i = bisect_right(months, month) - 1
        return amounts[max(i, 0)]

    def varies(self, member_id: int, first: str, last: str) -> bool:
        """Did the fee change between these months (inclusive)?"""
        line = self._lines.get(member_id)
        if not line:
            return False
        return any(first < eff <= last for eff in line[0])


def fee_for(db: Session, member: Member, month: Optional[str]) -> float:
    return FeeBook(db, [member]).fee(member, month)


def history(db: Session, member: Member) -> list[dict]:
    rows = (
        db.query(MemberFee).filter(MemberFee.member_id == member.id)
        .order_by(MemberFee.effective_from, MemberFee.id).all()
    )
    if not rows:
        return [{"amount": float(member.monthly_amount or 0), "effective_from": start_month(member),
                 "source": "start", "changed_by": None, "note": None, "created_at": None}]
    from app.utils.admin_codes import actor_labels

    labels = actor_labels(db, [r.changed_by_user_id for r in rows])

    out = []
    for r in rows:
        if out and out[-1]["effective_from"] == r.effective_from:
            out.pop()  # changed twice in one month: only the last one applies
        out.append({
            "amount": float(r.amount), "effective_from": r.effective_from, "source": r.source,
            "changed_by": labels.get(r.changed_by_user_id),
            "note": r.note, "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
        })
    return out


def next_month(month: str) -> str:
    year, mon = (int(x) for x in month.split("-"))
    return f"{year + 1}-01" if mon == 12 else f"{year}-{mon + 1:02d}"


def record_change(db: Session, member: Member, old_amount, new_amount, *, actor_id: Optional[int] = None,
                  source: str = "admin", note: Optional[str] = None) -> bool:
    """Save a fee change that starts NEXT month. Call after the new amount was put on the
    member; members.monthly_amount is set back to this month's fee. No commit."""
    old = float(old_amount or 0)
    new = float(new_amount or 0)
    member.monthly_amount = old  # this month keeps its fee; apply_due_changes switches it next month
    starts = next_month(current_month_business())
    if abs(fee_for(db, member, starts) - new) < 0.005:
        return False  # already the fee from next month
    if not db.query(MemberFee.id).filter(MemberFee.member_id == member.id).first():
        if abs(old - new) < 0.005:
            return False
        db.add(MemberFee(member_id=member.id, amount=old, effective_from=start_month(member), source="start"))
    db.add(MemberFee(member_id=member.id, amount=new, effective_from=starts, source=source,
                     changed_by_user_id=actor_id, note=(note or "").strip()[:300] or None))
    db.flush()
    return True


def upcoming(db: Session, member: Member) -> Optional[dict]:
    """A change waiting to start (next month), if any: {amount, effective_from}."""
    month = current_month_business()
    book = FeeBook(db, [member])
    nxt = next_month(month)
    if abs(book.fee(member, nxt) - book.fee(member, month)) < 0.005 or not book.varies(member.id, month, nxt):
        return None
    return {"amount": book.fee(member, nxt), "effective_from": nxt}


def apply_due_changes(db: Session) -> int:
    """Make members.monthly_amount the fee of the current month for everyone with a fee history
    (a change that was waiting for this month starts now). Re-prices their unpaid months. Commits."""
    from app.services.challan_state import sync_unpaid_monthly_amounts

    month = current_month_business()
    ids = [mid for (mid,) in db.query(MemberFee.member_id).distinct().all()]
    if not ids:
        return 0
    members = db.query(Member).filter(Member.id.in_(ids)).all()
    book = FeeBook(db, members)
    changed = 0
    for member in members:
        fee = book.fee(member, month)
        if fee > 0 and abs(float(member.monthly_amount or 0) - fee) > 0.005:
            member.monthly_amount = fee
            sync_unpaid_monthly_amounts(db, member)
            changed += 1
    if changed:
        db.commit()
    return changed


def run_for_now() -> int:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return apply_due_changes(db)
    finally:
        db.close()
