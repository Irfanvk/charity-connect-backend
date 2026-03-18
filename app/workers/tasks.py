from datetime import datetime

from app.database import SessionLocal
from app.models import Member, User
from app.services.notification_service import NotificationService
from app.services.whatsapp_service import send_whatsapp_message
from app.workers.celery_app import celery


@celery.task(name="app.workers.tasks.send_invite_message")
def send_invite_message(phone: str, invite_code: str):
    message = f"""
Assalamu Alaikum

You are invited to join CharityHub.

Invite Code: {invite_code}
""".strip()

    send_whatsapp_message(phone, message)


@celery.task(name="app.workers.tasks.send_user_notification")
def send_user_notification(user_id: int, title: str, message: str, target_role: str | None = None):
    db = SessionLocal()
    try:
        NotificationService.create_user_notification(
            db=db,
            user_id=user_id,
            title=title,
            message=message,
            target_role=target_role,
        )
    finally:
        db.close()


@celery.task(name="app.workers.tasks.send_welcome_notification")
def send_welcome_notification(user_id: int):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"status": "skipped", "reason": "user_not_found", "user_id": user_id}

        NotificationService.create_user_notification(
            db=db,
            user_id=user.id,
            title="Welcome to CharityHub",
            message="Your account is ready. Complete your profile and begin your charity journey.",
            target_role=user.role,
        )

        return {"status": "ok", "user_id": user.id}
    finally:
        db.close()


@celery.task(name="app.workers.tasks.send_monthly_membership_reminders")
def send_monthly_membership_reminders():
    db = SessionLocal()
    now = datetime.utcnow()
    month_label = now.strftime("%B %Y")

    sent = 0
    try:
        members = (
            db.query(Member)
            .join(User, Member.user_id == User.id)
            .filter(User.is_active == True)
            .all()
        )

        for member in members:
            if member.monthly_amount is None or float(member.monthly_amount) <= 0:
                continue

            NotificationService.create_user_notification(
                db=db,
                user_id=member.user_id,
                title="Monthly Membership Reminder",
                message=(
                    f"Your monthly membership contribution for {month_label} is due. "
                    f"Amount: {member.monthly_amount}."
                ),
                target_role="member",
            )
            sent += 1

            if member.user and member.user.phone:
                send_whatsapp_message(
                    member.user.phone,
                    (
                        f"CharityHub reminder: your monthly membership amount "
                        f"for {month_label} is {member.monthly_amount}."
                    ),
                )

        return {"status": "ok", "sent": sent}
    finally:
        db.close()
