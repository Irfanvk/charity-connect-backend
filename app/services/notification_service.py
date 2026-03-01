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
            # Send to specific user
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
        
        elif notification_data.target_role:
            # Send to all users with specific role
            users = db.query(User).filter(User.role == notification_data.target_role).all()
            
            for user in users:
                new_notification = Notification(
                    user_id=user.id,
                    title=notification_data.title,
                    message=notification_data.message,
                    target_role=notification_data.target_role,
                )
                db.add(new_notification)
        
        else:
            # Send to all users
            users = db.query(User).all()
            
            for user in users:
                new_notification = Notification(
                    user_id=user.id,
                    title=notification_data.title,
                    message=notification_data.message,
                )
                db.add(new_notification)
        
        db.commit()
        
        return {"message": "Notification sent successfully"}

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
        return {"message": "Notification deleted"}
    
    @staticmethod
    def get_user_notifications(db: Session, user_id: int, skip: int = 0, limit: int = 50):
        """Get notifications for user."""
        return db.query(Notification).filter(
            Notification.user_id == user_id
        ).order_by(Notification.created_at.desc()).offset(skip).limit(limit).all()
    
    @staticmethod
    def get_unread_notifications_count(db: Session, user_id: int):
        """Get count of unread notifications."""
        return db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.is_read == False,
        ).count()
    
    @staticmethod
    def mark_as_read(db: Session, notification_id: int):
        """Mark notification as read."""
        notification = db.query(Notification).filter(Notification.id == notification_id).first()
        
        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )
        
        notification.is_read = True
        notification.read_at = datetime.utcnow()
        
        db.commit()
        db.refresh(notification)
        
        return notification
    
    @staticmethod
    def mark_all_as_read(db: Session, user_id: int):
        """Mark all notifications as read for user."""
        notifications = db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.is_read == False,
        ).all()
        
        for notification in notifications:
            notification.is_read = True
            notification.read_at = datetime.utcnow()
        
        db.commit()
        
        return {"message": f"Marked {len(notifications)} notifications as read"}
