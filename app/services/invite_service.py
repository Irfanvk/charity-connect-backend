from sqlalchemy.orm import Session, joinedload
from sqlalchemy import asc, desc
from app.models import Invite, User
from app.schemas import InviteCreate, InviteValidate
from app.schemas.schemas import InviteUpdate
from app.utils import generate_invite_code
from fastapi import HTTPException, status
from datetime import datetime, timezone


class InviteService:
    """Invite management service."""

    @staticmethod
    def _to_utc_naive(dt: datetime) -> datetime:
        """Convert datetime to UTC-naive for consistent DB comparisons/storage."""
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    
    @staticmethod
    def _enrich_invite(invite: Invite) -> Invite:
        """Add computed fields to invite object."""
        # Add invited_by from created_by relationship
        if hasattr(invite, 'created_by') and invite.created_by:
            invite.invited_by = invite.created_by.email or invite.created_by.username
        else:
            invite.invited_by = None
        
        # Add status based on is_used
        invite.status = "used" if invite.is_used else "pending"
        
        return invite
    
    @staticmethod
    def create_invite(db: Session, invite_data: InviteCreate, admin_id: int):
        """Create new invite code."""
        
        # Verify admin exists
        admin = db.query(User).filter(User.id == admin_id).first()
        if not admin:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Admin not found",
            )
        
        # Generate unique invite code
        while True:
            invite_code = generate_invite_code()
            existing = db.query(Invite).filter(Invite.invite_code == invite_code).first()
            if not existing:
                break

        expiry_date = invite_data.expiry_date or invite_data.expires_at
        if expiry_date is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="expiry_date or expires_at is required",
            )

        expiry_date = InviteService._to_utc_naive(expiry_date)

        if expiry_date < datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Expiry date must be in the future",
            )
        
        new_invite = Invite(
            invite_code=invite_code,
            email=invite_data.email or None,
            phone=invite_data.phone,
            expiry_date=expiry_date,
            created_by_admin_id=admin_id,
        )
        
        db.add(new_invite)
        db.commit()
        db.refresh(new_invite)
        
        # Reload with relationship to get invited_by
        invite_with_relation = db.query(Invite).options(joinedload(Invite.created_by)).filter(Invite.id == new_invite.id).first()
        return InviteService._enrich_invite(invite_with_relation)
    
    @staticmethod
    def validate_invite(db: Session, validate_data: InviteValidate):
        """Validate if invite code matches email or phone."""
        
        invite = db.query(Invite).filter(
            Invite.invite_code == validate_data.invite_code
        ).first()
        
        if not invite:
            return {"valid": False, "message": "Invite code not found"}
        
        if invite.is_used:
            return {"valid": False, "message": "Invite code already used"}
        
        invite_expiry = InviteService._to_utc_naive(invite.expiry_date)
        if invite_expiry < datetime.utcnow():
            return {"valid": False, "message": "Invite code expired"}
        
        # Check if email or phone matches
        if invite.email and invite.email.lower() == validate_data.email_or_phone.lower():
            return {"valid": True, "message": "Invite valid for email", "type": "email"}
        
        if invite.phone and invite.phone == validate_data.email_or_phone:
            return {"valid": True, "message": "Invite valid for phone", "type": "phone"}
        
        return {"valid": False, "message": "Email or phone does not match"}
    
    @staticmethod
    def get_pending_invites(db: Session):
        """Get all pending (unused) invite codes."""
        invites = db.query(Invite).options(joinedload(Invite.created_by)).filter(Invite.is_used == False).all()
        return [InviteService._enrich_invite(invite) for invite in invites]

    @staticmethod
    def get_all_invites(
        db: Session,
        skip: int = 0,
        limit: int = 100,
        is_used: bool = None,
        email: str = None,
        phone: str = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        """Get all invites with filtering/sorting/pagination."""
        query = db.query(Invite).options(joinedload(Invite.created_by))

        if is_used is not None:
            query = query.filter(Invite.is_used == is_used)
        if email:
            query = query.filter(Invite.email.ilike(f"%{email}%"))
        if phone:
            query = query.filter(Invite.phone.ilike(f"%{phone}%"))

        sort_columns = {
            "created_at": Invite.created_at,
            "expiry_date": Invite.expiry_date,
            "invite_code": Invite.invite_code,
        }
        column = sort_columns.get(sort_by, Invite.created_at)
        query = query.order_by(desc(column) if sort_order.lower() == "desc" else asc(column))

        invites = query.offset(skip).limit(limit).all()
        return [InviteService._enrich_invite(invite) for invite in invites]

    @staticmethod
    def get_invite_by_id(db: Session, invite_id: int):
        """Get invite by ID."""
        invite = db.query(Invite).options(joinedload(Invite.created_by)).filter(Invite.id == invite_id).first()
        if not invite:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invite not found",
            )
        return InviteService._enrich_invite(invite)

    @staticmethod
    def update_invite(db: Session, invite_id: int, update_data: InviteUpdate):
        """Update invite metadata."""
        invite = InviteService.get_invite_by_id(db, invite_id)

        expiry_date = update_data.expiry_date or update_data.expires_at
        if expiry_date is not None:
            expiry_date = InviteService._to_utc_naive(expiry_date)
            if expiry_date < datetime.utcnow():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Expiry date must be in the future",
                )
            invite.expiry_date = expiry_date

        if update_data.email is not None:
            invite.email = update_data.email or None
        if update_data.phone is not None:
            invite.phone = update_data.phone

        db.commit()
        db.refresh(invite)
        
        # Reload with relationship to get invited_by
        invite_with_relation = db.query(Invite).options(joinedload(Invite.created_by)).filter(Invite.id == invite.id).first()
        return InviteService._enrich_invite(invite_with_relation)
    
    @staticmethod
    def delete_invite(db: Session, invite_id: int):
        """Delete an invite code."""
        invite = db.query(Invite).filter(Invite.id == invite_id).first()
        
        if not invite:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invite not found",
            )
        
        if invite.is_used:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete used invite",
            )
        
        db.delete(invite)
        db.commit()
        
        return {"message": "Invite deleted"}
