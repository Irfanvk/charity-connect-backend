from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.member_activation_service import MemberActivationService
from app.utils import get_current_admin

router = APIRouter(prefix="/member-activations", tags=["Member activation"])


class MemberActivationCreate(BaseModel):
    member_code: str = Field(..., min_length=1, max_length=50)
    full_name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=1, max_length=20)
    email: Optional[str] = Field(default=None, max_length=255)
    no_email: bool = False
    whatsapp_phone: Optional[str] = Field(default=None, max_length=20)
    username: str = Field(..., min_length=1, max_length=30)
    password: str = Field(..., min_length=1, max_length=128)
    last_paid_month: Optional[str] = Field(default=None, max_length=7)


class MemberActivationApprove(BaseModel):
    admin_notes: Optional[str] = Field(default=None, max_length=1000)


class MemberActivationReject(BaseModel):
    rejection_reason: str = Field(..., min_length=1, max_length=1000)
    admin_notes: Optional[str] = Field(default=None, max_length=1000)


@router.get("/availability")
def availability(db: Session = Depends(get_db)):
    """Public: whether the login page should offer self-activation."""
    return {"enabled": MemberActivationService.is_enabled(db)}


@router.post("", status_code=201)
def submit_activation(payload: MemberActivationCreate, request: Request, db: Session = Depends(get_db)):
    """Public: an existing member asks to activate their account."""
    source_ip = request.client.host if request.client else None
    return MemberActivationService.submit(db, payload, source_ip=source_ip)


@router.get("")
def list_activations(
    status: Optional[str] = Query(default="pending"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return MemberActivationService.list(db, status, skip, limit)


@router.get("/{activation_id}")
def get_activation(activation_id: int, current_admin: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    return MemberActivationService.get(db, activation_id)


@router.post("/{activation_id}/approve")
def approve_activation(
    activation_id: int,
    payload: MemberActivationApprove | None = None,
    current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return MemberActivationService.approve(db, current_admin, activation_id, payload.admin_notes if payload else None)


@router.post("/{activation_id}/reject")
def reject_activation(
    activation_id: int,
    payload: MemberActivationReject,
    current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return MemberActivationService.reject(
        db, current_admin, activation_id, payload.rejection_reason, payload.admin_notes,
    )
