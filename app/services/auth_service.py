from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import User, Member, Invite
from app.schemas import UserRegisterWithInvite, UserLogin
from app.utils import hash_password, verify_password, generate_member_code
from app.utils.message_format import with_islamic_greeting
from fastapi import HTTPException, status
from datetime import datetime, timedelta
from app.services.settings_service import get_setting, welcome_content
from app.utils.phones import find_users_by_phone, last_digits, phone_digits, phones_match

WELCOME_MESSAGE = with_islamic_greeting(
    "Your account is ready. Complete your profile and begin your charity journey."
)


class AuthService:
    """Authentication and user management service."""

    _failed_login_attempts: dict[str, dict] = {}
    _max_attempts = 10
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
    def _normalize_username(username: str | None) -> str | None:
        if username is None:
            return None
        cleaned = str(username).strip().lower()
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
    def _register_failed_attempt(keys: list[str], max_attempts: int | None = None, lockout_minutes: int | None = None):
        # Note: this counter is in-memory per process (existing behaviour).
        max_attempts = max_attempts or AuthService._max_attempts
        lockout_minutes = lockout_minutes or AuthService._lockout_minutes
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
            if entry["count"] >= max_attempts:
                entry["blocked_until"] = now + timedelta(minutes=lockout_minutes)

    @staticmethod
    def _reset_failed_attempts(keys: list[str]):
        for key in keys:
            AuthService._failed_login_attempts.pop(key, None)
    
    @staticmethod
    def login(db: Session, user_login: UserLogin, source_ip: str | None = None):
        """Authenticate user with username OR email (single field)."""
        # Get the identifier (could be username or email)
        identifier = (user_login.username or user_login.email or "").strip()
        normalized_identifier = identifier.lower()
        
        if identifier == "":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username or email required",
            )

        rate_limit_keys = AuthService._build_rate_limit_keys(normalized_identifier, source_ip)
        AuthService._assert_not_rate_limited(rate_limit_keys)
        
        # Try to find user by username first (case-insensitive), then by email
        user = db.query(User).filter(func.lower(User.username) == normalized_identifier).first()
        if not user:
            user = db.query(User).filter(func.lower(User.email) == normalized_identifier).first()
        
        if not user or not verify_password(user_login.password, user.password_hash):
            # The credentials may belong to a self-activation request that has
            # no account yet: tell the applicant where their request stands.
            from app.services.member_activation_service import MemberActivationService
            activation_status = MemberActivationService.status_for_login(db, identifier, user_login.password)
            if activation_status:
                AuthService._reset_failed_attempts(rate_limit_keys)
                # Fits the API's error shape: detail[0].type / .msg / .input
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
                    "type": activation_status["code"],
                    "msg": activation_status["message"],
                    "input": activation_status,
                })
            AuthService._register_failed_attempt(
                rate_limit_keys,
                get_setting(db, "login_max_failed_attempts"),
                get_setting(db, "login_lockout_minutes"),
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username/email or password",
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )

        from app.services import fee_confirm

        if str(getattr(user.role, "value", user.role)).lower() == "member" and fee_confirm.awaiting_approval(db, user.id):
            AuthService._reset_failed_attempts(rate_limit_keys)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=fee_confirm.WAITING_MESSAGE)

        AuthService._reset_failed_attempts(rate_limit_keys)
        
        return user
    
    @staticmethod
    def register_with_invite(db: Session, registration: UserRegisterWithInvite):
        """Register new user with valid invite code."""
        from app.services import fee_confirm
        normalized_username = AuthService._normalize_username(registration.username)
        if not normalized_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username is required",
            )

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
        
        # The sign-up form no longer asks for contacts the invite already has: a blank email or
        # mobile means the one on the invite.
        typed_email, typed_phone = normalized_registration_email, normalized_registration_phone
        normalized_registration_email = normalized_registration_email or normalized_invite_email
        normalized_registration_phone = normalized_registration_phone or normalized_invite_phone
        registration.email = normalized_registration_email
        registration.phone = normalized_registration_phone

        # Validate invite matches email or phone (a mobile written another way is the same mobile)
        if invite.email and normalized_registration_email != normalized_invite_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match invite",
            )

        if invite.phone and not phones_match(normalized_registration_phone, normalized_invite_phone):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone does not match invite",
            )

        # Existing-member invite registrations should keep monthly amount immutable.
        existing_member_user = AuthService._find_existing_member_user_by_contacts(db, invite, registration)
        if existing_member_user and (registration.monthly_amount or 0.0) > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Membership amount for existing members cannot be changed during registration. "
                    "Please submit a profile request after login for admin approval."
                ),
            )
        if existing_member_user and existing_member_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("This member already has an account. Please log in, or use Forgot password "
                        "if you don't remember it."),
            )
        if existing_member_user:
            # Checked against what they typed, not the invite's contacts filled in above.
            AuthService._check_it_is_them(existing_member_user, registration, typed_email, typed_phone)

        # If this person already exists as an offline-imported member account,
        # claim and activate that same user to preserve a single member history.
        claimable_user = existing_member_user
        if claimable_user:
            AuthService._claim_existing_member_user(db, claimable_user, invite, registration)
            db.refresh(claimable_user)
            return claimable_user
        
        # Check username doesn't exist
        existing_user = db.query(User).filter(User.username == normalized_username).first()
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
            username=normalized_username,
            email=normalized_registration_email,
            phone=normalized_registration_phone,
            password_hash=hash_password(registration.password),
            role="member",
            full_name=registration.full_name or normalized_username,
        )
        
        db.add(new_user)
        db.flush()
        
        # Get last member code to generate next sequential code
        from app.utils.member_codes import next_member_code as _next_code

        next_member_code = _next_code(db)
        
        # Create member
        new_member = Member(
            user_id=new_user.id,
            member_code=next_member_code,
            monthly_amount=fee_confirm.check_new_member_fee(db, registration.monthly_amount),
            fee_confirmed=False,  # an admin confirms or changes the fee they chose
            address=registration.address,
            country=registration.country,
            city=registration.city,
            full_name=registration.full_name or normalized_username,
        )
        
        db.add(new_member)
        
        # Mark invite as used
        invite.is_used = True
        invite.used_by_user_id = new_user.id
        
        db.commit()
        db.refresh(new_user)

        from app.services.notification_service import NotificationService

        fee_confirm.tell_admins_new_fee(db, new_member)
        welcome_title, welcome_message = welcome_content(db, new_user.full_name)
        welcome_message += (f" Your monthly fee of ₹{float(new_member.monthly_amount or 0):,.0f} is waiting for the "
                            "committee to confirm it. You can log in once the committee approves your account.")
        enqueue_result = NotificationService.enqueue_user_notification(
            user_id=new_user.id,
            title=welcome_title,
            message=welcome_message,
            target_role=new_user.role,
            category="announcements",
            link_url="/Notifications",
        )
        if not enqueue_result.get("queued"):
            NotificationService.create_user_notification(
                db=db,
                user_id=new_user.id,
                title=welcome_title,
                message=welcome_message,
                target_role=new_user.role,
                category="announcements",
                link_url="/Notifications",
            )
        
        return new_user

    @staticmethod
    def _with_fee_on_record(message: str, member) -> str:
        """Existing members joining: tell them the monthly fee on our records."""
        if member is None:
            return message
        if getattr(member, "monthly_member", True) is False:
            return message + " You are not a monthly member on our records."
        return (message + f" Your monthly fee on our records is ₹{float(member.monthly_amount or 0):,.0f}."
                " If this is not right, send a request from your Profile.")

    @staticmethod
    def _check_it_is_them(user: User, registration: UserRegisterWithInvite,
                          typed_email: str | None, typed_phone: str | None) -> None:
        """An existing member proves it is them with the last 4 digits of the mobile on record
        (or the email on record when there is no mobile). Older app versions send the full
        mobile/email instead, which (having matched the invite) is accepted too."""
        verify = str(registration.verify or "").strip()
        if verify:
            if user.phone:
                digits = phone_digits(verify)
                if (len(digits) == 4 and digits == last_digits(user.phone)) or phones_match(verify, user.phone):
                    return
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Those are not the last 4 digits of the mobile number the committee has for you.",
                )
            if user.email and verify.lower() == user.email.lower():
                return
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That is not the email the committee has for you.",
            )
        if (user.phone and typed_phone and phones_match(typed_phone, user.phone)) or (
            user.email and typed_email and typed_email.lower() == user.email.lower()
        ):
            return
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please enter the last 4 digits of your mobile number to confirm it is you.",
        )

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
            for user in find_users_by_phone(db, phone):
                if user not in candidates:
                    candidates.append(user)

        for user in candidates:
            # Only claim member-linked accounts that are currently offline/inactive.
            if user.role == "member" and user.member is not None and not user.is_active:
                return user

        return None

    @staticmethod
    def _find_existing_member_user_by_contacts(
        db: Session,
        invite: Invite,
        registration: UserRegisterWithInvite,
    ) -> User | None:
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
            for user in find_users_by_phone(db, phone):
                if user not in candidates:
                    candidates.append(user)

        for user in candidates:
            # str() of the role enum is "UserRole.MEMBER", so compare its value
            if str(getattr(user.role, "value", user.role)).lower() == "member" and user.member is not None:
                return user

        return None

    @staticmethod
    def _claim_existing_member_user(
        db: Session,
        user: User,
        invite: Invite,
        registration: UserRegisterWithInvite,
    ):
        normalized_username = AuthService._normalize_username(registration.username)
        if not normalized_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username is required",
            )

        username_owner = db.query(User).filter(User.username == normalized_username, User.id != user.id).first()
        if username_owner:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            )

        if registration.email and not user.email:
            email_owner = db.query(User).filter(
                User.email == AuthService._normalize_email(registration.email),
                User.id != user.id,
            ).first()
            if email_owner:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Email already taken",
                )

        if registration.phone and not user.phone:
            phone_owner = next((u for u in find_users_by_phone(db, registration.phone) if u.id != user.id), None)
            if phone_owner:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Phone already taken",
                )

        user.username = normalized_username
        # The committee's contacts stay; the form only fills ones the record doesn't have.
        if registration.email and not user.email:
            user.email = AuthService._normalize_email(registration.email)
        if registration.phone and not user.phone:
            user.phone = AuthService._normalize_phone(registration.phone)
        user.password_hash = hash_password(registration.password)
        user.is_active = True
        if registration.full_name and registration.full_name.strip():
            user.full_name = registration.full_name.strip()
            if user.member:
                user.member.full_name = registration.full_name.strip()
        member = user.member
        if member is not None:
            # Asked on the form only when the record has no location; saved (it used to be dropped).
            if registration.country and not member.country:
                member.country = registration.country
            if registration.city and registration.city.strip() and not (member.city or "").strip():
                member.city = registration.city.strip()
            if registration.address and registration.address.strip() and not (member.address or "").strip():
                member.address = registration.address.strip()

        # Keep invite tracking accurate.
        invite.is_used = True
        invite.used_by_user_id = user.id

        db.commit()

        from app.services.notification_service import NotificationService

        welcome_title, welcome_message = welcome_content(db, user.full_name)
        welcome_message = AuthService._with_fee_on_record(welcome_message, user.member)
        enqueue_result = NotificationService.enqueue_user_notification(
            user_id=user.id,
            title=welcome_title,
            message=welcome_message,
            target_role=user.role,
            category="announcements",
            link_url="/Notifications",
        )
        if not enqueue_result.get("queued"):
            NotificationService.create_user_notification(
                db=db,
                user_id=user.id,
                title=welcome_title,
                message=welcome_message,
                target_role=user.role,
                category="announcements",
                link_url="/Notifications",
            )
    
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

    @staticmethod
    def change_password(db: Session, user_id: int, current_password: str, new_password: str):
        """Change password for an authenticated user."""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        if str(user.role).lower() == "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Admin password changes require superadmin approval. "
                    "Please submit a reset request using forgot-password flow."
                ),
            )

        if not verify_password(current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect",
            )

        if verify_password(new_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from current password",
            )

        user.password_hash = hash_password(new_password)
        db.commit()
        db.refresh(user)
        from app.services.notification_service import NotificationService

        NotificationService.notify_security_event(db, user.id, "password_changed")
        return user
