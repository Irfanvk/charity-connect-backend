from datetime import datetime

from app.database import SessionLocal
from app.models import Member, Notification, User
from app.services.notification_service import NotificationService
from app.services.settings_service import get_setting, org_name, render_message, welcome_content
from app.services.web_push_service import WebPushService
from app.services.whatsapp_service import send_whatsapp_message
from app.utils.invite_share import build_invite_share_message
from app.utils.message_format import with_islamic_greeting
from app.utils.timezone import now_business
from app.workers.celery_app import celery


WELCOME_MESSAGE = with_islamic_greeting(
    "Your account is ready. Complete your profile and begin your charity journey."
)


@celery.task(name="app.workers.tasks.send_invite_message", ignore_result=True)
def send_invite_message(phone: str, invite_code: str, expiry_date: str | None = None):
    parsed_expiry_date = None
    if expiry_date:
        try:
            parsed_expiry_date = datetime.fromisoformat(expiry_date)
        except ValueError:
            parsed_expiry_date = None

    db = SessionLocal()
    try:
        message = build_invite_share_message(invite_code, parsed_expiry_date, db)
    finally:
        db.close()

    send_whatsapp_message(phone, message)


@celery.task(
    bind=True,
    name="app.workers.tasks.send_web_push_notification",
    autoretry_for=(OSError, TimeoutError, ConnectionError),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    ignore_result=True,
)
def send_web_push_notification(self, notification_id: int):
    """Deliver a persisted notification outside the API request lifecycle."""
    db = SessionLocal()
    try:
        notification = db.query(Notification).filter(Notification.id == notification_id).first()
        if not notification:
            return {"status": "skipped", "reason": "notification_not_found"}
        return WebPushService.send_new_notification(db=db, notification=notification)
    finally:
        db.close()


@celery.task(name="app.workers.tasks.send_user_notification", ignore_result=True)
def send_user_notification(
    user_id: int,
    title: str,
    message: str,
    target_role: str | None = None,
    category: str | None = None,
    link_url: str | None = None,
):
    db = SessionLocal()
    try:
        NotificationService.create_user_notification(
            db=db,
            user_id=user_id,
            title=title,
            message=message,
            target_role=target_role,
            category=category,
            link_url=link_url,
        )
    finally:
        db.close()


@celery.task(name="app.workers.tasks.send_welcome_notification", ignore_result=True)
def send_welcome_notification(user_id: int):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"status": "skipped", "reason": "user_not_found", "user_id": user_id}

        title, message = welcome_content(db, user.full_name)
        NotificationService.create_user_notification(
            db=db,
            user_id=user.id,
            title=title,
            message=message,
            target_role=user.role,
            category="announcements",
            link_url="/Notifications",
        )

        return {"status": "ok", "user_id": user.id}
    finally:
        db.close()


@celery.task(name="app.workers.tasks.send_monthly_membership_reminders", ignore_result=True)
def send_monthly_membership_reminders():
    """Kept for Celery beat setups; the API process runs the same schedule by itself."""
    from app.services.payment_reminder_service import run_due_reminders

    db = SessionLocal()
    try:
        return run_due_reminders(db, now_business().date())
    finally:
        db.close()
