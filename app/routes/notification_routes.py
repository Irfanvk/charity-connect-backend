from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import NotificationCreate, NotificationResponse, NotificationAdminUpdate
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
    """
    return NotificationService.create_notification(db, notification_data, current_user["user_id"])


@router.post("/send", status_code=status.HTTP_201_CREATED, deprecated=True)
def create_notification_legacy(
    notification_data: NotificationCreate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Deprecated alias for notification creation.
    Use POST /notifications/ instead.
    """
    return NotificationService.create_notification(db, notification_data, current_user["user_id"])


@router.get("/", response_model=List[NotificationResponse])
def get_my_notifications(
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get current user's notifications.
    """
    notifications = NotificationService.get_user_notifications(db, current_user["user_id"], skip, limit)
    return notifications


@router.get("/unread/count")
def get_unread_count(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get count of unread notifications.
    """
    count = NotificationService.get_unread_notifications_count(db, current_user["user_id"])
    return {"unread_count": count}


@router.put("/{notification_id}/read", response_model=NotificationResponse)
def mark_as_read(
    notification_id: int,
    _current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mark notification as read.
    """
    notification = NotificationService.mark_as_read(db, notification_id)
    return notification


@router.post("/mark-all-read")
def mark_all_as_read(
    _current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mark all notifications as read.
    """
    return NotificationService.mark_all_as_read(db, _current_user["user_id"])


@router.put("/{notification_id}", response_model=NotificationResponse)
def update_notification(
    notification_id: int,
    update_data: NotificationAdminUpdate,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Update notification details (Admin only).
    """
    return NotificationService.update_notification(db, notification_id, update_data)


@router.delete("/{notification_id}")
def delete_notification(
    notification_id: int,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Delete notification (Admin only).
    """
    return NotificationService.delete_notification(db, notification_id)
