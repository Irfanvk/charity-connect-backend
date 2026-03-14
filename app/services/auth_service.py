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

        # If this person already exists as an offline-imported member account,
        # claim and activate that same user to preserve a single member history.
        claimable_user = AuthService._find_claimable_member_user(db, invite, registration)
        if claimable_user:
            AuthService._claim_existing_member_user(db, claimable_user, invite, registration)
            db.refresh(claimable_user)
            return claimable_user
        
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
    def _find_claimable_member_user(db: Session, invite: Invite, registration: UserRegisterWithInvite):
        candidates: list[User] = []

        possible_emails = [value for value in [invite.email, registration.email] if value]
        possible_phones = [value for value in [invite.phone, registration.phone] if value]

        for email in possible_emails:
            user = db.query(User).filter(User.email == email).first()
            if user and user not in candidates:
                candidates.append(user)

        for phone in possible_phones:
            user = db.query(User).filter(User.phone == phone).first()
            if user and user not in candidates:
                candidates.append(user)

        for user in candidates:
            # Only claim member-linked accounts that are currently offline/inactive.
            if user.role == "member" and user.member is not None and not user.is_active:
                return user

        return None

    @staticmethod
    def _claim_existing_member_user(
        db: Session,
        user: User,
        invite: Invite,
        registration: UserRegisterWithInvite,
    ):
        username_owner = db.query(User).filter(User.username == registration.username, User.id != user.id).first()
        if username_owner:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            )

        if registration.email:
            email_owner = db.query(User).filter(User.email == registration.email, User.id != user.id).first()
            if email_owner:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already taken",
                )

        if registration.phone:
            phone_owner = db.query(User).filter(User.phone == registration.phone, User.id != user.id).first()
            if phone_owner:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Phone already taken",
                )

        user.username = registration.username
        if registration.email:
            user.email = registration.email
        if registration.phone:
            user.phone = registration.phone
        user.password_hash = hash_password(registration.password)
        user.is_active = True

        # Keep invite tracking accurate.
        invite.is_used = True
        invite.used_by_user_id = user.id

        db.commit()
    
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
