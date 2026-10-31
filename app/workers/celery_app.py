from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.workers.runtime import celery_result_backend_url


result_backend_url = celery_result_backend_url()

celery = Celery(
    "charityhub",
    broker=settings.CELERY_BROKER_URL,
    backend=result_backend_url,
)

celery.conf.update(
    # Beat schedules (crontab) are evaluated in IST; timestamps stay UTC (enable_utc).
    timezone=settings.BUSINESS_TIMEZONE,
    enable_utc=True,
    task_default_queue="default",
    task_ignore_result=result_backend_url is None,
    task_store_errors_even_if_ignored=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=45,
    task_time_limit=60,
)

celery.conf.task_routes = {
    "app.workers.tasks.send_web_push_notification": {"queue": "notifications"},
    "app.workers.tasks.send_invite_message": {"queue": "notifications"},
    "app.workers.tasks.send_user_notification": {"queue": "notifications"},
    "app.workers.tasks.send_welcome_notification": {"queue": "notifications"},
    "app.workers.tasks.send_monthly_membership_reminders": {"queue": "notifications"},
}

# Reminder task runs DAILY at 09:00 IST; the task itself exits unless today (IST)
# equals the monthly_reminder_day setting and reminders are enabled.
celery.conf.beat_schedule = {
    "monthly-membership-reminder": {
        "task": "app.workers.tasks.send_monthly_membership_reminders",
        "schedule": crontab(minute=0, hour=9),
    }
}

celery.autodiscover_tasks(["app.workers"])
