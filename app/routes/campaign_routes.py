from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import CampaignCreate, CampaignResponse, CampaignUpdate, CampaignPaymentImportSummary
from app.services import CampaignService
from app.utils import get_current_user, get_current_admin, get_current_superadmin
from typing import List

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


@router.post("/import/payments", response_model=CampaignPaymentImportSummary, status_code=status.HTTP_201_CREATED)
async def import_campaign_payments(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_superadmin),
    db: Session = Depends(get_db),
):
    """
    Import campaign payment history from CSV/XLSX (Superadmin only).

    Supported columns include:
    - username/member_code/si_no (member match)
    - amount
    - status
    - payment_method
    - suggested_campaign_name/campaign_name
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    return CampaignService.import_campaign_payments_file(
        db=db,
        file_bytes=content,
        filename=file.filename or "campaign_payments.csv",
        imported_by_user_id=current_user.get("user_id"),
    )


@router.post("/", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
def create_campaign(
    campaign_data: CampaignCreate,
    current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Create new campaign (Admin only).
    """
    try:
        campaign = CampaignService.create_campaign(db, campaign_data, current_admin["user_id"])
        return campaign
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create campaign")


@router.get("/", response_model=List[CampaignResponse])
def get_all_campaigns(
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=1, le=500, description="Maximum number of records to return"),
    active_only: bool = False,
    _: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get all campaigns. Supports pagination via skip/limit.
    """
    try:
        campaigns = CampaignService.get_all_campaigns(db, skip, limit, active_only)
        return campaigns
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch campaigns")


@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(
    campaign_id: int,
    _: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get campaign details by ID.
    """
    campaign = CampaignService.get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Campaign {campaign_id} not found")
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignResponse)
@router.put("/{campaign_id}", response_model=CampaignResponse)
def update_campaign(
    campaign_id: int,
    update_data: CampaignUpdate,
    _: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Update a campaign (Admin only).
    
    Supports both PUT and PATCH methods for compatibility.
    PATCH is canonical for partial updates, but PUT is also accepted.
    """
    campaign = CampaignService.get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Campaign {campaign_id} not found")
    try:
        updated = CampaignService.update_campaign(db, campaign_id, update_data)
        return updated
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update campaign")


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    campaign_id: int,
    _: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Delete a campaign (Admin only).
    """
    campaign = CampaignService.get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Campaign {campaign_id} not found")
    try:
        CampaignService.delete_campaign(db, campaign_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete campaign")