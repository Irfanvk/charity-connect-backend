"""Admins confirm (or change) the monthly fee a new member chose when joining by invite."""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import MemberService, fee_confirm
from app.utils import get_current_admin, log_audit

router = APIRouter(tags=["New members' fees"])


class ConfirmFeeIn(BaseModel):
    monthly_amount: Optional[float] = Field(default=None, ge=0, le=1_000_000)  # empty: keep what they chose
    note: Optional[str] = Field(default=None, max_length=300)


@router.get("/members/fees-to-confirm")
def fees_to_confirm(_admin: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """New members whose chosen fee waits for an admin, oldest first."""
    return fee_confirm.waiting(db)


@router.post("/members/{member_id}/confirm-fee")
def confirm_fee(member_id: int, body: ConfirmFeeIn, admin: dict = Depends(get_current_admin),
                db: Session = Depends(get_db)):
    member = MemberService.get_member(db, member_id)
    chosen = float(member.monthly_amount or 0)
    out = fee_confirm.confirm(db, member, body.monthly_amount, body.note, admin.get("user_id"))
    log_audit(db, user_id=admin.get("user_id"), action="member_fee_confirmed", entity_type="Member",
              entity_id=member.id, old_values={"monthly_amount": chosen, "fee_confirmed": False},
              new_values={"member_code": member.member_code, **out, "note": body.note}, auto_commit=True)
    return out
