from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import CampaignCreate, CampaignResponse, CampaignUpdate
from app.services import CampaignService
from app.utils import get_current_user, get_current_admin
from typing import List

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


@router.post("/", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
def create_campaign(
    campaign_data: CampaignCreate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Create new campaign (Admin only).
    """
    campaign = CampaignService.create_campaign(db, campaign_data, current_user["user_id"])
    return campaign


@router.get("/", response_model=List[CampaignResponse])
def get_all_campaigns(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = False,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get all campaigns.
    """
    campaigns = CampaignService.get_all_campaigns(db, skip, limit, active_only)
    return campaigns


@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(
    campaign_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get campaign details.
    """
    campaign = CampaignService.get_campaign(db, campaign_id)
    return campaign


@router.put("/{campaign_id}", response_model=CampaignResponse)
def update_campaign(
    campaign_id: int,
    update_data: CampaignUpdate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Update campaign (Admin only).
    """
    campaign = CampaignService.update_campaign(db, campaign_id, update_data)
    return campaign


@router.delete("/{campaign_id}")
def delete_campaign(
    campaign_id: int,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Delete campaign (Admin only).
    """
    return CampaignService.delete_campaign(db, campaign_id)
