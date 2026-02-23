from sqlalchemy.orm import Session
from app.models import Invite, User
from app.schemas import InviteCreate, InviteValidate
from app.utils import generate_invite_code
from fastapi import HTTPException, status
from datetime import datetime


class InviteService:
    """Invite management service."""
    
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
        
        new_invite = Invite(
            invite_code=invite_code,
            email=invite_data.email,
            phone=invite_data.phone,
            expiry_date=invite_data.expiry_date,
            created_by_admin_id=admin_id,
        )
        
        db.add(new_invite)
        db.commit()
        db.refresh(new_invite)
        
        return new_invite
    
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
        
        if invite.expiry_date < datetime.utcnow():
            return {"valid": False, "message": "Invite code expired"}
        
        # Check if email or phone matches
        if invite.email and invite.email.lower() == validate_data.invite_code.lower():
            return {"valid": True, "message": "Invite valid for email", "type": "email"}
        
        if invite.phone and invite.phone == validate_data.invite_code:
            return {"valid": True, "message": "Invite valid for phone", "type": "phone"}
        
        return {"valid": False, "message": "Email or phone does not match"}
    
    @staticmethod
    def get_pending_invites(db: Session):
        """Get all pending (unused) invite codes."""
        return db.query(Invite).filter(Invite.is_used == False).all()
    
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
