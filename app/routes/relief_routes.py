"""Relief fund claims (see app/services/relief_service.py)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import relief_service
from app.utils.auth import get_current_user

router = APIRouter(prefix="/relief", tags=["Relief fund"])


class ReliefDocument(BaseModel):
    kind: str
    url: str
    name: Optional[str] = None


class ReliefClaimCreate(BaseModel):
    member_id: int
    reason: str
    illness_type: Optional[str] = None
    details: Optional[str] = None
    amount: Optional[float] = Field(default=None, ge=0)
    receiver_name: str
    receiver_relation: Optional[str] = None
    receiver_phone: Optional[str] = None
    receiver_bank_account: Optional[str] = None
    receiver_ifsc: Optional[str] = None
    receiver_bank_name: Optional[str] = None
    receiver_upi: Optional[str] = None
    gulf_from_year: Optional[int] = None
    gulf_to_year: Optional[int] = None
    documents: List[ReliefDocument] = []


class ReliefDecision(BaseModel):
    note: Optional[str] = None


class ReliefReason(BaseModel):
    reason: str


class ReliefPaid(BaseModel):
    paid_on: str
    method: str
    reference: Optional[str] = None
    receipt_url: Optional[str] = None


@router.get("/me")
def my_relief(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Any signed-in member: the scheme numbers, their own rule checks and claims made for them."""
    return relief_service.my_relief(db, current_user)


@router.get("/eligibility/{member_id}")
def member_eligibility(
    member_id: int,
    reason: Optional[str] = None,
    gulf_from_year: Optional[int] = None,
    gulf_to_year: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admins: the rule checks for a member before creating a claim."""
    return relief_service.member_eligibility(db, current_user, member_id, reason, gulf_from_year, gulf_to_year)


@router.get("/claims")
def list_claims(
    status: Optional[str] = Query(default=None, description="pending | approved | rejected | paid | cancelled | to_decide"),
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return relief_service.list_claims(db, current_user, status, search)


@router.post("/claims", status_code=201)
def create_claim(payload: ReliefClaimCreate, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["documents"] = [d.model_dump() for d in payload.documents]
    return relief_service.create_claim(db, current_user, data)


@router.get("/claims/{claim_id}")
def get_claim(claim_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return relief_service.get_claim(db, current_user, claim_id)


@router.post("/claims/{claim_id}/approve")
def approve_claim(claim_id: int, payload: ReliefDecision = ReliefDecision(),
                  current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return relief_service.approve(db, current_user, claim_id, payload.note)


@router.post("/claims/{claim_id}/reject")
def reject_claim(claim_id: int, payload: ReliefReason, current_user: dict = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    return relief_service.reject(db, current_user, claim_id, payload.reason)


@router.post("/claims/{claim_id}/paid")
def mark_claim_paid(claim_id: int, payload: ReliefPaid, current_user: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    return relief_service.mark_paid(db, current_user, claim_id, payload.model_dump())


@router.post("/claims/{claim_id}/cancel")
def cancel_claim(claim_id: int, payload: ReliefReason, current_user: dict = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    return relief_service.cancel(db, current_user, claim_id, payload.reason)
