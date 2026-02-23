from sqlalchemy.orm import Session
from app.models import Member
from app.schemas import MemberUpdate
from fastapi import HTTPException, status


class MemberService:
    """Member management service."""
    
    @staticmethod
    def get_member(db: Session, member_id: int):
        """Get member by ID."""
        member = db.query(Member).filter(Member.id == member_id).first()
        
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found",
            )
        
        return member
    
    @staticmethod
    def get_member_by_code(db: Session, member_code: str):
        """Get member by member code."""
        member = db.query(Member).filter(Member.member_code == member_code).first()
        
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found",
            )
        
        return member
    
    @staticmethod
    def get_all_members(db: Session, skip: int = 0, limit: int = 100):
        """Get all members with pagination."""
        return db.query(Member).offset(skip).limit(limit).all()
    
    @staticmethod
    def update_member(db: Session, member_id: int, update_data: MemberUpdate):
        """Update member information."""
        member = MemberService.get_member(db, member_id)
        
        update_fields = update_data.dict(exclude_unset=True)
        for key, value in update_fields.items():
            if value is not None:
                setattr(member, key, value)
        
        db.commit()
        db.refresh(member)
        
        return member
    
    @staticmethod
    def get_member_for_user(db: Session, user_id: int):
        """Get member associated with user."""
        member = db.query(Member).filter(Member.user_id == user_id).first()
        
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member profile not found for this user",
            )
        
        return member
