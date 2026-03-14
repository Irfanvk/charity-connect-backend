from fastapi import APIRouter, Depends, status, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import MemberResponse, MemberUpdate, MemberCreate, MemberImportSummary
from app.services import MemberService
from app.utils import get_current_user, get_current_admin, get_current_superadmin
from typing import List

router = APIRouter(prefix="/members", tags=["Members"])


def _is_admin(current_user: dict) -> bool:
    return current_user.get("role") in ["admin", "superadmin"]


@router.get("/", response_model=List[MemberResponse])
def get_members(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="full_name"),
    sort_order: str = Query(default="asc"),
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
        return MemberService.get_all_members(
    db=db,
    skip=skip,
    limit=limit,
    search=search,
    sort_by=sort_by,
    sort_order=sort_order
)
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
    _ = current_user
    member = MemberService.get_member_by_code(db, member_code)
    return member


@router.post("/", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
def create_member(
    payload: MemberCreate,
    _current_user: dict = Depends(get_current_superadmin),
    db: Session = Depends(get_db),
):
    """Create member profile (Superadmin only)."""
    return MemberService.create_member(db, payload)


@router.post("/import", response_model=MemberImportSummary, status_code=status.HTTP_201_CREATED)
async def import_members(
    file: UploadFile = File(...),
    include_donations: bool = Query(default=True),
    current_user: dict = Depends(get_current_superadmin),
    db: Session = Depends(get_db),
):
    """
    Import members from CSV/XLSX (Superadmin only).

        Supported member columns:
        - member_code/member_id/code/si_no, full_name/name/member_name, username,
            phone/mobile, email, address/location/notes, monthly_amount, join_date/join_year, status

    Optional donation columns (when include_donations=true):
        - type, month/donation_month/payment_month/period,
            amount/donation_amount/paid_amount, payment_method, donation_status,
            suggested_campaign_name
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    return MemberService.import_members_file(
        db=db,
        file_bytes=content,
        filename=file.filename or "import.csv",
        include_donations=include_donations,
        imported_by_user_id=current_user.get("user_id"),
    )


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
    _ = current_user
    member = MemberService.update_member(db, member_id, update_data)
    return member


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_member(
    member_id: int,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Delete member profile (Admin only)."""
    MemberService.delete_member(db, member_id)
