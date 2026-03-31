from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import InviteCreate, InviteResponse, InviteUpdate
from app.services import InviteService
from app.utils import get_current_admin, log_audit
from typing import List, Optional

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
    log_audit(
        db,
        user_id=current_user["user_id"],
        action="invite_create",
        entity_type="Invite",
        entity_id=invite.id,
        new_values={"invite_code": invite.invite_code, "phone": invite_data.phone, "email": invite_data.email},
        auto_commit=True,
    )
    return invite


@router.get("/", response_model=List[InviteResponse])
def get_all_invites(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    is_used: Optional[bool] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Get all invites with filtering, sorting and pagination (Admin only).
    """
    return InviteService.get_all_invites(
        db,
        skip=skip,
        limit=limit,
        is_used=is_used,
        email=email,
        phone=phone,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/pending", response_model=List[InviteResponse])
def get_pending_invites(
    _current_user: dict = Depends(get_current_admin),
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
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Delete invite code (Admin only).
    """
    result = InviteService.delete_invite(db, invite_id)
    log_audit(
        db,
        user_id=_current_user.get("user_id"),
        action="invite_delete",
        entity_type="Invite",
        entity_id=invite_id,
        auto_commit=True,
    )
    return result


@router.get("/{invite_id}", response_model=InviteResponse)
def get_invite(
    invite_id: int,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Get invite details by ID (Admin only).
    """
    return InviteService.get_invite_by_id(db, invite_id)


@router.put("/{invite_id}", response_model=InviteResponse)
def update_invite(
    invite_id: int,
    update_data: InviteUpdate,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Update invite details (Admin only).
    """
    result = InviteService.update_invite(db, invite_id, update_data)
    log_audit(
        db,
        user_id=_current_user.get("user_id"),
        action="invite_update",
        entity_type="Invite",
        entity_id=invite_id,
        new_values=update_data.dict(exclude_unset=True),
        auto_commit=True,
    )
    return result
