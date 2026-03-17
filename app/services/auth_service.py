from sqlalchemy.orm import Session
from app.models import User, Member, Invite
from app.schemas import UserRegisterWithInvite, UserLogin
from app.utils import hash_password, verify_password, generate_member_code
from fastapi import HTTPException, status
from datetime import datetime, timedelta


class AuthService:
    """Authentication and user management service."""

    _failed_login_attempts: dict[str, dict] = {}
    _max_attempts = 5
    _window_minutes = 15
    _lockout_minutes = 15

    @staticmethod
    def _normalize_phone(phone: str | None) -> str | None:
        if phone is None:
            return None
        cleaned = "".join(str(phone).split())
        return cleaned or None

    @staticmethod
    def _normalize_email(email: str | None) -> str | None:
        if email is None:
            return None
        cleaned = str(email).strip().lower()
        return cleaned or None

    @staticmethod
    def _build_rate_limit_keys(identifier: str, source_ip: str | None = None) -> list[str]:
        keys = [f"id:{identifier.lower()}".strip()]
        if source_ip:
            keys.append(f"ip:{source_ip}".strip())
        return keys

    @staticmethod
    def _assert_not_rate_limited(keys: list[str]):
        now = datetime.utcnow()
        for key in keys:
            entry = AuthService._failed_login_attempts.get(key)
            if not entry:
                continue
            blocked_until = entry.get("blocked_until")
            if blocked_until and blocked_until > now:
                remaining = max(int((blocked_until - now).total_seconds() // 60), 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many failed login attempts. Try again in {remaining} minute(s).",
                )

    @staticmethod
    def _register_failed_attempt(keys: list[str]):
        now = datetime.utcnow()
        window_start = now - timedelta(minutes=AuthService._window_minutes)

        for key in keys:
            entry = AuthService._failed_login_attempts.get(key)
            if not entry or entry.get("first_attempt_at") < window_start:
                AuthService._failed_login_attempts[key] = {
                    "count": 1,
                    "first_attempt_at": now,
                    "blocked_until": None,
                }
                continue

            entry["count"] = int(entry.get("count", 0)) + 1
            if entry["count"] >= AuthService._max_attempts:
                entry["blocked_until"] = now + timedelta(minutes=AuthService._lockout_minutes)

    @staticmethod
    def _reset_failed_attempts(keys: list[str]):
        for key in keys:
            AuthService._failed_login_attempts.pop(key, None)
    
    @staticmethod
    def login(db: Session, user_login: UserLogin, source_ip: str | None = None):
        """Authenticate user with username OR email (single field)."""
        # Get the identifier (could be username or email)
        identifier = (user_login.username or user_login.email or "").strip()
        
        if identifier == "":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username or email required",
            )

        rate_limit_keys = AuthService._build_rate_limit_keys(identifier, source_ip)
        AuthService._assert_not_rate_limited(rate_limit_keys)
        
        # Try to find user by username first, then by email
        user = db.query(User).filter(User.username == identifier).first()
        if not user:
            user = db.query(User).filter(User.email == identifier).first()
        
        if not user or not verify_password(user_login.password, user.password_hash):
            AuthService._register_failed_attempt(rate_limit_keys)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username/email or password",
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )

        AuthService._reset_failed_attempts(rate_limit_keys)
        
        return user
    
    @staticmethod
    def register_with_invite(db: Session, registration: UserRegisterWithInvite):
        """Register new user with valid invite code."""
        normalized_registration_email = AuthService._normalize_email(registration.email)
        normalized_registration_phone = AuthService._normalize_phone(registration.phone)
        
        # Validate invite code
        invite = db.query(Invite).filter(
            Invite.invite_code == registration.invite_code
        ).first()

        normalized_invite_email = AuthService._normalize_email(invite.email) if invite else None
        normalized_invite_phone = AuthService._normalize_phone(invite.phone) if invite else None
        
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
        if invite.email and normalized_registration_email != normalized_invite_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match invite",
            )
        
        if invite.phone and normalized_registration_phone != normalized_invite_phone:
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
        if normalized_registration_email:
            existing_email_user = db.query(User).filter(User.email == normalized_registration_email).first()
            if existing_email_user:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already taken",
                )
        
        # Create user
        new_user = User(
            username=registration.username,
            email=normalized_registration_email,
            phone=normalized_registration_phone,
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

        possible_emails = [
            value
            for value in [
                AuthService._normalize_email(invite.email),
                AuthService._normalize_email(registration.email),
            ]
            if value
        ]
        possible_phones = [
            value
            for value in [
                AuthService._normalize_phone(invite.phone),
                AuthService._normalize_phone(registration.phone),
            ]
            if value
        ]

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
            email_owner = db.query(User).filter(
                User.email == AuthService._normalize_email(registration.email),
                User.id != user.id,
            ).first()
            if email_owner:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already taken",
                )

        if registration.phone:
            phone_owner = db.query(User).filter(
                User.phone == AuthService._normalize_phone(registration.phone),
                User.id != user.id,
            ).first()
            if phone_owner:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Phone already taken",
                )

        user.username = registration.username
        if registration.email:
            user.email = AuthService._normalize_email(registration.email)
        if registration.phone:
            user.phone = AuthService._normalize_phone(registration.phone)
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
