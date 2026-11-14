"""Monthly payment reminders, one day per member.

Each member gets a reminder on their chosen day (1-28, default: the
organisation's ``monthly_reminder_day``) unless this month is already paid or
submitted, plus one follow-up 7 days later if still unpaid. Every reminder sent
is logged with a unique (member, month, kind) row, so repeated runs, restarts
and several server workers can never send the same reminder twice.

The schedule runs inside the API process (no Celery needed on the server); the
Celery beat task, if someone runs it, calls the same function.
"""
from __future__ import annotations

import asyncio
import calendar
import logging
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.notification_prefs import uses_simple_settings
from app.models import Challan, Member, Notification, PaymentReminderLog, User
from app.models.models import ChallanStatus, ChallanType
from app.services.notification_service import NotificationService
from app.services.settings_service import get_setting, org_name, render_message
from app.utils.message_format import with_islamic_greeting
from app.utils.timezone import now_business

logger = logging.getLogger(__name__)

FIRST = "first"
FOLLOW_UP = "follow_up"
MIN_DAY, MAX_DAY = 1, 28
CATCH_UP_DAYS = 2          # still send up to 2 days late (e.g. the server was down)
FOLLOW_UP_AFTER_DAYS = 7
MIN_GAP_DAYS = 3           # never two reminders closer than this
SEND_FROM_HOUR = 9         # IST
CHECK_EVERY_SECONDS = 30 * 60
PAID_STATUSES = (ChallanStatus.APPROVED, ChallanStatus.PENDING)


def clamp_day(value) -> int:
    try:
        day = int(value)
    except (TypeError, ValueError):
        day = MIN_DAY
    return max(MIN_DAY, min(MAX_DAY, day))


def reminder_enabled(user: User) -> bool:
    if uses_simple_settings(user):
        return True  # admins have no reminder choices; they always get them
    return user.payment_reminder_enabled is not False  # NULL = on by default


def reminder_day(db: Session, user: User) -> int:
    if user.payment_reminder_day and not uses_simple_settings(user):
        return clamp_day(user.payment_reminder_day)
    return clamp_day(get_setting(db, "monthly_reminder_day"))


def preferences_for(db: Session, user: User) -> dict:
    member = user.member
    return {
        "enabled": reminder_enabled(user),
        "day": reminder_day(db, user),
        "uses_default_day": not user.payment_reminder_day,
        "default_day": clamp_day(get_setting(db, "monthly_reminder_day")),
        "applies": bool(member and (member.monthly_amount or 0) > 0),
        "organisation_enabled": bool(get_setting(db, "monthly_reminder_enabled")),
    }


def save_preferences(user: User, enabled: bool | None = None, day: int | None = None) -> None:
    if enabled is not None:
        user.payment_reminder_enabled = bool(enabled)
    if day is not None:
        if not MIN_DAY <= int(day) <= MAX_DAY:
            raise ValueError("Reminder day must be between 1 and 28.")
        user.payment_reminder_day = int(day)


def _month_paid(db: Session, member_id: int, month: str) -> bool:
    """Approved, or pending with something actually handed in (see challan_state)."""
    from app.services.challan_state import submitted_clause

    return db.query(Challan.id).filter(
        Challan.member_id == member_id,
        Challan.type == ChallanType.MONTHLY,
        Challan.month == month,
        Challan.status.in_(PAID_STATUSES),
        submitted_clause(),
    ).first() is not None


def _format_amount(amount) -> str:
    value = float(amount or 0)
    return f"₹{value:,.0f}" if value.is_integer() else f"₹{value:,.2f}"


