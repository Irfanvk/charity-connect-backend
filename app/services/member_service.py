from sqlalchemy.orm import Session
from app.models import Member, User
from app.schemas import MemberUpdate, MemberCreate
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
    def create_member(db: Session, member_data: MemberCreate):
        """Create member profile (admin only)."""
        existing_user = db.query(User).filter(User.id == member_data.user_id).first()
        if not existing_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        existing_member = db.query(Member).filter(Member.user_id == member_data.user_id).first()
        if existing_member:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Member profile already exists for this user",
            )

        duplicate_code = db.query(Member).filter(Member.member_code == member_data.member_code).first()
        if duplicate_code:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Member code already in use",
            )

        member = Member(
            user_id=member_data.user_id,
            member_code=member_data.member_code,
            monthly_amount=member_data.monthly_amount,
            address=member_data.address,
            status="active",
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        return member
    
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
    def delete_member(db: Session, member_id: int):
        """Delete a member profile (admin only)."""
        member = MemberService.get_member(db, member_id)
        db.delete(member)
        db.commit()
        return None
    
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
