"""Service layer for admin-mediated password reset requests."""

import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import settings
from app.models.models import PasswordResetRequest, User, Notification
from app.services.notification_service import NotificationService
from app.utils import hash_password

logger = logging.getLogger(__name__)

TOKEN_EXPIRY_HOURS = 24


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _find_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    """Look up a user by email, username, or phone number."""
    clean = identifier.strip()
    clean_lower = clean.lower()
    user = (
        db.query(User)
        .filter(
            (func.lower(User.email) == clean_lower)
            | (func.lower(User.username) == clean_lower)
            | (User.phone == clean)
        )
        .first()
    )
    return user


def resolve_user(db: Session, req: PasswordResetRequest) -> Optional[User]:
    """Re-resolve a request's user_id from its identifier (case-insensitive).

    Backfills req.user_id if a match is found so future lookups are instant.
    """
    user = _find_user_by_identifier(db, req.identifier)
    if user and not req.user_id:
        req.user_id = user.id
        db.commit()
        db.refresh(req)
    return user


def create_request(db: Session, identifier: str) -> PasswordResetRequest:
    """Create a pending password reset request (public, no auth required)."""
    user = _find_user_by_identifier(db, identifier)

    # Create the request even when the user is not found to avoid leaking
    # whether an account exists for a given identifier.
    req = PasswordResetRequest(
        identifier=identifier.strip(),
        user_id=user.id if user else None,
        status="pending",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # Notify all admins about the new password reset request
    _notify_admins_new_request(db, req, user)

    return req


def _notify_admins_new_request(
    db: Session, req: PasswordResetRequest, user: Optional[User]
) -> None:
    """Create an in-app notification for all admin/superadmin users."""
    try:
        display_name = user.full_name or user.username if user else req.identifier
        title = "New Password Reset Request"
        message = f"{display_name} has requested a password reset. Please review it in Admin Requests."

        admins = (
            db.query(User)
            .filter(User.role.in_(["admin", "superadmin"]), User.is_active == True)
            .all()
        )
        created_notifications = []
        for admin in admins:
            notification = Notification(
                user_id=admin.id,
                title=title,
                message=message,
                target_role="admin",
            )
            db.add(notification)
            created_notifications.append(notification)
        if admins:
            db.commit()
            for notification in created_notifications:
                db.refresh(notification)
                NotificationService.dispatch_notification(db, notification)
    except Exception:
        logger.exception("Failed to notify admins about password reset request %s", req.id)


def list_requests(
    db: Session,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> list[PasswordResetRequest]:
    """Return password reset requests (admin-only)."""
    q = db.query(PasswordResetRequest)
    if status:
        q = q.filter(PasswordResetRequest.status == status)
    q = q.order_by(PasswordResetRequest.created_at.desc())
    return q.offset(skip).limit(limit).all()


def get_request(db: Session, req_id: int) -> Optional[PasswordResetRequest]:
    return db.query(PasswordResetRequest).filter(PasswordResetRequest.id == req_id).first()


def approve_request(
    db: Session,
    req_id: int,
    admin_id: int,
    admin_notes: Optional[str] = None,
) -> PasswordResetRequest:
    """Approve a password reset request: generate token for admin to share."""
    req = db.query(PasswordResetRequest).filter(PasswordResetRequest.id == req_id).first()
    if not req:
        raise ValueError(f"PasswordResetRequest {req_id} not found")
    if req.status != "pending":
        raise ValueError(f"Request is already {req.status}")
    if not req.user_id:
        # Re-resolve: identifier may now match after case-insensitive fix
        user = _find_user_by_identifier(db, req.identifier)
        if user:
            req.user_id = user.id
        else:
            raise ValueError("Cannot approve request: original identifier did not match any account")
    else:
        user = db.query(User).filter(User.id == req.user_id).first()

    if not user:
        raise ValueError("Associated user account not found")

    token = secrets.token_urlsafe(48)
    now = _utcnow()

    req.status = "approved"
    req.reset_token = token
    req.token_expires_at = now + timedelta(hours=TOKEN_EXPIRY_HOURS)
    req.admin_id = admin_id
    req.admin_notes = admin_notes
    req.resolved_at = now

    db.commit()
    db.refresh(req)

    # WhatsApp link is built in the route layer (_build_reset_chat_url)
    # and returned to the admin frontend for manual sending.
    return req


def reject_request(
    db: Session,
    req_id: int,
    admin_id: int,
    rejection_reason: str,
    admin_notes: Optional[str] = None,
) -> PasswordResetRequest:
    """Reject a password reset request."""
    req = db.query(PasswordResetRequest).filter(PasswordResetRequest.id == req_id).first()
    if not req:
        raise ValueError(f"PasswordResetRequest {req_id} not found")
    if req.status != "pending":
        raise ValueError(f"Request is already {req.status}")

    now = _utcnow()
    req.status = "rejected"
    req.rejection_reason = rejection_reason
    req.admin_id = admin_id
    req.admin_notes = admin_notes
    req.resolved_at = now

    db.commit()
    db.refresh(req)
    return req


def verify_token(db: Session, token: str) -> Optional[PasswordResetRequest]:
    """Return the request if the token is valid and unexpired, else None."""
    req = (
        db.query(PasswordResetRequest)
        .filter(
            PasswordResetRequest.reset_token == token,
            PasswordResetRequest.status == "approved",
        )
        .first()
    )
    if not req:
        return None
    if req.token_expires_at and req.token_expires_at < _utcnow():
        return None
    return req


def complete_reset(db: Session, token: str, new_password: str) -> User:
    """Set the new password and mark the request as used."""
    req = verify_token(db, token)
    if not req:
        raise ValueError("Token is invalid or has expired")

    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise ValueError("Associated user account not found")

    user.password_hash = hash_password(new_password)

    req.status = "used"
    req.resolved_at = _utcnow()

    db.commit()
    db.refresh(user)
    return user
