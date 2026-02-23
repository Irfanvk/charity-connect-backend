from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import InviteCreate, InviteResponse
from app.services import InviteService
from app.utils import get_current_admin
from typing import List

router = APIRouter(prefix="/invites", tags=["Invites"])


@router.post("/", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def create_invite(
    invite_data: InviteCreate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Create new invite code (Admin only).
    """
    invite = InviteService.create_invite(db, invite_data, current_user["user_id"])
    return invite


@router.get("/pending", response_model=List[InviteResponse])
def get_pending_invites(
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Get all pending invite codes (Admin only).
    """
    invites = InviteService.get_pending_invites(db)
    return invites


@router.post("/validate")
def validate_invite(email_or_phone: str, invite_code: str, db: Session = Depends(get_db)):
    """
    Validate if invite code is valid and matches email/phone.
    """
    from app.schemas import InviteValidate
    validate_data = InviteValidate(invite_code=invite_code, email_or_phone=email_or_phone)
    return InviteService.validate_invite(db, validate_data)


@router.delete("/{invite_id}")
def delete_invite(
    invite_id: int,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Delete invite code (Admin only).
    """
    return InviteService.delete_invite(db, invite_id)
