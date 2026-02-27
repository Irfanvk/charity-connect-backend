from fastapi import HTTPException
from app.models.models import ChallanStatus
from fastapi import APIRouter, Depends, status, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import ChallanCreate, ChallanResponse, ChallanApprove, ChallanReject
from app.services import ChallanService, MemberService
from app.utils import get_current_user, get_current_admin
from typing import List, Optional

router = APIRouter(prefix="/challans", tags=["Challans"])


# ------------------------------------------------------------------
# CREATE CHALLAN (MEMBER)
# ------------------------------------------------------------------
@router.post("/", response_model=ChallanResponse, status_code=status.HTTP_201_CREATED)
def create_challan(
    challan_data: ChallanCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new challan (member creates for themselves).
    """
    member = MemberService.get_member_for_user(db, current_user["user_id"])

    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    return ChallanService.create_challan(db, member.id, challan_data)


# ------------------------------------------------------------------
# UPLOAD PAYMENT PROOF (MEMBER – OWN CHALLAN ONLY)
# ------------------------------------------------------------------
@router.post("/{challan_id}/upload-proof", response_model=ChallanResponse)
def upload_proof(
    challan_id: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload payment proof for a challan (owner only).
    """
    challan = ChallanService.get_challan(db, challan_id)
    member = MemberService.get_member_for_user(db, current_user["user_id"])

    if challan.member_id != member.id:
        raise HTTPException(status_code=403, detail="Not authorized to upload proof")

    # File validation
    allowed_types = ["image/jpeg", "image/png", "application/pdf"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type")

    content = file.file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")

    return ChallanService.upload_proof(db, challan_id, content, file.filename)


# ------------------------------------------------------------------
# GET ALL CHALLANS (ADMIN ONLY)
# ------------------------------------------------------------------
@router.get("/", response_model=List[ChallanResponse])
def get_all_challans(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[ChallanStatus] = None,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Get all challans (admin only).
    """
    return ChallanService.get_all_challans(
        db, skip, limit, status_filter=status_filter
    )


# ------------------------------------------------------------------
# GET MEMBER CHALLANS (ADMIN OR SELF)
# ------------------------------------------------------------------
@router.get("/member/{member_id}", response_model=List[ChallanResponse])
def get_member_challans(
    member_id: int,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get challans for a member (admin or self).
    """
    member = MemberService.get_member_for_user(db, current_user["user_id"])

    if not current_user.get("is_admin") and member.id != member_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return ChallanService.get_member_challans(db, member_id, skip, limit)


# ------------------------------------------------------------------
# GET SINGLE CHALLAN (ADMIN OR OWNER)
# ------------------------------------------------------------------
@router.get("/{challan_id}", response_model=ChallanResponse)
def get_challan(
    challan_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get challan details (admin or owner).
    """
    challan = ChallanService.get_challan(db, challan_id)

    if not current_user.get("is_admin"):
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if challan.member_id != member.id:
            raise HTTPException(status_code=403, detail="Access denied")

    return challan


# ------------------------------------------------------------------
# APPROVE CHALLAN (ADMIN ONLY)
# ------------------------------------------------------------------
@router.patch("/{challan_id}/approve", response_model=ChallanResponse)
def approve_challan(
    challan_id: int,
    approve_data: ChallanApprove,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    challan = ChallanService.get_challan(db, challan_id)

    if challan.status != ChallanStatus.PENDING.value:
        raise HTTPException(
            status_code=400,
            detail="Challan already processed"
        )

    return ChallanService.approve_challan(db, challan_id, approve_data)


# ------------------------------------------------------------------
# REJECT CHALLAN (ADMIN ONLY)
# ------------------------------------------------------------------
@router.patch("/{challan_id}/reject", response_model=ChallanResponse)
def reject_challan(
    challan_id: int,
    reject_data: ChallanReject,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    challan = ChallanService.get_challan(db, challan_id)

    if challan.status != ChallanStatus.PENDING.value:
        raise HTTPException(
            status_code=400,
            detail="Challan already processed"
        )

    return ChallanService.reject_challan(db, challan_id, reject_data)