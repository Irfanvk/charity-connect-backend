from sqlalchemy.orm import Session
from app.models import Notification, User
from app.schemas import NotificationCreate, NotificationAdminUpdate
from fastapi import HTTPException, status
from datetime import datetime, timedelta


class NotificationService:
    """Notification service."""

    @staticmethod
    def create_notification(db: Session, notification_data: NotificationCreate, _admin_id: int = None):
        """Create and send notification."""

        batch_created_at = datetime.utcnow()
        recipient_ids = set()
        admin_copy_included = False

        def queue_notification(user_id: int):
            recipient_ids.add(user_id)
            db.add(Notification(
                user_id=user_id,
                title=notification_data.title,
                message=notification_data.message,
                target_role=notification_data.target_role,
                created_at=batch_created_at,
            ))

        if notification_data.user_id:
            # Send to specific user — return the single created notification
            user = db.query(User).filter(User.id == notification_data.user_id).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )

            queue_notification(notification_data.user_id)

        elif notification_data.target_role:
            # Send to all users with specific role
            users = db.query(User).filter(User.role == notification_data.target_role).all()
            if not users:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No users found with role '{notification_data.target_role}'",
                )

            for user in users:
                queue_notification(user.id)

        else:
            # Send to all users
            users = db.query(User).all()

            for user in users:
                queue_notification(user.id)

        # Ensure the sending admin always sees newly sent notifications.
        if _admin_id and _admin_id not in recipient_ids:
            admin_user = db.query(User).filter(User.id == _admin_id, User.is_active == True).first()
            if admin_user:
                queue_notification(_admin_id)
                admin_copy_included = True

        db.commit()
        return {
            "sent_count": len(recipient_ids),
            "message": "Notifications sent successfully",
            "batch_created_at": batch_created_at.isoformat(),
            "admin_copy_included": admin_copy_included,
        }

    @staticmethod
    def get_admin_sent_notifications(
        db: Session,
        minutes: int = 10080,
        audience_filter: str = "all",
        skip: int = 0,
        limit: int = 50,
    ):
        """List grouped sent-notification batches for admin panel with audience diagnostics."""

        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        query = (
            db.query(Notification, User.role)
            .join(User, Notification.user_id == User.id)
            .filter(Notification.created_at >= cutoff)
        )

        if audience_filter == "members":
            query = query.filter(User.role == "member")
        elif audience_filter == "admins":
            query = query.filter(User.role.in_(["admin", "superadmin"]))
        elif audience_filter == "superadmins":
            query = query.filter(User.role == "superadmin")

        rows = query.order_by(Notification.created_at.desc()).all()

        groups = {}
        for notif, role in rows:
            key = (notif.created_at, notif.title, notif.message, notif.target_role)
            if key not in groups:
                groups[key] = {
                    "batch_created_at": notif.created_at,
                    "title": notif.title,
                    "message": notif.message,
                    "target_role": notif.target_role,
                    "total_recipients": 0,
                    "member_recipients": 0,
                    "admin_recipients": 0,
                    "superadmin_recipients": 0,
                    "unread_count": 0,
                }

            batch = groups[key]
            batch["total_recipients"] += 1
            if str(role).lower() == "member":
                batch["member_recipients"] += 1
            elif str(role).lower() == "admin":
                batch["admin_recipients"] += 1
            elif str(role).lower() == "superadmin":
                batch["superadmin_recipients"] += 1

            if not notif.is_read:
                batch["unread_count"] += 1

        grouped = list(groups.values())
        grouped.sort(key=lambda item: item["batch_created_at"], reverse=True)

        for item in grouped:
            members = item["member_recipients"]
            admins = item["admin_recipients"] + item["superadmin_recipients"]
            if members > 0 and admins == 0:
                item["audience_label"] = "members-only"
            elif members == 0 and admins > 0:
                item["audience_label"] = "admins-only"
            elif members > 0 and admins > 0:
                item["audience_label"] = "all/mixed"
            else:
                item["audience_label"] = "unknown"

        return grouped[skip: skip + limit]

    @staticmethod
    def delete_admin_sent_notifications(
        db: Session,
        batch_created_at: datetime,
        title: str,
        message: str,
        recipient_scope: str = "all",
    ):
        """Delete sent notifications for a specific batch, with recipient scope filter."""

        query = db.query(Notification).filter(
            Notification.created_at == batch_created_at,
            Notification.title == title,
            Notification.message == message,
        )

        if recipient_scope == "members":
            member_ids = db.query(User.id).filter(User.role == "member")
            query = query.filter(Notification.user_id.in_(member_ids))
        elif recipient_scope == "admins":
            admin_ids = db.query(User.id).filter(User.role.in_(["admin", "superadmin"]))
            query = query.filter(Notification.user_id.in_(admin_ids))
        elif recipient_scope == "superadmins":
            superadmin_ids = db.query(User.id).filter(User.role == "superadmin")
            query = query.filter(Notification.user_id.in_(superadmin_ids))

        deleted_count = query.delete(synchronize_session=False)
        db.commit()

        return {
            "deleted_count": deleted_count,
            "message": f"Deleted {deleted_count} notifications",
        }

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