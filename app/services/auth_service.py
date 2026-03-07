from sqlalchemy.orm import Session
from app.models import User, Member, Invite
from app.schemas import UserRegisterWithInvite, UserLogin
from app.utils import hash_password, verify_password, generate_member_code
from fastapi import HTTPException, status
from datetime import datetime


class AuthService:
    """Authentication and user management service."""
    
    @staticmethod
    def login(db: Session, user_login: UserLogin):
        """Authenticate user with username OR email (single field)."""
        # Get the identifier (could be username or email)
        identifier = user_login.username or user_login.email
        
        if not identifier:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username or email required",
            )
        
        # Try to find user by username first, then by email
        user = db.query(User).filter(User.username == identifier).first()
        if not user:
            user = db.query(User).filter(User.email == identifier).first()
        
        if not user or not verify_password(user_login.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username/email or password",
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )
        
        return user
    
    @staticmethod
    def register_with_invite(db: Session, registration: UserRegisterWithInvite):
        """Register new user with valid invite code."""
        
        # Validate invite code
        invite = db.query(Invite).filter(
            Invite.invite_code == registration.invite_code
        ).first()
        
        if not invite:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invite code",
            )
        
        if invite.is_used:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invite code already used",
            )
        
        if invite.expiry_date < datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invite code expired",
            )
        
        # Validate invite matches email or phone
        if invite.email and registration.email != invite.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match invite",
            )
        
        if invite.phone and registration.phone != invite.phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone does not match invite",
            )
        
        # Check username doesn't exist
        existing_user = db.query(User).filter(User.username == registration.username).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            )

        # Check email doesn't exist (if provided)
        if registration.email:
            existing_email_user = db.query(User).filter(User.email == registration.email).first()
            if existing_email_user:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already taken",
                )
        
        # Create user
        new_user = User(
            username=registration.username,
            email=registration.email,
            phone=registration.phone,
            password_hash=hash_password(registration.password),
            role="member",
        )
        
        db.add(new_user)
        db.flush()
        
        # Get last member code to generate next sequential code
        last_member = db.query(Member).order_by(Member.id.desc()).first()
        last_code = last_member.member_code if last_member else None
        next_member_code = generate_member_code(last_code)
        
        # Create member
        new_member = Member(
            user_id=new_user.id,
            member_code=next_member_code,
            monthly_amount=registration.monthly_amount or 0.0,
            address=registration.address,
        )
        
        db.add(new_member)
        
        # Mark invite as used
        invite.is_used = True
        invite.used_by_user_id = new_user.id
        
        db.commit()
        db.refresh(new_user)
        
        return new_user
    
    @staticmethod
    def get_user(db: Session, user_id: int):
        """Get user by ID."""
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        
        return user
    
    @staticmethod
    def get_current_user(db: Session, user_id: int):
        """Get current authenticated user details."""
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        return user
