"""Service layer for admin-mediated password reset requests."""

import re
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, cast

from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from fastapi import HTTPException

from app.config import settings
from app.models.models import PasswordResetRequest, User, Notification
from app.services.notification_service import NotificationService
from app.services.settings_service import get_setting
from app.utils import hash_password
from app.utils.audit import log_audit
from app.utils.permissions import assert_not_own_user

logger = logging.getLogger(__name__)

PRIVILEGED_ROLES = {"admin", "superadmin", "executive"}  # executives see members' details
ADMIN_RESET_DENIED = "Password resets for admin accounts must be handled by the superadmin"
SUPERADMIN_RESET_DENIED = "Superadmin password resets must be done from the server with seed_admin.py"


def _role_value(user: Optional[User]) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "value", role) or "").lower()


def _authorize_resolution(db: Session, actor_id: int, target: Optional[User], action_label: str) -> None:
    """Enforce who may approve/reject a reset for ``target``.

    Admin and superadmin accounts can only be handled by a superadmin, and
    never by the account owner. The actor's role is read from the database,
    not from the caller.
    """
    if target is None:
        return
    target_role = _role_value(target)
    if target_role not in PRIVILEGED_ROLES:
        assert_not_own_user({"user_id": actor_id}, cast(int, target.id), action_label)
        return

    if target_role == "superadmin":
        other_superadmin = (
            db.query(User)
            .filter(User.role == "superadmin", User.is_active == True, User.id != target.id)
            .first()
        )
        if other_superadmin is None:
            raise HTTPException(status_code=403, detail=SUPERADMIN_RESET_DENIED)

    assert_not_own_user({"user_id": actor_id}, cast(int, target.id), action_label)

    actor = db.query(User).filter(User.id == actor_id).first()
    if _role_value(actor) != "superadmin":
        raise HTTPException(status_code=403, detail=ADMIN_RESET_DENIED)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


PHONE_LIKE = re.compile(r"^\+?[\d\s().-]{7,}$")


def _phone_digits(value: Optional[str]) -> str:
    """'+971 050-123 4567' -> '971501234567': digits only, without a leading 0
    (local format) or a 0 typed right after the country code."""
    from app.utils.countries import COUNTRIES

    digits = re.sub(r"\D", "", value or "").lstrip("0")
    for code in sorted({c for _, c in COUNTRIES.values()}, key=len, reverse=True):
        if digits.startswith(code + "0") and len(digits) > len(code) + 7:
            return code + digits[len(code):].lstrip("0")
    return digits


def _same_phone(typed: str, stored: str) -> bool:
    """Equal digits, or one is the other without its country code (at least 8 digits)."""
    if not typed or not stored:
        return False
    if typed == stored:
        return True
    shorter, longer = sorted((typed, stored), key=len)
    return len(shorter) >= 8 and longer.endswith(shorter)


