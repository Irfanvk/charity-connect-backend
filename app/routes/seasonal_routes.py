"""Excused months, yearly pledges and monthly membership (see app/services/seasonal.py)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import ExcusedMonth, Member
from app.services import MemberService, seasonal
from app.utils import get_current_admin, get_current_staff, get_current_user, log_audit

router = APIRouter(tags=["Excused months and pledges"])


class ExcuseIn(BaseModel):
    months: List[str] = Field(min_length=1, max_length=12)
    reason: str = Field(min_length=1, max_length=300)


class DecideIn(BaseModel):
    approve: bool
    note: Optional[str] = Field(default=None, max_length=300)


class PledgeIn(BaseModel):
    year: int
    amount: float
    note: Optional[str] = Field(default=None, max_length=300)


class MonthlyMemberIn(BaseModel):
    monthly_member: bool


def _my_member(db: Session, user: dict) -> Member:
    member = db.query(Member).filter(Member.user_id == user.get("user_id")).first()
    if member is None:
        raise HTTPException(status_code=404, detail="There is no member record for your account.")
    return member


def _audit(db: Session, user: dict, action: str, member: Member, values: dict) -> None:
    log_audit(db, user_id=user.get("user_id"), action=action, entity_type="Member", entity_id=member.id,
              new_values={"member_code": member.member_code, **values}, auto_commit=True)


# ------------------------------------------------------------- the member's own
@router.get("/members/me/seasonal")
def my_seasonal(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """My excused months (and requests) and pledges."""
    return seasonal.overview(db, _my_member(db, current_user))


@router.post("/members/me/excused-requests", status_code=status.HTTP_201_CREATED)
def request_excused(body: ExcuseIn, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Ask the committee to excuse some months (e.g. no work). An admin approves or rejects."""
    return seasonal.request_months(db, current_user.get("user_id"), body.months, body.reason)


@router.delete("/members/me/excused-requests/{excused_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_excused_request(excused_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Withdraw my own request while it is still waiting."""
    member = _my_member(db, current_user)
    e = db.query(ExcusedMonth).filter(ExcusedMonth.id == excused_id, ExcusedMonth.member_id == member.id).first()
    if e is None or e.status != seasonal.REQUESTED:
        raise HTTPException(status_code=404, detail="Only a waiting request can be withdrawn.")
    db.delete(e)
    db.commit()


# ------------------------------------------------------------- admins
@router.get("/excused/requests")
def excused_requests(_admin: dict = Depends(get_current_staff), db: Session = Depends(get_db)):
    """Every waiting excuse request, oldest first."""
    return seasonal.waiting_requests(db)


@router.get("/members/{member_id}/seasonal")
def member_seasonal(member_id: int, _admin: dict = Depends(get_current_staff), db: Session = Depends(get_db)):
    return seasonal.overview(db, MemberService.get_member(db, member_id))


@router.post("/members/{member_id}/excused", status_code=status.HTTP_201_CREATED)
def excuse(member_id: int, body: ExcuseIn, admin: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    member = MemberService.get_member(db, member_id)
    out = seasonal.excuse_months(db, member, body.months, body.reason, admin.get("user_id"))
    _audit(db, admin, "excused_months_added", member, {"months": out["excused"], "reason": body.reason})
    return out


@router.post("/members/{member_id}/excused/{excused_id}/decide")
def decide(member_id: int, excused_id: int, body: DecideIn, admin: dict = Depends(get_current_admin),
           db: Session = Depends(get_db)):
    member = MemberService.get_member(db, member_id)
    out = seasonal.decide_request(db, member, excused_id, body.approve, body.note, admin.get("user_id"))
    _audit(db, admin, "excused_request_" + ("approved" if body.approve else "rejected"), member,
           {"excused_id": excused_id, "note": body.note})
    return out


@router.delete("/members/{member_id}/excused/{excused_id}", status_code=status.HTTP_204_NO_CONTENT)
def unexcuse(member_id: int, excused_id: int, admin: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    member = MemberService.get_member(db, member_id)
    e = db.query(ExcusedMonth).filter(ExcusedMonth.id == excused_id, ExcusedMonth.member_id == member.id).first()
    month = e.month if e else None
    seasonal.remove_excused(db, member, excused_id)
    _audit(db, admin, "excused_month_removed", member, {"month": month})


@router.put("/members/{member_id}/pledges")
def set_pledge(member_id: int, body: PledgeIn, admin: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    member = MemberService.get_member(db, member_id)
    out = seasonal.set_pledge(db, member, body.year, body.amount, body.note, admin.get("user_id"))
    _audit(db, admin, "pledge_set", member, {"year": out["label"], "amount": out["amount"], "note": body.note})
    return out


@router.delete("/members/{member_id}/pledges/{pledge_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_pledge(member_id: int, pledge_id: int, admin: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    member = MemberService.get_member(db, member_id)
    seasonal.remove_pledge(db, member, pledge_id)
    _audit(db, admin, "pledge_removed", member, {"pledge_id": pledge_id})


@router.put("/members/{member_id}/monthly-member")
def set_monthly_member(member_id: int, body: MonthlyMemberIn, admin: dict = Depends(get_current_admin),
                       db: Session = Depends(get_db)):
    """Off: not a monthly member (no monthly fee owed; fee set to 0; 'not paid yet' rows removed).
    On: set the fee in the member form afterwards (it starts next month)."""
    member = MemberService.get_member(db, member_id)
    before = {"monthly_member": seasonal.is_monthly(member), "monthly_amount": float(member.monthly_amount or 0)}
    out = seasonal.set_monthly_member(db, member, body.monthly_member, admin.get("user_id"))
    log_audit(db, user_id=admin.get("user_id"), action="monthly_member_changed", entity_type="Member",
              entity_id=member.id, old_values=before, new_values={"member_code": member.member_code, **out},
              auto_commit=True)
    return out
