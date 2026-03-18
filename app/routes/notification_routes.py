from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import (
    NotificationCreate,
    NotificationResponse,
    NotificationAdminUpdate,
    NotificationReadPatchRequest,
    NotificationSentBatchResponse,
    NotificationSentDeleteRequest,
    NotificationSentDeleteResponse,
)
from app.services import NotificationService
from app.utils import get_current_user, get_current_admin
from typing import List

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_notification(
    notification_data: NotificationCreate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Create and send notification (Admin only).
    Returns sent_count and a message.
    Supports: single user (user_id), role broadcast (target_role), or all users.
    """
    return NotificationService.create_notification(db, notification_data, current_user["user_id"])


@router.get("/", response_model=List[NotificationResponse])
def get_my_notifications(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get current user's notifications, newest first.
    """
    return NotificationService.get_user_notifications(db, current_user["user_id"], skip, limit)


@router.get("/unread/count")
def get_unread_count(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get count of unread notifications for current user.
    """
    count = NotificationService.get_unread_notifications_count(db, current_user["user_id"])
    return {"unread_count": count}


@router.get("/feed")
def get_notification_feed(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Feed payload for frontend state context (items + unread_count)."""
    return NotificationService.get_user_notification_feed(
        db,
        user_id=current_user["user_id"],
        skip=skip,
        limit=limit,
    )


@router.get("/admin/sent", response_model=List[NotificationSentBatchResponse])
def get_admin_sent_notifications(
    minutes: int = Query(default=10080, ge=1, le=525600),
    audience_filter: str = Query(default="all", pattern="^(all|members|admins|superadmins)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Admin panel: list grouped sent-notification batches with audience identification."""
    return NotificationService.get_admin_sent_notifications(
        db,
        minutes=minutes,
        audience_filter=audience_filter,
        skip=skip,
        limit=limit,
    )


@router.delete("/admin/sent", response_model=NotificationSentDeleteResponse)
def delete_admin_sent_notifications(
    payload: NotificationSentDeleteRequest,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Admin panel: delete notifications from a sent batch for members/admins/all scope."""
    return NotificationService.delete_admin_sent_notifications(
        db,
        batch_created_at=payload.batch_created_at,
        title=payload.title,
        message=payload.message,
        recipient_scope=payload.recipient_scope,
    )


@router.get("/{notification_id}", response_model=NotificationResponse)
def get_notification(
    notification_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get a single notification by ID (must belong to current user).
    """
    return NotificationService.get_notification_by_id(db, notification_id, current_user["user_id"])


@router.put("/{notification_id}/read", response_model=NotificationResponse)
def mark_as_read(
    notification_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mark a notification as read (must belong to current user).
    """
    return NotificationService.mark_as_read(db, notification_id, current_user["user_id"])


@router.post("/mark-all-read")
def mark_all_as_read(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mark all of current user's unread notifications as read.
    """
    return NotificationService.mark_all_as_read(db, current_user["user_id"])


@router.patch("/read")
def patch_mark_read(
    payload: NotificationReadPatchRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mark notifications as read using PATCH semantics.
    - mark_all=true marks all unread notifications.
    - notification_ids=[...] marks selected notifications.
    """
    if payload.mark_all:
        return NotificationService.mark_all_as_read(db, current_user["user_id"])
    return NotificationService.mark_selected_as_read(db, current_user["user_id"], payload.notification_ids or [])


@router.put("/{notification_id}", response_model=NotificationResponse)
def update_notification(
    notification_id: int,
    update_data: NotificationAdminUpdate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Update notification details (Admin only).
    """
    _ = current_user
    return NotificationService.update_notification(db, notification_id, update_data)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(
    notification_id: int,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Delete a notification (Admin only).
    """
    _ = current_user
    NotificationService.delete_notification(db, notification_id)