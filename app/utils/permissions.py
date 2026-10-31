"""Separation-of-duties helpers shared by challan, request and fund routes."""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Member

MIN_REASON_LENGTH = 10


def _user_id(current_user) -> Optional[int]:
    if isinstance(current_user, dict):
        return current_user.get("user_id")
    return getattr(current_user, "user_id", None) or getattr(current_user, "id", None)


def is_own_member_record(db: Session, current_user, member_id: Optional[int]) -> bool:
    """True when the member row belongs to the acting user."""
    user_id = _user_id(current_user)
    if user_id is None or member_id is None:
        return False
    return (
        db.query(Member.id)
        .filter(Member.id == member_id, Member.user_id == user_id)
        .first()
        is not None
    )


def _self_error(action_label: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail=f"You cannot {action_label} your own payment/request. Another admin must do this.",
    )


def assert_not_self(db: Session, current_user, member_id: Optional[int], action_label: str) -> None:
    if is_own_member_record(db, current_user, member_id):
        raise _self_error(action_label)


def assert_not_own_user(current_user, owner_user_id: Optional[int], action_label: str) -> None:
    """Same rule for records owned directly by a user id (requests, resets, fund entries)."""
    user_id = _user_id(current_user)
    if user_id is not None and owner_user_id is not None and int(user_id) == int(owner_user_id):
        raise _self_error(action_label)


def assert_different_actor(current_user_id: Optional[int], original_actor_id: Optional[int], action_label: str) -> None:
    if (
        current_user_id is not None
        and original_actor_id is not None
        and int(current_user_id) == int(original_actor_id)
    ):
        label = action_label[:1].upper() + action_label[1:]
        raise HTTPException(
            status_code=403,
            detail=f"{label} must be done by a different admin than the one who approved it.",
        )


def require_reason(reason: Optional[str], field_label: str = "Reason", db: Optional[Session] = None) -> str:
    """Validate a reason; the minimum length is the platform setting when a db is given."""
    min_length = MIN_REASON_LENGTH
    if db is not None:
        from app.services.settings_service import get_setting

        min_length = max(MIN_REASON_LENGTH, int(get_setting(db, "min_reason_length")))
    cleaned = (reason or "").strip()
    if len(cleaned) < min_length:
        raise HTTPException(
            status_code=400,
            detail=f"{field_label} is required and must be at least {min_length} characters.",
        )
    return cleaned


def assert_can_verify_entry(current_user, challan) -> None:
    """Maker-checker for admin-recorded payments; imports and member-created challans are exempt."""
    if getattr(challan, "entry_source", None) != "admin":
        return
    user_id = _user_id(current_user)
    if user_id is None:
        return
    if challan.created_by_user_id is not None and int(challan.created_by_user_id) == int(user_id):
        raise HTTPException(
            status_code=403,
            detail="Payments entered by an admin must be verified by a different admin.",
        )
    method = str(getattr(challan, "payment_method", "") or "").lower()
    if method == "cash" and challan.collected_by_user_id is not None and int(challan.collected_by_user_id) == int(user_id):
        raise HTTPException(
            status_code=403,
            detail="Cash must be verified by an admin who did not collect it.",
        )
