from sqlalchemy.orm import Session
from app.models import Challan, Member
from app.models.models import ChallanStatus, ChallanType
from app.schemas import ChallanCreate, ChallanApprove, ChallanReject
from app.utils.file_handler import save_file, validate_file
from fastapi import HTTPException, status
from datetime import datetime


class ChallanService:
    """Challan management service."""
    
    @staticmethod
    def create_challan(db: Session, member_id: int, challan_data: ChallanCreate):
        """Create new challan."""
        
        # Verify member exists
        member = db.query(Member).filter(Member.id == member_id).first()
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found",
            )
        
        # Validate challan data
        if challan_data.type == ChallanType.MONTHLY and not challan_data.month:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Month required for monthly challans",
            )
        
        if challan_data.type == ChallanType.CAMPAIGN and not challan_data.campaign_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Campaign ID required for campaign challans",
            )
        
        # Check if monthly challan already exists for this month
        if challan_data.type == ChallanType.MONTHLY:
            existing = db.query(Challan).filter(
                Challan.member_id == member_id,
                Challan.type == ChallanType.MONTHLY,
                Challan.month == challan_data.month,
                Challan.status.in_([ChallanStatus.GENERATED, ChallanStatus.PENDING]),
            ).first()
            
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Challan already exists for this month",
                )
        
        new_challan = Challan(
            member_id=member_id,
            type=challan_data.type,
            month=challan_data.month,
            campaign_id=challan_data.campaign_id,
            amount=challan_data.amount,
            payment_method=challan_data.payment_method,
        )
        
        db.add(new_challan)
        db.commit()
        db.refresh(new_challan)
        
        return new_challan
    
    @staticmethod
    def upload_proof(db: Session, challan_id: int, file_content: bytes, filename: str):
        """Upload payment proof for challan."""
        
        challan = db.query(Challan).filter(Challan.id == challan_id).first()
        if not challan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Challan not found",
            )
        
        if challan.status not in [ChallanStatus.GENERATED, ChallanStatus.PENDING]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot upload proof for this challan status",
            )
        
        # Validate file
        validate_file(file_content, filename)
        
        # Save file
        proof_path = save_file(file_content, "proofs", filename)
        
        # Update challan
        challan.proof_path = proof_path
        challan.proof_uploaded_at = datetime.utcnow()
        challan.status = ChallanStatus.PENDING
        
        db.commit()
        db.refresh(challan)
        
        return challan
    
    @staticmethod
    def approve_challan(db: Session, challan_id: int, approve_data: ChallanApprove):
        """Approve challan."""
        
        challan = db.query(Challan).filter(Challan.id == challan_id).first()
        if not challan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Challan not found",
            )
        
        if challan.status != ChallanStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only pending challans can be approved",
            )
        
        challan.status = ChallanStatus.APPROVED
        challan.approved_by_admin_id = approve_data.approved_by_admin_id
        challan.approved_at = datetime.utcnow()
        
        db.commit()
        db.refresh(challan)
        
        return challan
    
    @staticmethod
    def reject_challan(db: Session, challan_id: int, reject_data: ChallanReject):
        """Reject challan."""
        
        challan = db.query(Challan).filter(Challan.id == challan_id).first()
        if not challan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Challan not found",
            )
        
        if challan.status != ChallanStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only pending challans can be rejected",
            )
        
        challan.status = ChallanStatus.REJECTED
        challan.rejection_reason = reject_data.rejection_reason
        
        db.commit()
        db.refresh(challan)
        
        return challan
    
    @staticmethod
    def get_challan(db: Session, challan_id: int):
        """Get challan by ID."""
        challan = db.query(Challan).filter(Challan.id == challan_id).first()
        
        if not challan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Challan not found",
            )
        
        return challan
    
    @staticmethod
    def get_member_challans(db: Session, member_id: int, skip: int = 0, limit: int = 100):
        """Get all challans for a member."""
        return db.query(Challan).filter(
            Challan.member_id == member_id
        ).offset(skip).limit(limit).all()
    
    @staticmethod
    def get_all_challans(db: Session, skip: int = 0, limit: int = 100, status_filter: str = None):
        """Get all challans with optional filtering."""
        query = db.query(Challan)
        
        if status_filter:
            query = query.filter(Challan.status == status_filter)
        
        return query.offset(skip).limit(limit).all()