def _send(db: Session, member: Member, user: User, month: str, month_label: str, kind: str) -> bool:
    """Log + create the notification in one transaction. False if it was already sent."""
    ctx = {
        "member_name": member.full_name or user.full_name or "",
        "month": month_label,
        "amount": _format_amount(member.monthly_amount),
    }
    if kind == FIRST:
        title = "Monthly payment reminder"
        body = render_message(db, "msg_monthly_reminder", ctx)
    else:
        title = "Gentle reminder: payment still due"
        body = render_message(db, "msg_monthly_reminder_followup", ctx)

    notification = Notification(
        user_id=user.id,
        title=title,
        message=with_islamic_greeting(body),
        target_role=user.role,
        type="payment",
        category="reminders",
        link_url="/Challans",
    )
    db.add(PaymentReminderLog(member_id=member.id, user_id=user.id, month=month, kind=kind))
    db.add(notification)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # another worker/run already sent it
        return False
    db.refresh(notification)
    try:
        NotificationService.dispatch_notification(db, notification)
    except Exception:
        logger.exception("Push for payment reminder %s failed", notification.id)

    if kind == FIRST and user.phone:
        try:
            from app.services.whatsapp_service import send_whatsapp_message  # no-op unless WhatsApp is enabled
            send_whatsapp_message(user.phone, f"{org_name(db)}: {body}")
        except Exception:
            logger.exception("WhatsApp payment reminder failed for user %s", user.id)
    return True


def run_due_reminders(db: Session, today: date) -> dict:
    """Send every reminder due on ``today`` (an IST date). Safe to call any number of times."""
    if not get_setting(db, "monthly_reminder_enabled"):
        return {"status": "skipped", "reason": "disabled"}

    month = today.strftime("%Y-%m")
    month_label = today.strftime("%B %Y")
    last_day = calendar.monthrange(today.year, today.month)[1]
    default_day = clamp_day(get_setting(db, "monthly_reminder_day"))

    sent_logs = {
        (row.member_id, row.kind): row.sent_at
        for row in db.query(PaymentReminderLog).filter(PaymentReminderLog.month == month).all()
    }
    rows = (
        db.query(Member, User)
        .join(User, Member.user_id == User.id)
        .filter(User.is_active == True, Member.monthly_amount > 0)  # noqa: E712
        .all()
    )

    counts = {"status": "ok", "first": 0, "follow_up": 0, "skipped_paid": 0}
    for member, user in rows:
        if not reminder_enabled(user):
            continue
        day = clamp_day(user.payment_reminder_day) if user.payment_reminder_day else default_day
        first_sent = sent_logs.get((member.id, FIRST))

        if first_sent is None:
            if day <= today.day <= day + CATCH_UP_DAYS:
                if _month_paid(db, member.id, month):
                    counts["skipped_paid"] += 1
                elif _send(db, member, user, month, month_label, FIRST):
                    counts["first"] += 1
            continue

        if (member.id, FOLLOW_UP) in sent_logs:
            continue
        follow_up_day = min(day + FOLLOW_UP_AFTER_DAYS, last_day)
        first_sent_day = first_sent.date() if hasattr(first_sent, "date") else first_sent
        if (
            follow_up_day <= today.day <= follow_up_day + CATCH_UP_DAYS
            and (today - first_sent_day).days >= MIN_GAP_DAYS
        ):
            if _month_paid(db, member.id, month):
                counts["skipped_paid"] += 1
            elif _send(db, member, user, month, month_label, FOLLOW_UP):
                counts["follow_up"] += 1
    return counts


def run_for_now() -> dict:
    """Run for the current IST date, from its own DB session."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return run_due_reminders(db, now_business().date())
    finally:
        db.close()


async def reminder_scheduler_loop() -> None:
    """Checks every 30 minutes; sends from 09:00 IST. Started from the API's startup hook."""
    await asyncio.sleep(60)
    while True:
        try:
            if now_business().hour >= SEND_FROM_HOUR:
                result = await asyncio.to_thread(run_for_now)
                if result.get("first") or result.get("follow_up"):
                    logger.info("Payment reminders sent: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Payment reminder run failed")
        await asyncio.sleep(CHECK_EVERY_SECONDS)
