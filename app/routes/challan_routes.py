from fastapi import APIRouter, Depends, status, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import ChallanCreate, ChallanResponse, ChallanApprove, ChallanReject
from app.services import ChallanService, MemberService
from app.utils import get_current_user, get_current_admin
from typing import List

router = APIRouter(prefix="/challans", tags=["Challans"])


@router.post("/", response_model=ChallanResponse, status_code=status.HTTP_201_CREATED)
def create_challan(
    challan_data: ChallanCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create new challan (Member creates for themselves).
    """
    # Get member associated with current user
    member = MemberService.get_member_for_user(db, current_user["user_id"])
    
    challan = ChallanService.create_challan(db, member.id, challan_data)
    return challan


@router.post("/{challan_id}/upload-proof", response_model=ChallanResponse)
async def upload_proof(
    challan_id: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload payment proof for challan.
    """
    # Read file
    content = await file.read()
    
    challan = ChallanService.upload_proof(db, challan_id, content, file.filename)
    return challan


@router.get("/", response_model=List[ChallanResponse])
def get_all_challans(
    skip: int = 0,
    limit: int = 100,
    status_filter: str = None,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Get all challans (Admin only).
    """
    challans = ChallanService.get_all_challans(db, skip, limit, status_filter=status_filter)
    return challans


@router.get("/member/{member_id}", response_model=List[ChallanResponse])
def get_member_challans(
    member_id: int,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get challans for specific member.
    """
    challans = ChallanService.get_member_challans(db, member_id, skip, limit)
    return challans


@router.get("/{challan_id}", response_model=ChallanResponse)
def get_challan(
    challan_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get challan details.
    """
    challan = ChallanService.get_challan(db, challan_id)
    return challan


@router.put("/{challan_id}/approve", response_model=ChallanResponse)
def approve_challan(
    challan_id: int,
    approve_data: ChallanApprove,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Approve pending challan (Admin only).
    """
    challan = ChallanService.approve_challan(db, challan_id, approve_data)
    return challan


@router.put("/{challan_id}/reject", response_model=ChallanResponse)
def reject_challan(
    challan_id: int,
    reject_data: ChallanReject,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Reject pending challan (Admin only).
    """
    challan = ChallanService.reject_challan(db, challan_id, reject_data)
    return challan
