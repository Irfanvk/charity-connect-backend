"""New members who joined by invite wait for an admin to approve them, with the monthly fee they chose.

Until then ``Member.fee_confirmed`` is False: they cannot log in ("waiting for the committee to
approve your account") and admins see them in a list with Approve / Change fee / Decline. Confirming with a different amount
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
WAITING_MESSAGE = ("Your account is waiting for the committee to approve it. "
                   "Please try again later; the committee will approve it soon.")


def awaiting_approval(db: Session, user_id: int) -> bool:
    """A new member who joined by invite and is not approved yet (cannot log in)."""
    row = db.query(Member.fee_confirmed).filter(Member.user_id == user_id).first()
    return row is not None and row[0] is False


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
                   f"₹{float(member.monthly_amount or 0):,.0f} a month. They can log in once you approve them "
                   "(you can change the fee or decline).")
        for admin_id in NotificationService._active_admin_ids(db):
            NotificationService._send_status_notification(
                db, admin_id, "Approve a new member", message, "info",
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
        text = (f"Welcome! The committee approved your membership. Your monthly fee of ₹{new:,.0f} is confirmed."
                if not changed else
                f"Welcome! The committee approved your membership. Your monthly fee is set to ₹{new:,.0f} "
                f"(you chose ₹{old:,.0f}). Reason: {note}")
        NotificationService._send_status_notification(
            db, user.id, "Membership approved", text, "success",
            category="requests", link_url="/MyStatement", entity_type="member", entity_id=member.id,
        )
    return {"member_id": member.id, "monthly_amount": new, "changed": changed, "unpaid_rows_updated": updated_rows}


def decline(db: Session, member: Member, reason: Optional[str], actor_id: int) -> dict:
    """Refuse a new member who joined by invite and is not approved yet: their account and member
    record are removed (nothing financial exists yet). With any payment record it is refused:
    approve them, or make them inactive. Commits."""
    from app.services.challan_state import submitted_clause
    from app.models.models import BulkChallanGroup, MemberFee, Notification

    if member.fee_confirmed:
        raise HTTPException(status_code=409, detail="This member is already approved.")
    reason = " ".join(str(reason or "").split())[:300]
    if not reason:
        raise HTTPException(status_code=400, detail="Please give a reason.")
    has_payments = (db.query(Challan).filter(Challan.member_id == member.id, submitted_clause()).count()
                    + db.query(BulkChallanGroup).filter(BulkChallanGroup.member_id == member.id).count())
    if has_payments:
        raise HTTPException(status_code=400, detail=(
            "This member already has payment records, which must stay on record. "
            "Approve them, or make them inactive."))
    snapshot = {"member_code": member.member_code, "full_name": member.full_name,
                "monthly_amount": float(member.monthly_amount or 0), "reason": reason}
    user = db.query(User).filter(User.id == member.user_id).first() if member.user_id else None
    db.query(Challan).filter(Challan.member_id == member.id).delete(synchronize_session=False)
    db.query(MemberFee).filter(MemberFee.member_id == member.id).delete(synchronize_session=False)
    db.delete(member)
    if user is not None:
        db.query(Notification).filter(Notification.user_id == user.id).delete(synchronize_session=False)
        from app.models import Invite

        for inv in db.query(Invite).filter(Invite.used_by_user_id == user.id).all():
            inv.used_by_user_id = None  # the invite stays used; it just no longer points at the account
        db.delete(user)
    db.commit()
    return snapshot
