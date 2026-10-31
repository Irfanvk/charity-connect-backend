from sqlalchemy.orm import Session
from kombu.exceptions import OperationalError
import json
import logging
from app.models import Notification, User
from app.models.models import UserRole
from app.schemas import NotificationCreate, NotificationAdminUpdate
from app.services.realtime_notification_service import notification_realtime_hub
from app.services.settings_service import render_message
from app.services.web_push_service import WebPushService
from app.workers.runtime import can_enqueue_celery_tasks
from fastapi import HTTPException, status
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)


class NotificationService:
    """Notification service."""

    @staticmethod
    def _serialize_event(notification: Notification) -> dict:
        return {
            "id": notification.id,
            "user_id": notification.user_id,
            "title": notification.title,
            "message": notification.message,
            "is_read": bool(notification.is_read),
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
            "read_at": notification.read_at.isoformat() if notification.read_at else None,
            "target_role": notification.target_role.value if hasattr(notification.target_role, "value") else notification.target_role,
        }

    @staticmethod
    def dispatch_notification(db: Session, notification: Notification) -> None:
        """Fan out a newly created notification to realtime and web push channels."""
        try:
            payload = NotificationService._serialize_event(notification)
            notification_realtime_hub.publish_event(
                user_id=notification.user_id,
                event={"type": "create", "data": payload},
            )
        except Exception:
            # Realtime delivery must not affect persisted notification records.
            pass

        try:
            if can_enqueue_celery_tasks():
                from app.workers.tasks import send_web_push_notification

                send_web_push_notification.delay(notification.id)
            else:
                WebPushService.send_new_notification(db=db, notification=notification)
        except Exception:
            # Push delivery must not affect persisted notification records.
            pass

    @staticmethod
    def create_user_notification(
        db: Session,
        user_id: int,
        title: str,
        message: str,
        target_role: str | None = None,
    ):
        """Create a direct notification for a single user."""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        normalized_role = target_role or user.role
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            target_role=normalized_role,
        )

        db.add(notification)
        db.commit()
        db.refresh(notification)
        NotificationService.dispatch_notification(db, notification)
        return notification

    @staticmethod
    def enqueue_user_notification(
        user_id: int,
        title: str,
        message: str,
        target_role: str | None = None,
    ) -> dict:
        """Queue notification creation via Celery with safe fallback."""
        if not can_enqueue_celery_tasks():
            return {"queued": False, "worker": "fallback"}

        try:
            from app.workers.tasks import send_user_notification

            send_user_notification.delay(user_id, title, message, target_role)
            return {"queued": True, "worker": "celery"}
        except (ImportError, OperationalError, OSError, RuntimeError):
            # Keep API behavior resilient even if worker is unavailable.
            return {"queued": False, "worker": "fallback"}

    # ------------------------------------------------------------------
    # Challan status notifications
    # ------------------------------------------------------------------
    @staticmethod
    def _format_inr(amount) -> str:
        """Format with Indian digit grouping, e.g. 1500000 -> 15,00,000."""
        value = float(amount or 0)
        whole, _, frac = f"{abs(value):.2f}".partition(".")
        if len(whole) > 3:
            head, tail = whole[:-3], whole[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            if head:
                groups.insert(0, head)
            whole = ",".join(groups + [tail])
        text = whole if frac == "00" else f"{whole}.{frac}"
        return f"₹{'-' if value < 0 else ''}{text}"

    @staticmethod
    def _format_month(month: str | None) -> str:
        """'2026-10' -> 'Oct 2026'; unknown formats are returned unchanged."""
        try:
            return datetime.strptime(month, "%Y-%m").strftime("%b %Y")
        except (TypeError, ValueError):
            return month or "the selected month"

    @staticmethod
    def _format_month_range(months: list[str]) -> str:
        valid = sorted(m for m in months if m)
        if not valid:
            return "the selected months"
        first, last = valid[0], valid[-1]
        if first == last:
            return NotificationService._format_month(first)
        try:
            start = datetime.strptime(first, "%Y-%m")
            end = datetime.strptime(last, "%Y-%m")
        except ValueError:
            return f"{first}–{last}"
        if start.year == end.year:
            return f"{start.strftime('%b')}–{end.strftime('%b %Y')}"
        return f"{start.strftime('%b %Y')}–{end.strftime('%b %Y')}"

    @staticmethod
    def _send_status_notification(db: Session, user_id: int, title: str, message: str, ntype: str) -> None:
        """Persist then dispatch. Never raises: failures are logged only."""
        try:
            notification = Notification(user_id=user_id, title=title, message=message, type=ntype)
            db.add(notification)
            db.commit()
            db.refresh(notification)
        except Exception:
            logger.exception("Failed to create challan notification for user %s", user_id)
            try:
                db.rollback()
            except Exception:
                pass
            return
        try:
            NotificationService.dispatch_notification(db, notification)
        except Exception:
            logger.exception("Failed to dispatch challan notification %s", notification.id)

    @staticmethod
    def _status_content(event: str, subject: str, reason: str | None, db: Session | None = None, context: dict | None = None) -> tuple[str, str, str]:
        reason_text = (reason or "").strip() or "No reason provided"
        ctx = {**(context or {}), "payment": subject, "reason": reason_text}
        if event == "approved":
            if db is not None:
                return "Payment approved", render_message(db, "msg_payment_approved", ctx), "success"
            return "Payment approved", f"Your {subject} has been approved.", "success"
        if event == "rejected":
            if db is not None:
                return "Payment rejected", render_message(db, "msg_payment_rejected", ctx), "warning"
            return (
                "Payment rejected",
                f"Your {subject} was rejected. Reason: {reason_text}. "
                "Please re-upload your payment proof from the Challans page.",
                "warning",
            )
        if event == "reverted":
            return (
                "Payment status changed",
                f"Your {subject} is back under review. Reason: {reason_text}.",
                "warning",
            )
        raise ValueError(f"Unknown challan event: {event}")

    @staticmethod
    def notify_challan_status_change(db: Session, challan, event: str, reason: str | None = None, actor_name: str | None = None) -> None:
        """Notify the member that their challan was approved/rejected/reverted. Never raises."""
        try:
            member = challan.member
            user_id = getattr(member, "user_id", None)
            if not user_id:
                return

            amount = NotificationService._format_inr(challan.amount)
            type_value = getattr(challan.type, "value", challan.type)
            if type_value == "campaign" and challan.campaign is not None:
                subject = f"donation of {amount} to {challan.campaign.title}"
            else:
                subject = f"monthly payment for {NotificationService._format_month(challan.month)} ({amount})"

            title, message, ntype = NotificationService._status_content(
                event, subject, reason, db,
                {
                    "member_name": getattr(member, "full_name", None) or getattr(getattr(member, "user", None), "full_name", None) or "",
                    "month": NotificationService._format_month(challan.month),
                    "amount": amount,
                },
            )
            if actor_name and event != "approved":
                message += f" (by {actor_name})"
        except Exception:
            logger.exception("Failed to build challan notification")
            return
        NotificationService._send_status_notification(db, user_id, title, message, ntype)

    @staticmethod
    def notify_bulk_status_change(db: Session, bulk_group, event: str, reason: str | None = None) -> None:
        """Send ONE notification for a whole bulk group. Never raises."""
        try:
            user_id = getattr(bulk_group.member, "user_id", None)
            if not user_id:
                return
            months = json.loads(bulk_group.months_list) if bulk_group.months_list else []
            count = len(months)
            subject = (
                f"payment for {count} month{'s' if count != 1 else ''} "
                f"({NotificationService._format_month_range(months)}, "
                f"{NotificationService._format_inr(bulk_group.total_amount)})"
            )
            title, message, ntype = NotificationService._status_content(
                event, subject, reason, db,
                {
                    "member_name": getattr(bulk_group.member, "full_name", None) or "",
                    "month": NotificationService._format_month_range(months),
                    "amount": NotificationService._format_inr(bulk_group.total_amount),
                },
            )
        except Exception:
            logger.exception("Failed to build bulk challan notification")
            return
        NotificationService._send_status_notification(db, user_id, title, message, ntype)

    @staticmethod
    def _active_admin_ids(db: Session, exclude_user_id: int | None = None) -> list[int]:
        """Ids of active admins/superadmins, optionally excluding one user."""
        query = db.query(User.id).filter(
            User.role.in_([UserRole.ADMIN, UserRole.SUPERADMIN]),
            User.is_active == True,
        )
        if exclude_user_id is not None:
            query = query.filter(User.id != exclude_user_id)
        return [row[0] for row in query.all()]

    @staticmethod
    def notify_admins_proof_uploaded(
        db: Session, member, months: list[str], uploader_user_id: int | None = None
    ) -> None:
        """One in-app notification per active admin/superadmin (except the uploader) per upload. Never raises."""
        try:
            name = getattr(member, "full_name", None) or "a member"
            label = NotificationService._format_month_range(months)
            message = f"New payment proof from {name} for {label}"
            owner_id = getattr(member, "user_id", None)
            if owner_id is not None:
                owner_role = db.query(User.role).filter(User.id == owner_id).scalar()
                if owner_role in (UserRole.ADMIN, UserRole.SUPERADMIN):
                    message += " (admin's own payment — please review)"
            admin_ids = NotificationService._active_admin_ids(db, exclude_user_id=uploader_user_id)
        except Exception:
            logger.exception("Failed to build admin proof notification")
            return
        for admin_id in admin_ids:
            NotificationService._send_status_notification(
                db, admin_id, "New payment proof", message, "payment"
            )

    @staticmethod
    def notify_fund_utilization_created(db: Session, utilization) -> None:
        """Ask every OTHER active admin/superadmin to review a new utilization. Never raises."""
        try:
            message = (
                f"Fund utilization of {NotificationService._format_inr(utilization.amount)} "
                f"for {utilization.title} needs your approval"
            )
            admin_ids = NotificationService._active_admin_ids(
                db, exclude_user_id=utilization.registered_by_admin_id
            )
        except Exception:
            logger.exception("Failed to build fund utilization notification")
            return
        for admin_id in admin_ids:
            NotificationService._send_status_notification(
                db, admin_id, "Fund utilization needs approval", message, "info"
            )

    @staticmethod
    def notify_fund_utilization_status_change(db: Session, utilization, event: str, reason: str | None = None) -> None:
        """Tell the creator their utilization was approved/rejected/reverted. Never raises."""
        try:
            user_id = utilization.registered_by_admin_id
            subject = (
                f"fund utilization of {NotificationService._format_inr(utilization.amount)} "
                f"for {utilization.title}"
            )
            reason_text = (reason or "").strip() or "No reason provided"
            if event == "approved":
                title, message, ntype = "Fund utilization approved", f"Your {subject} has been approved.", "success"
            elif event == "rejected":
                title, message, ntype = (
                    "Fund utilization rejected",
                    f"Your {subject} was rejected. Reason: {reason_text}",
                    "warning",
                )
            elif event == "reverted":
                title, message, ntype = (
                    "Fund utilization reverted",
                    f"Your {subject} was moved back to pending. Reason: {reason_text}",
                    "warning",
                )
            else:
                raise ValueError(f"Unknown fund utilization event: {event}")
        except Exception:
            logger.exception("Failed to build fund utilization status notification")
            return
        NotificationService._send_status_notification(db, user_id, title, message, ntype)

    @staticmethod
    def create_notification(db: Session, notification_data: NotificationCreate, _admin_id: int = None):
        """Create and send notification."""

        batch_created_at = datetime.utcnow()
        recipient_ids = set()
        created_notifications = []
        admin_copy_included = False

        def queue_notification(user_id: int):
            recipient_ids.add(user_id)
            notification = Notification(
                user_id=user_id,
                title=notification_data.title,
                message=notification_data.message,
                target_role=notification_data.target_role,
                type=notification_data.type or "info",
                created_at=batch_created_at,
            )
            db.add(notification)
            created_notifications.append(notification)

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
        for notification in created_notifications:
            db.refresh(notification)
            NotificationService.dispatch_notification(db, notification)

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
    def get_user_notification_feed(db: Session, user_id: int, skip: int = 0, limit: int = 50):
        """Frontend-friendly notification feed payload."""
        items = NotificationService.get_user_notifications(db, user_id, skip=skip, limit=limit)
        unread_count = NotificationService.get_unread_notifications_count(db, user_id)
        return {
            "items": items,
            "unread_count": unread_count,
        }

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
        notification_realtime_hub.publish_event(
            user_id=user_id,
            event={"type": "read", "data": {"notification_id": notification.id}},
        )
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
        notification_realtime_hub.publish_event(
            user_id=user_id,
            event={"type": "read_all", "data": {"marked_read": updated_count}},
        )
        return {"marked_read": updated_count, "message": f"Marked {updated_count} notifications as read"}

    @staticmethod
    def mark_selected_as_read(db: Session, user_id: int, notification_ids: list[int]):
        """Mark selected notification ids as read for the requesting user."""
        ids = list({int(item) for item in notification_ids if item is not None})
        if not ids:
            return {"marked_read": 0, "message": "No notifications selected"}

        now = datetime.utcnow()
        updated_count = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.id.in_(ids),
                Notification.is_read == False,
            )
            .update({"is_read": True, "read_at": now}, synchronize_session=False)
        )
        db.commit()
        notification_realtime_hub.publish_event(
            user_id=user_id,
            event={"type": "read_selected", "data": {"marked_read": updated_count}},
        )
        return {"marked_read": updated_count, "message": f"Marked {updated_count} notifications as read"}