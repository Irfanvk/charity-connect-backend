from sqlalchemy.orm import Session
from app.models import Notification, User
from app.schemas import NotificationCreate, NotificationAdminUpdate
from fastapi import HTTPException, status
from datetime import datetime


class NotificationService:
    """Notification service."""

    @staticmethod
    def create_notification(db: Session, notification_data: NotificationCreate, _admin_id: int = None):
        """Create and send notification."""

        if notification_data.user_id:
            # Send to specific user — return the single created notification
            user = db.query(User).filter(User.id == notification_data.user_id).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )

            new_notification = Notification(
                user_id=notification_data.user_id,
                title=notification_data.title,
                message=notification_data.message,
            )
            db.add(new_notification)
            db.commit()
            db.refresh(new_notification)
            return {"sent_count": 1, "message": "Notification sent successfully"}

        elif notification_data.target_role:
            # Send to all users with specific role
            users = db.query(User).filter(User.role == notification_data.target_role).all()
            if not users:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No users found with role '{notification_data.target_role}'",
                )

            for user in users:
                db.add(Notification(
                    user_id=user.id,
                    title=notification_data.title,
                    message=notification_data.message,
                ))

            db.commit()
            return {"sent_count": len(users), "message": "Notifications sent successfully"}

        else:
            # Send to all users
            users = db.query(User).all()

            for user in users:
                db.add(Notification(
                    user_id=user.id,
                    title=notification_data.title,
                    message=notification_data.message,
                ))

            db.commit()
            return {"sent_count": len(users), "message": "Notifications sent successfully"}

    @staticmethod
    def get_notification_by_id(db: Session, notification_id: int, user_id: int):
        """Get a single notification by ID, scoped to the requesting user."""
        notification = db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        ).first()

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        return notification

    @staticmethod
    def update_notification(db: Session, notification_id: int, update_data: NotificationAdminUpdate):
        """Update notification (admin use-case)."""
        notification = db.query(Notification).filter(Notification.id == notification_id).first()

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        update_fields = update_data.dict(exclude_unset=True)
        for key, value in update_fields.items():
            setattr(notification, key, value)

        if update_fields.get("is_read") is True and notification.read_at is None:
            notification.read_at = datetime.utcnow()
        if update_fields.get("is_read") is False:
            notification.read_at = None

        db.commit()
        db.refresh(notification)
        return notification

    @staticmethod
    def delete_notification(db: Session, notification_id: int):
        """Delete notification (admin use-case)."""
        notification = db.query(Notification).filter(Notification.id == notification_id).first()

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        db.delete(notification)
        db.commit()
        # No return — caller uses 204 No Content

    @staticmethod
    def get_user_notifications(db: Session, user_id: int, skip: int = 0, limit: int = 50):
        """Get notifications for user."""
        return (
            db.query(Notification)
            .filter(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_unread_notifications_count(db: Session, user_id: int):
        """Get count of unread notifications using SQL COUNT — no records loaded into memory."""
        return (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.is_read == False,
            )
            .count()
        )

    @staticmethod
    def mark_as_read(db: Session, notification_id: int, user_id: int):
        """Mark notification as read, scoped to the requesting user."""
        notification = db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == user_id,  # ownership check
        ).first()

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        if notification.is_read:
            return notification  # already read, no unnecessary write

        notification.is_read = True
        notification.read_at = datetime.utcnow()

        db.commit()
        db.refresh(notification)
        return notification

    @staticmethod
    def mark_all_as_read(db: Session, user_id: int):
        """Mark all unread notifications as read using a bulk update."""
        now = datetime.utcnow()

        updated_count = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.is_read == False,
            )
            .update({"is_read": True, "read_at": now}, synchronize_session=False)
        )

        db.commit()
        return {"marked_read": updated_count, "message": f"Marked {updated_count} notifications as read"}