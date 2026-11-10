"""Self-activation for existing (imported) members.

An imported member already has a user account (inactive, auto-generated
username, no known password). Instead of an admin generating an invite link per
member, the member fills one form with their Member ID and personal details.
An admin compares it with the record and approves or rejects it. Only an
approval touches the member's account.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime
from difflib import SequenceMatcher

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AuditLog, Challan, Member, MemberActivation, Notification, User
from app.models.models import ChallanStatus, ChallanType
from app.services.notification_service import NotificationService
from app.services.settings_service import get_setting
from app.utils import hash_password, verify_password
from app.utils.message_format import with_islamic_greeting

logger = logging.getLogger(__name__)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"

MAX_PENDING_PER_MEMBER = 3
SUBMIT_LIMIT = 5  # submissions (and failed Member ID lookups) per IP ...
SUBMIT_WINDOW_SECONDS = 60 * 60  # ... per hour

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,30}$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_attempts: dict[str, list[float]] = {}
_attempts_lock = threading.Lock()


def _bad_request(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    return HTTPException(status_code=code, detail=message)


def _role_value(role) -> str:
    return str(getattr(role, "value", role) or "").lower()


def normalize_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    cleaned = "".join(str(phone).split())
    return cleaned or None


def normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    cleaned = str(email).strip().lower()
    return cleaned or None


def _check_rate_limit(source_ip: str | None) -> None:
    if not source_ip:
        return
    now = time.monotonic()
    with _attempts_lock:
        recent = [t for t in _attempts.get(source_ip, []) if now - t < SUBMIT_WINDOW_SECONDS]
        _attempts[source_ip] = recent
        if len(recent) >= SUBMIT_LIMIT:
            raise _bad_request(
                "Too many activation attempts from this device. Please try again in an hour or ask an admin.",
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
        recent.append(now)


def reset_rate_limit() -> None:
    """Test helper."""
    with _attempts_lock:
        _attempts.clear()


# ── Matching helpers ────────────────────────────────────────────────────────

def find_member_by_code(db: Session, entered: str) -> Member | None:
    """Accept '0001', '#1', 'MEM-0001', 'mem 1' and so on."""
    raw = str(entered or "").strip()
    if not raw:
        return None
    digits = re.sub(r"[^0-9]", "", raw)
    candidates = {raw.upper()}
    if digits:
        number = int(digits)
        candidates.update({
            f"MEM-{number:04d}", f"MEM-{number}", f"MEM{number:04d}", f"MEM{number}",
            f"{number:04d}", str(number),
        })
    return (
        db.query(Member)
        .filter(func.upper(Member.member_code).in_(list(candidates)))
        .first()
    )


def _name_tokens(name: str | None) -> list[str]:
    return [t for t in re.split(r"[^a-z]+", str(name or "").lower()) if t]


def name_match(entered: str | None, record: str | None) -> str:
    """'match', 'close' or 'different'. Spelling variants count as close."""
    a, b = _name_tokens(entered), _name_tokens(record)
    if not a or not b:
        return "different"
    if sorted(a) == sorted(b):
        return "match"
    ratio = SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio()
    if ratio >= 0.85:
        return "match"
    # Token-level: every token on one side resembles a token on the other.
    def covered(xs, ys):
        return all(any(SequenceMatcher(None, x, y).ratio() >= 0.75 or x.startswith(y) or y.startswith(x)
                       for y in ys) for x in xs)
    if covered(a, b) or covered(b, a) or ratio >= 0.6:
        return "close"
    return "different"


def last_paid_month_on_record(db: Session, member_id: int) -> str | None:
    return (
        db.query(func.max(Challan.month))
        .filter(
            Challan.member_id == member_id,
            Challan.type == ChallanType.MONTHLY,
            Challan.status == ChallanStatus.APPROVED,
            Challan.month.isnot(None),
        )
        .scalar()
    )


def _contact_conflicts(db: Session, exclude_user_id: int | None, *, username=None, phone=None, email=None) -> list[str]:
    problems = []

    def owner(column, value):
        q = db.query(User).filter(column == value)
        if exclude_user_id:
            q = q.filter(User.id != exclude_user_id)
        return q.first()

    if username and owner(func.lower(User.username), username.lower()):
        problems.append("This username is already taken. Please choose another one.")
    if phone and owner(User.phone, phone):
        problems.append("This phone number is already used by another account.")
    if email and owner(func.lower(User.email), email.lower()):
        problems.append("This email is already used by another account.")
    return problems


# ── Service ────────────────────────────────────────────────────────────────

class MemberActivationService:

    @staticmethod
    def is_enabled(db: Session) -> bool:
        return bool(get_setting(db, "self_activation_enabled"))

    @staticmethod
    def submit(db: Session, payload, source_ip: str | None = None) -> dict:
        if not MemberActivationService.is_enabled(db):
            raise _bad_request("Self-activation is turned off. Please ask an admin for an invite link.",
                               status.HTTP_403_FORBIDDEN)
        _check_rate_limit(source_ip)

        username = str(payload.username or "").strip().lower()
        full_name = " ".join(str(payload.full_name or "").split())
        phone = normalize_phone(payload.phone)
        email = None if payload.no_email else normalize_email(payload.email)
        whatsapp = normalize_phone(payload.whatsapp_phone)
        last_paid = (payload.last_paid_month or "").strip() or None

        if len(full_name) < 2:
            raise _bad_request("Please enter your full name.")
        if not phone or len(re.sub(r"\D", "", phone)) < 7:
            raise _bad_request("Please enter a valid phone number.")
        if email and not EMAIL_RE.match(email):
            raise _bad_request("Please enter a valid email address.")
        if not email and not whatsapp:
            raise _bad_request("Please enter your email, or your WhatsApp number if you don't use email.")
        if not USERNAME_RE.match(username):
            raise _bad_request("Username must be 3-30 characters: letters, numbers, dot, dash or underscore.")
        if len(payload.password or "") < 8:
            raise _bad_request("Password must be at least 8 characters.")
        if last_paid and not MONTH_RE.match(last_paid):
            raise _bad_request("Last paid month must look like 2026-09.")

        member = find_member_by_code(db, payload.member_code)
        if member is None:
            raise _bad_request(
                "We couldn't find this Member ID. Please check it on your receipt or ask an admin.",
                status.HTTP_404_NOT_FOUND,
            )
        member_user = member.user
        if member_user is not None and member_user.is_active:
            raise _bad_request(
                "This Member ID is already active. If it is yours, use \"Forgot password\" on the login page "
                "or contact an admin.",
                status.HTTP_409_CONFLICT,
            )

        exclude_id = member_user.id if member_user else None
        problems = _contact_conflicts(db, exclude_id, username=username, phone=phone, email=email)
        if problems:
            raise _bad_request(problems[0], status.HTTP_409_CONFLICT)

        pending_for_member = (
            db.query(MemberActivation)
            .filter(MemberActivation.member_id == member.id, MemberActivation.status == PENDING)
            .with_for_update()
            .all()
        )
        # Username must not be held by someone else's pending request.
        username_holder = (
            db.query(MemberActivation)
            .filter(func.lower(MemberActivation.username) == username, MemberActivation.status == PENDING)
            .first()
        )
        own = next((a for a in pending_for_member if a.phone == phone or a.username.lower() == username), None)
        if username_holder is not None and username_holder is not own:
            raise _bad_request("This username is already taken. Please choose another one.", status.HTTP_409_CONFLICT)

        is_new = own is None
        if is_new and len(pending_for_member) >= MAX_PENDING_PER_MEMBER:
            raise _bad_request("There are already requests waiting for this Member ID. Please contact an admin.",
                               status.HTTP_409_CONFLICT)

        item = own or MemberActivation(member_id=member.id, status=PENDING)
        item.member_code_entered = str(payload.member_code).strip()[:50]
        item.full_name = full_name[:255]
        item.username = username
        item.password_hash = hash_password(payload.password)
        item.phone = phone
        item.email = email
        item.whatsapp_phone = whatsapp
        item.last_paid_month = last_paid
        item.source_ip = (source_ip or "")[:64] or None
        if is_new:
            db.add(item)
        db.commit()
        db.refresh(item)

        if is_new:
            MemberActivationService._notify_admins(db, item, member)

        return {
            "id": item.id,
            "status": item.status,
            "member_code": member.member_code,
            "updated": not is_new,
            "message": "Thank you. Your request has been sent to the admins. "
                       "Sign in with your new username and password to check its status.",
        }

    @staticmethod
    def _notify_admins(db: Session, item: MemberActivation, member: Member) -> None:
        try:
            admins = db.query(User).filter(
                User.is_active == True,  # noqa: E712
                User.role.in_(["admin", "superadmin"]),
            ).all()
            created = []
            for admin in admins:
                n = Notification(
                    user_id=admin.id,
                    title="New member activation",
                    message=f"{item.full_name} wants to activate Member ID {member.member_code}. Please review.",
                    target_role=admin.role,
                    category="admin_requests",
                    link_url=f"/admin/requests?tab=activations&request={item.id}",
                    entity_type="member_activation",
                    entity_id=item.id,
                )
                db.add(n)
                created.append(n)
            db.commit()
            for n in created:
                db.refresh(n)
                NotificationService.dispatch_notification(db, n)
        except Exception:
            logger.exception("Failed to notify admins about member activation %s", item.id)

    # ── Login status ──

    @staticmethod
    def status_for_login(db: Session, identifier: str, password: str) -> dict | None:
        """If these credentials belong to an activation request (not an account), describe it."""
        ident = (identifier or "").strip().lower()
        if not ident or not password:
            return None
        try:
            candidates = (
                db.query(MemberActivation)
                .filter(
                    (func.lower(MemberActivation.username) == ident) | (func.lower(MemberActivation.email) == ident),
                    MemberActivation.status.in_([PENDING, REJECTED]),
                )
                .order_by(MemberActivation.created_at.desc(), MemberActivation.id.desc())
                .limit(10)
                .all()
            )
        except Exception:
            # Never let this extra check break normal logins (e.g. table not created yet).
            logger.exception("Activation status lookup failed during login")
            db.rollback()
            return None
        candidates.sort(key=lambda a: 0 if a.status == PENDING else 1)
        for item in candidates:
            if verify_password(password, item.password_hash):
                member_code = item.member.member_code if item.member else item.member_code_entered
                if item.status == PENDING:
                    return {
                        "code": "activation_pending",
                        "message": "Your activation request is waiting for an admin to approve it.",
                        "member_code": member_code,
                        "full_name": item.full_name,
                        "submitted_at": item.created_at.isoformat() if item.created_at else None,
                    }
                return {
                    "code": "activation_rejected",
                    "message": "Your activation request was not approved.",
                    "member_code": member_code,
                    "full_name": item.full_name,
                    "reason": item.rejection_reason,
                    "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
                }
        return None

    # ── Admin ──

    @staticmethod
    def _checks(db: Session, item: MemberActivation) -> dict:
        member = item.member
        user = member.user if member else None
        record_name = (member.full_name if member else None) or (user.full_name if user else None)
        record_month = last_paid_month_on_record(db, member.id) if member else None
        if not item.last_paid_month:
            month_result = "not_given"
        elif not record_month:
            month_result = "no_records"
        else:
            month_result = "match" if item.last_paid_month == record_month else "different"
        other_pending = 0
        if member:
            other_pending = (
                db.query(MemberActivation)
                .filter(
                    MemberActivation.member_id == member.id,
                    MemberActivation.status == PENDING,
                    MemberActivation.id != item.id,
                )
                .count()
            )
        conflicts = _contact_conflicts(
            db, user.id if user else None, username=item.username, phone=item.phone, email=item.email,
        ) if item.status == PENDING else []
        return {
            "name": name_match(item.full_name, record_name),
            "last_paid_month": month_result,
            "already_active": bool(user and user.is_active and item.status == PENDING),
            "other_pending": other_pending,
            "conflicts": conflicts,
        }

    @staticmethod
    def _serialize(db: Session, item: MemberActivation, with_checks: bool = True) -> dict:
        member = item.member
        user = member.user if member else None
        months_paid = 0
        if member:
            months_paid = (
                db.query(func.count(func.distinct(Challan.month)))
                .filter(
                    Challan.member_id == member.id,
                    Challan.type == ChallanType.MONTHLY,
                    Challan.status == ChallanStatus.APPROVED,
                )
                .scalar()
                or 0
            )
        data = {
            "id": item.id,
            "status": item.status,
            "member_id": item.member_id,
            "member_code_entered": item.member_code_entered,
            "full_name": item.full_name,
            "username": item.username,
            "phone": item.phone,
            "email": item.email,
            "whatsapp_phone": item.whatsapp_phone,
            "last_paid_month": item.last_paid_month,
            "rejection_reason": item.rejection_reason,
            "admin_notes": item.admin_notes,
            "reviewed_by_name": (item.reviewed_by.full_name or item.reviewed_by.username) if item.reviewed_by else None,
            "reviewed_at": item.reviewed_at,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "record": {
                "member_code": member.member_code if member else None,
                "full_name": (member.full_name if member else None) or (user.full_name if user else None),
                "phone": user.phone if user else None,
                "email": user.email if user else None,
                "member_status": member.status if member else None,
                "monthly_amount": member.monthly_amount if member else None,
                "months_paid": int(months_paid),
                "last_paid_month": last_paid_month_on_record(db, member.id) if member else None,
                "account_active": bool(user and user.is_active),
            },
        }
        if with_checks:
            data["checks"] = MemberActivationService._checks(db, item)
        return data

    @staticmethod
    def list(db: Session, status_filter: str | None, skip: int, limit: int) -> dict:
        q = db.query(MemberActivation)
        if status_filter and status_filter.lower() != "all":
            q = q.filter(MemberActivation.status == status_filter.lower())
        total = q.count()
        items = (
            q.order_by(MemberActivation.created_at.desc(), MemberActivation.id.desc())
            .offset(skip).limit(limit).all()
        )
        pending_total = db.query(MemberActivation).filter(MemberActivation.status == PENDING).count()
        return {
            "items": [MemberActivationService._serialize(db, i) for i in items],
            "total": total,
            "pending_total": pending_total,
        }

    @staticmethod
    def get(db: Session, activation_id: int) -> dict:
        return MemberActivationService._serialize(db, MemberActivationService._load(db, activation_id))

    @staticmethod
    def _load(db: Session, activation_id: int, lock: bool = False) -> MemberActivation:
        q = db.query(MemberActivation).filter(MemberActivation.id == activation_id)
        if lock:
            q = q.with_for_update()
        item = q.first()
        if item is None:
            raise _bad_request("Activation request not found", status.HTTP_404_NOT_FOUND)
        return item

    @staticmethod
    def approve(db: Session, current_admin: dict, activation_id: int, notes: str | None = None) -> dict:
        item = MemberActivationService._load(db, activation_id, lock=True)
        if item.status != PENDING:
            raise _bad_request(f"This request is already {item.status}.", status.HTTP_409_CONFLICT)
        member = item.member
        user = member.user if member else None
        if user is None:
            raise _bad_request("This member has no account to activate.", status.HTTP_409_CONFLICT)
        if user.is_active:
            raise _bad_request("This member's account is already active. Reject this request with a reason.",
                               status.HTTP_409_CONFLICT)
        if _role_value(user.role) != "member":
            raise _bad_request("Only member accounts can be activated this way.", status.HTTP_409_CONFLICT)
        problems = _contact_conflicts(db, user.id, username=item.username, phone=item.phone, email=item.email)
        if problems:
            raise _bad_request(problems[0] + " Reject the request with a reason.", status.HTTP_409_CONFLICT)

        before = {"username": user.username, "phone": user.phone, "email": user.email, "is_active": user.is_active}
        user.username = item.username
        user.password_hash = item.password_hash
        user.phone = item.phone
        if item.email:
            user.email = item.email
        if item.whatsapp_phone:
            user.whatsapp_phone = item.whatsapp_phone
        if not user.full_name:
            user.full_name = item.full_name
        user.is_active = True
        user.welcome_pending = True

        now = datetime.utcnow()
        admin_id = int(current_admin.get("user_id"))
        item.status = APPROVED
        item.admin_notes = (notes or "").strip() or None
        item.reviewed_by_admin_id = admin_id
        item.reviewed_at = now

        others = (
            db.query(MemberActivation)
            .filter(
                MemberActivation.member_id == member.id,
                MemberActivation.status == PENDING,
                MemberActivation.id != item.id,
            )
            .all()
        )
        for other in others:
            other.status = REJECTED
            other.rejection_reason = "Another activation request for this Member ID was approved."
            other.reviewed_by_admin_id = admin_id
            other.reviewed_at = now

        db.add(AuditLog(
            user_id=admin_id,
            action="member_activation_approved",
            entity_type="MemberActivation",
            entity_id=item.id,
            old_values=json.dumps(before),
            new_values=json.dumps({
                "member_code": member.member_code, "user_id": user.id, "username": user.username,
                "phone": user.phone, "email": user.email, "auto_rejected": [o.id for o in others],
            }),
        ))
        welcome = Notification(
            user_id=user.id,
            title="Welcome! Your account is active",
            message=with_islamic_greeting(
                f"Your account for Member ID {member.member_code} has been approved. "
                "Your payment history is ready to view."
            ),
            target_role=user.role,
            category="announcements",
            link_url="/dashboard",
        )
        db.add(welcome)
        db.commit()
        db.refresh(welcome)
        NotificationService.dispatch_notification(db, welcome)
        db.refresh(item)
        return MemberActivationService._serialize(db, item)

    @staticmethod
    def reject(db: Session, current_admin: dict, activation_id: int, reason: str, notes: str | None = None) -> dict:
        item = MemberActivationService._load(db, activation_id, lock=True)
        if item.status != PENDING:
            raise _bad_request(f"This request is already {item.status}.", status.HTTP_409_CONFLICT)
        reason = (reason or "").strip()
        min_len = int(get_setting(db, "min_reason_length") or 10)
        if len(reason) < min_len:
            raise _bad_request(f"Please give a reason of at least {min_len} characters.")
        admin_id = int(current_admin.get("user_id"))
        item.status = REJECTED
        item.rejection_reason = reason
        item.admin_notes = (notes or "").strip() or None
        item.reviewed_by_admin_id = admin_id
        item.reviewed_at = datetime.utcnow()
        db.add(AuditLog(
            user_id=admin_id,
            action="member_activation_rejected",
            entity_type="MemberActivation",
            entity_id=item.id,
            new_values=json.dumps({"reason": reason}),
        ))
        db.commit()
        db.refresh(item)
        return MemberActivationService._serialize(db, item)

    # ── Welcome screen ──

    @staticmethod
    def welcome_summary(db: Session, user_id: int) -> dict:
        user = db.get(User, user_id)
        if user is None or not user.welcome_pending:
            return {"show": False}
        member = user.member
        summary = {"show": True, "full_name": user.full_name or user.username,
                   "member_code": member.member_code if member else None,
                   "months_paid": 0, "total_paid": 0.0, "first_month": None, "last_month": None}
        if member:
            approved = (
                db.query(Challan)
                .filter(Challan.member_id == member.id, Challan.status == ChallanStatus.APPROVED)
                .all()
            )
            months = sorted({c.month for c in approved if c.type == ChallanType.MONTHLY and c.month})
            summary.update({
                "full_name": member.full_name or summary["full_name"],
                "months_paid": len(months),
                "total_paid": float(sum(c.amount or 0 for c in approved)),
                "first_month": months[0] if months else None,
                "last_month": months[-1] if months else None,
            })
        return summary

    @staticmethod
    def mark_welcome_seen(db: Session, user_id: int) -> dict:
        user = db.get(User, user_id)
        if user is not None and user.welcome_pending:
            user.welcome_pending = False
            db.commit()
        return {"ok": True}
