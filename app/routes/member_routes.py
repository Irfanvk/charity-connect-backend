from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import MemberResponse, MemberUpdate
from app.services import MemberService
from app.utils import get_current_user, get_current_admin
from typing import List

router = APIRouter(prefix="/members", tags=["Members"])


@router.get("/", response_model=List[MemberResponse])
def get_all_members(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Get all members (Admin only).
    """
    members = MemberService.get_all_members(db, skip, limit)
    return members


@router.get("/me", response_model=MemberResponse)
def get_my_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get current user's member profile.
    """
    member = MemberService.get_member_for_user(db, current_user["user_id"])
    return member


@router.get("/code/{member_code}", response_model=MemberResponse)
def get_member_by_code(
    member_code: str,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Get member details by member code (Admin only).
    """
    member = MemberService.get_member_by_code(db, member_code)
    return member


@router.get("/{member_id}", response_model=MemberResponse)
def get_member(
    member_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = MemberService.get_member(db, member_id)

    # Allow only admin OR owner
    if not current_user.get("is_admin") and member.user_id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You are not allowed to access this profile"
        )

    return member


@router.put("/{member_id}", response_model=MemberResponse)
def update_member(
    member_id: int,
    update_data: MemberUpdate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Update member information (Admin only).
    """
    member = MemberService.update_member(db, member_id, update_data)
    return member