def _find_user_by_phone(db: Session, raw: str) -> Optional[User]:
    """Match the phone or WhatsApp number however it was typed or saved; only a single match counts."""
    typed = _phone_digits(raw)
    if len(typed) < 7:
        return None
    tail = typed[-7:]
    candidates = (
        db.query(User)
        .filter(or_(User.phone.isnot(None), User.whatsapp_phone.isnot(None)))
        .all()
    )
    matches = {
        u.id: u for u in candidates
        if tail in re.sub(r"\D", "", f"{u.phone or ''} {u.whatsapp_phone or ''}")
        and (_same_phone(typed, _phone_digits(u.phone)) or _same_phone(typed, _phone_digits(u.whatsapp_phone)))
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def _find_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    """Look up a user by email, username, or phone number (phone in any format)."""
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
    if user is None and PHONE_LIKE.match(clean):
        user = _find_user_by_phone(db, clean)
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

    # Asking again while a request is still waiting: keep that one (with what they typed now);
    # admins are not told again.
    if user is not None:
        waiting = (
            db.query(PasswordResetRequest)
            .filter(PasswordResetRequest.user_id == user.id, PasswordResetRequest.status == "pending")
            .order_by(PasswordResetRequest.created_at.desc())
            .first()
        )
        if waiting is not None:
            waiting.identifier = identifier.strip()
            db.commit()
            db.refresh(waiting)
            return waiting

    # Create the request even when the user is not found to avoid leaking
    # whether an account exists for a given identifier (the response is the same). Such
    # requests are kept but not shown to admins: there is no account to reset.
    req = PasswordResetRequest(
        identifier=identifier.strip(),
        user_id=user.id if user else None,
        status="pending",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    if user is not None:  # nothing to do for an unknown name or number
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
                category="admin_requests",
                link_url=f"/admin/requests?tab=password&request={req.id}",
                entity_type="password_reset",
                entity_id=req.id,
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
    """Return password reset requests (admin-only), only those that match an account."""
    # Older requests may match now (e.g. after the case-insensitive fix): link them first.
    for req in (db.query(PasswordResetRequest)
                .filter(PasswordResetRequest.user_id.is_(None), PasswordResetRequest.status == "pending")
                .limit(500).all()):
        resolve_user(db, req)
    q = db.query(PasswordResetRequest).filter(PasswordResetRequest.user_id.isnot(None))
    if status:
        q = q.filter(PasswordResetRequest.status == status)
    q = q.order_by(PasswordResetRequest.created_at.desc())
    return q.offset(skip).limit(limit).all()


DELETE_AFTER_DAYS = 7


def deletable_from(req: PasswordResetRequest) -> Optional[datetime]:
    """When an admin may delete this request: pending or rejected, 7 days after it was sent.
    Approved and used ones stay as a record (None)."""
    if req.status not in ("pending", "rejected") or req.created_at is None:
        return None
    return req.created_at + timedelta(days=DELETE_AFTER_DAYS)


def can_delete(req: PasswordResetRequest, now: Optional[datetime] = None) -> bool:
    start = deletable_from(req)
    return start is not None and (now or _utcnow()) >= start


def delete_request(db: Session, req_id: int, actor_id: int) -> None:
    """Delete an old pending or rejected request (7 days after it was sent). Audited. Commits.
    Requests for admin accounts can only be deleted by a superadmin (as with resetting them)."""
    req = get_request(db, req_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Password reset request not found")
    if req.status not in ("pending", "rejected"):
        raise HTTPException(status_code=400, detail="Approved and used requests are kept as a record.")
    if not can_delete(req):
        raise HTTPException(status_code=400,
                            detail=f"Requests can be deleted {DELETE_AFTER_DAYS} days after they were sent.")
    target = db.query(User).filter(User.id == req.user_id).first() if req.user_id else None
    actor = db.query(User).filter(User.id == actor_id).first()
    if target is not None and _role_value(target) in PRIVILEGED_ROLES and _role_value(actor) != "superadmin":
        raise HTTPException(status_code=403, detail="Requests for admin accounts can only be deleted by the superadmin.")
    log_audit(
        db,
        user_id=actor_id,
        action="password_reset_request_deleted",
        entity_type="PasswordResetRequest",
        entity_id=req.id,
        old_values={"status": req.status, "identifier": req.identifier, "user_id": req.user_id,
                    "created_at": req.created_at.isoformat() if req.created_at else None},
        auto_commit=False,
    )
    db.delete(req)
    db.commit()


def get_request(db: Session, req_id: int) -> Optional[PasswordResetRequest]:
    return db.query(PasswordResetRequest).filter(PasswordResetRequest.id == req_id).first()


def approve_request(
    db: Session,
    req_id: int,
    admin_id: int,
    admin_notes: Optional[str] = None,
    approver_role: Optional[str] = None,
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

    approved_user_id = cast(int, user.id)
    _authorize_resolution(db, admin_id, user, "approve")

    token = secrets.token_urlsafe(48)
    now = _utcnow()

    req.status = "approved"
    req.reset_token = token
    req.token_expires_at = now + timedelta(minutes=get_setting(db, "password_reset_link_expiry_minutes"))
    req.admin_id = admin_id
    req.admin_notes = admin_notes
    req.resolved_at = now

    log_audit(
        db,
        user_id=admin_id,
        action="password_reset_approve",
        entity_type="PasswordResetRequest",
        entity_id=req.id,
        old_values={"status": "pending"},
        new_values={
            "status": "approved",
            "target_user_id": approved_user_id,
            "target_role": _role_value(user),
        },
    )
    db.commit()
    db.refresh(req)

    # The reset link is built in the route layer and returned only in the
    # approve response; list endpoints never expose the token.
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

    target = db.query(User).filter(User.id == req.user_id).first() if req.user_id else None
    _authorize_resolution(db, admin_id, target, "reject")

    now = _utcnow()
    req.status = "rejected"
    req.rejection_reason = rejection_reason
    req.admin_id = admin_id
    req.admin_notes = admin_notes
    req.resolved_at = now

    log_audit(
        db,
        user_id=admin_id,
        action="password_reset_reject",
        entity_type="PasswordResetRequest",
        entity_id=req.id,
        old_values={"status": "pending"},
        new_values={
            "status": "rejected",
            "reason": rejection_reason,
            "target_user_id": req.user_id,
            "target_role": _role_value(target),
        },
    )
    db.commit()
    db.refresh(req)
    return req


def verify_token(db: Session, token: str) -> Optional[PasswordResetRequest]:
    """Return the request if the token is valid, unused and unexpired, else None."""
    if not token:
        return None
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
    if not req.token_expires_at or req.token_expires_at < _utcnow():
        return None
    return req


def complete_reset(db: Session, token: str, new_password: str) -> User:
    """Set the new password and mark the request as used (single use)."""
    req = verify_token(db, token)
    if not req:
        raise ValueError("Token is invalid or has expired")

    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise ValueError("Associated user account not found")

    user.password_hash = hash_password(new_password)

    req.status = "used"
    req.reset_token = None
    req.resolved_at = _utcnow()

    log_audit(
        db,
        user_id=cast(int, user.id),
        action="password_reset_complete",
        entity_type="PasswordResetRequest",
        entity_id=req.id,
        old_values={"status": "approved"},
        new_values={
            "status": "used",
            "target_user_id": cast(int, user.id),
            "target_role": _role_value(user),
        },
    )
    db.commit()
    db.refresh(user)
    NotificationService.notify_security_event(db, cast(int, user.id), "password_reset")
    return user
