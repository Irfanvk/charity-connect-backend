from sqlalchemy.orm import Session
from app.models import Campaign
from app.schemas import CampaignCreate, CampaignUpdate
from fastapi import HTTPException, status


class CampaignService:
    """Campaign management service."""
    
    @staticmethod
    def create_campaign(db: Session, campaign_data: CampaignCreate, admin_id: int):
        """Create new campaign."""
        
        new_campaign = Campaign(
            title=campaign_data.title,
            description=campaign_data.description,
            target_amount=campaign_data.target_amount,
            start_date=campaign_data.start_date,
            end_date=campaign_data.end_date,
            created_by_admin_id=admin_id,
        )
        
        db.add(new_campaign)
        db.commit()
        db.refresh(new_campaign)
        
        return new_campaign
    
    @staticmethod
    def get_campaign(db: Session, campaign_id: int):
        """Get campaign by ID."""
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        
        if not campaign:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found",
            )
        
        return campaign
    
    @staticmethod
    def get_all_campaigns(db: Session, skip: int = 0, limit: int = 100, active_only: bool = False):
        """Get all campaigns with optional filtering."""
        query = db.query(Campaign)
        
        if active_only:
            query = query.filter(Campaign.is_active == True)
        
        return query.offset(skip).limit(limit).all()
    
    @staticmethod
    def update_campaign(db: Session, campaign_id: int, update_data: CampaignUpdate):
        """Update campaign information."""
        campaign = CampaignService.get_campaign(db, campaign_id)
        
        update_fields = update_data.dict(exclude_unset=True)
        for key, value in update_fields.items():
            if value is not None:
                setattr(campaign, key, value)
        
        db.commit()
        db.refresh(campaign)
        
        return campaign
    
    @staticmethod
    def delete_campaign(db: Session, campaign_id: int):
        """Delete campaign."""
        campaign = CampaignService.get_campaign(db, campaign_id)
        
        db.delete(campaign)
        db.commit()
        
        return {"message": "Campaign deleted"}
