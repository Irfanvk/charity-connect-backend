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
    db = SessionLocal()
    now = now_business()
    month_label = now.strftime("%B %Y")

    sent = 0
    try:
        if not get_setting(db, "monthly_reminder_enabled"):
            return {"status": "skipped", "reason": "disabled"}
        if now.day != get_setting(db, "monthly_reminder_day"):
            return {"status": "skipped", "reason": "not reminder day"}

        members = (
            db.query(Member)
            .join(User, Member.user_id == User.id)
            .filter(User.is_active == True)
            .all()
        )

        for member in members:
            if member.monthly_amount is None or float(member.monthly_amount) <= 0:
                continue

            reminder_ctx = {
                "member_name": member.full_name or (member.user.full_name if member.user else "") or "",
                "month": month_label,
                "amount": member.monthly_amount,
            }
            if member.user_id:
                NotificationService.create_user_notification(
                    db=db,
                    user_id=member.user_id,
                    title="Monthly payment reminder",
                    message=with_islamic_greeting(render_message(db, "msg_monthly_reminder", reminder_ctx)),
                    target_role="member",
                    ntype="payment",
                    category="reminders",
                    link_url="/Challans",
                )
            sent += 1

            if member.user and member.user.phone:
                send_whatsapp_message(
                    member.user.phone,
                    with_islamic_greeting(
                        f"{org_name(db)} reminder: your monthly membership amount "
                        f"for {month_label} is {member.monthly_amount}."
                    ),
                )

        return {"status": "ok", "sent": sent}
    finally:
        db.close()
