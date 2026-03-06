from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import MemberResponse, MemberUpdate
from app.services import MemberService
from app.utils import get_current_user, get_current_admin
from typing import List

router = APIRouter(prefix="/members", tags=["Members"])


def _is_admin(current_user: dict) -> bool:
    return current_user.get("role") in ["admin", "superadmin"]


@router.get("/", response_model=List[MemberResponse])
def get_members(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get members:
    - Admin: all members
    - Member: only their own profile (as list)
    """
    if _is_admin(current_user):
        # Admin gets all members
        return MemberService.get_all_members(db, skip, limit)
    else:
        # Member gets only their own profile (returned as list)
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if not member:
            raise HTTPException(status_code=404, detail="Member profile not found")
        return [member]


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
    if not _is_admin(current_user) and member.user_id != current_user["user_id"]:
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
