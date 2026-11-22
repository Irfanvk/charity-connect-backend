"""New members who joined by invite choose their own monthly fee; an admin confirms or changes it.

Until then ``Member.fee_confirmed`` is False: the member sees "waiting for the committee" and
admins see the member in a list with Confirm / Change. Confirming with a different amount
sets the fee from the member's first month (it is their starting fee, not a later change) and
updates any "not paid yet" monthly rows; payments already handed in keep their amount.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Challan, ChallanType, Member, MemberFee, User
from app.services.challan_state import unpaid_monthly_clause
from app.services.settings_service import get_setting

LINK = "/Members?member={id}&tab=fee"


def min_fee(db: Session) -> float:
    return float(get_setting(db, "min_monthly_fee") or 0)


def check_new_member_fee(db: Session, amount) -> float:
    """The fee a new member typed when joining: at least the minimum (Settings)."""
    lowest = min_fee(db)
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0
    if value < max(lowest, 1):
        raise HTTPException(status_code=400,
                            detail=f"Please enter your monthly payment: at least ₹{max(lowest, 1):,.0f}.")
    if value > 1_000_000:
        raise HTTPException(status_code=400, detail="Please check the monthly payment amount.")
    return round(value, 2)


def tell_admins_new_fee(db: Session, member: Member) -> None:
    """One task notification per active admin: confirm the fee this new member chose."""
    from app.services.notification_service import NotificationService

    try:
        message = (f"New member {member.member_code} ({member.full_name or 'no name'}) joined by invite and chose "
                   f"₹{float(member.monthly_amount or 0):,.0f} a month. Please confirm or change it.")
        for admin_id in NotificationService._active_admin_ids(db):
            NotificationService._send_status_notification(
                db, admin_id, "Confirm a new member's fee", message, "info",
                category="admin_requests", link_url=LINK.format(id=member.id),
                entity_type="member", entity_id=member.id,
            )
    except Exception:  # never block the sign-up
        pass


def waiting(db: Session) -> list[dict]:
    """Members whose chosen fee waits for an admin, oldest first."""
    rows = (db.query(Member).filter(Member.fee_confirmed.is_(False))
            .order_by(Member.join_date.asc(), Member.id.asc()).all())
    return [{
        "member_id": m.id, "member_code": m.member_code, "full_name": m.full_name,
        "monthly_amount": float(m.monthly_amount or 0),
        "joined": m.join_date.isoformat() if m.join_date else None,
    } for m in rows]


def confirm(db: Session, member: Member, amount: Optional[float], note: Optional[str], actor_id: int) -> dict:
    """Confirm the member's chosen fee, or set another one from their first month. Commits."""
    from app.services import fee_history
    from app.services.notification_service import NotificationService

    if member.fee_confirmed:
        raise HTTPException(status_code=409, detail="This member's fee is already confirmed.")
    old = float(member.monthly_amount or 0)
    new = old if amount is None else float(amount)
    if new < 0:
        raise HTTPException(status_code=400, detail="The fee cannot be below 0.")
    note = " ".join(str(note or "").split())[:300] or None
    changed = abs(new - old) >= 0.005
    if changed and not note:
        raise HTTPException(status_code=400, detail="Please say why the fee is different (it is shown to the member).")

    updated_rows = 0
    if changed:
        member.monthly_amount = new
        # Their starting fee: one history row from their first month, replacing what they typed.
        db.query(MemberFee).filter(MemberFee.member_id == member.id).delete(synchronize_session=False)
        db.add(MemberFee(member_id=member.id, amount=new, effective_from=fee_history.start_month(member),
                         source="confirmed", changed_by_user_id=actor_id, note=note))
        for c in (db.query(Challan).filter(Challan.member_id == member.id, Challan.type == ChallanType.MONTHLY,
                                           unpaid_monthly_clause()).all()):
            c.amount = new
            updated_rows += 1
    member.fee_confirmed = True
    db.commit()

    user = db.query(User).filter(User.id == member.user_id).first() if member.user_id else None
    if user is not None:
        text = (f"Your monthly fee of ₹{new:,.0f} is confirmed by the committee." if not changed else
                f"Your monthly fee is set to ₹{new:,.0f} by the committee (you chose ₹{old:,.0f}). Reason: {note}")
        NotificationService._send_status_notification(
            db, user.id, "Monthly fee confirmed", text, "success",
            category="requests", link_url="/MyStatement", entity_type="member", entity_id=member.id,
        )
    return {"member_id": member.id, "monthly_amount": new, "changed": changed, "unpaid_rows_updated": updated_rows}
