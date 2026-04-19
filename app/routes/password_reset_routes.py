"""Routes for admin-mediated password reset requests."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import PasswordResetRequest, User
from app.schemas import (
    ForgotPasswordRequest,
    PasswordResetApprove,
    PasswordResetReject,
    PasswordResetComplete,
    PasswordResetRequestResponse,
    PasswordResetTokenVerifyResponse,
)
from app.utils.auth import get_current_admin
from app.services import password_reset_service
from app.services.whatsapp_service import generate_whatsapp_chat_url
from app.utils.message_format import with_islamic_greeting
from app.utils.invite_share import _normalize_base_url
from app.config import settings

router = APIRouter(tags=["Password Reset"])

TOKEN_EXPIRY_HOURS = 24


def _build_reset_chat_url(user, reset_token=None) -> str:
    """Build a wa.me link so the admin can manually send the reset link via WhatsApp."""
    phone = (getattr(user, "phone", None) or "") if user else ""
    if not phone:
        return ""
    if reset_token:
        base_url = _normalize_base_url()
        reset_link = f"{base_url}/ResetPassword?token={reset_token}"
        message = with_islamic_greeting(
            f"Your password reset request for CharityHub has been approved by the admin.\n\n"
            f"Click the link below to set your new password:\n"
            f"{reset_link}\n\n"
            f"This link expires in {TOKEN_EXPIRY_HOURS} hours. "
            f"Do not share this link with anyone."
        )
        return generate_whatsapp_chat_url(phone, message)
    return generate_whatsapp_chat_url(phone)


# ── Public endpoints (no auth required) ──────────────────────────────────────

@router.post(
    "/auth/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a forgot-password request",
)
def forgot_password(
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Creates a pending password reset request visible to admins.
    Always returns 202 regardless of whether the identifier matched an account
    to avoid leaking information about registered users.
    """
    password_reset_service.create_request(db, body.identifier)
    return {
        "message": (
            "Your request has been submitted. "
            "An admin will review it and you will receive a WhatsApp message "
            "with a reset link if your account is found."
        )
    }


@router.get(
    "/auth/reset-password/verify",
    response_model=PasswordResetTokenVerifyResponse,
    summary="Verify a password reset token",
)
def verify_reset_token(
    token: str = Query(..., description="Reset token from the WhatsApp link"),
    db: Session = Depends(get_db),
) -> PasswordResetTokenVerifyResponse:
    req = password_reset_service.verify_token(db, token)
    if not req:
        return PasswordResetTokenVerifyResponse(
            valid=False,
            message="Token is invalid or has expired.",
        )
    user = db.query(User).filter(User.id == req.user_id).first()
    return PasswordResetTokenVerifyResponse(
        valid=True,
        user_username=user.username if user else None,
        message="Token is valid.",
    )


@router.post(
    "/auth/reset-password",
    summary="Complete a password reset using a token",
)
def complete_reset(
    body: PasswordResetComplete,
    db: Session = Depends(get_db),
) -> dict:
    try:
        user = password_reset_service.complete_reset(db, body.token, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"message": "Password updated successfully.", "username": user.username}


# ── Admin endpoints (requires admin or superadmin) ────────────────────────────

@router.get(
    "/admin/password-reset-requests",
    response_model=list[PasswordResetRequestResponse],
    summary="List password reset requests (admin)",
)
def list_requests(
    request_status: Optional[str] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
) -> list[PasswordResetRequestResponse]:
    items = password_reset_service.list_requests(db, status=request_status, skip=skip, limit=limit)
    result = []
    for req in items:
        user = db.query(User).filter(User.id == req.user_id).first() if req.user_id else None
        # Re-resolve unmatched requests (e.g. created before case-insensitive fix)
        if not user and req.identifier and req.status == "pending":
            user = password_reset_service.resolve_user(db, req)
        result.append(
            PasswordResetRequestResponse(
                id=req.id,
                identifier=req.identifier,
                user_id=req.user_id,
                status=req.status,
                admin_id=req.admin_id,
                admin_notes=req.admin_notes,
                rejection_reason=req.rejection_reason,
                created_at=req.created_at,
                resolved_at=req.resolved_at,
                user_full_name=user.full_name if user else None,
                user_username=user.username if user else None,
                user_phone=user.phone if user else None,
                user_email=user.email if user else None,
                whatsapp_chat_url=_build_reset_chat_url(user, req.reset_token if req.status == "approved" else None),
            )
        )
    return result


@router.post(
    "/admin/password-reset-requests/{req_id}/approve",
    response_model=PasswordResetRequestResponse,
    summary="Approve a password reset request (admin)",
)
def approve_request(
    req_id: int,
    body: PasswordResetApprove,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
) -> PasswordResetRequestResponse:
    try:
        req = password_reset_service.approve_request(
            db, req_id, current_user["user_id"], body.admin_notes
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    user = db.query(User).filter(User.id == req.user_id).first() if req.user_id else None
    return PasswordResetRequestResponse(
        id=req.id,
        identifier=req.identifier,
        user_id=req.user_id,
        status=req.status,
        admin_id=req.admin_id,
        admin_notes=req.admin_notes,
        rejection_reason=req.rejection_reason,
        created_at=req.created_at,
        resolved_at=req.resolved_at,
        user_full_name=user.full_name if user else None,
        user_username=user.username if user else None,
        user_phone=user.phone if user else None,
        user_email=user.email if user else None,
        whatsapp_chat_url=_build_reset_chat_url(user, req.reset_token),
    )


@router.post(
    "/admin/password-reset-requests/{req_id}/reject",
    response_model=PasswordResetRequestResponse,
    summary="Reject a password reset request (admin)",
)
def reject_request(
    req_id: int,
    body: PasswordResetReject,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
) -> PasswordResetRequestResponse:
    try:
        req = password_reset_service.reject_request(
            db, req_id, current_user["user_id"], body.rejection_reason, body.admin_notes
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    user = db.query(User).filter(User.id == req.user_id).first() if req.user_id else None
    return PasswordResetRequestResponse(
        id=req.id,
        identifier=req.identifier,
        user_id=req.user_id,
        status=req.status,
        admin_id=req.admin_id,
        admin_notes=req.admin_notes,
        rejection_reason=req.rejection_reason,
        created_at=req.created_at,
        resolved_at=req.resolved_at,
        user_full_name=user.full_name if user else None,
        user_username=user.username if user else None,
        user_phone=user.phone if user else None,
        user_email=user.email if user else None,
        whatsapp_chat_url=_build_reset_chat_url(user),
    )
