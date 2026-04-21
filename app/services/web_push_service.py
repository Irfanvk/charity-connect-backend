import json
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import PushSubscription, Notification

try:
    from pywebpush import webpush, WebPushException
except Exception:
    webpush = None
    WebPushException = Exception


class WebPushService:
    @staticmethod
    def _enabled() -> bool:
        return bool(settings.web_push_configured and webpush is not None)

    @staticmethod
    def upsert_subscription(
        db: Session,
        user_id: int,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str = "",
    ) -> dict:
        existing = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
        if existing:
            existing.user_id = user_id
            existing.p256dh = p256dh
            existing.auth = auth
            existing.user_agent = user_agent or existing.user_agent
            existing.is_active = True
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return {"status": "updated", "endpoint": existing.endpoint, "is_active": existing.is_active}

        subscription = PushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
            is_active=True,
        )
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
        return {"status": "created", "endpoint": subscription.endpoint, "is_active": subscription.is_active}

    @staticmethod
    def deactivate_subscription(db: Session, user_id: int, endpoint: str) -> int:
        updated = (
            db.query(PushSubscription)
            .filter(
                PushSubscription.user_id == user_id,
                PushSubscription.endpoint == endpoint,
                PushSubscription.is_active == True,
            )
            .update({"is_active": False}, synchronize_session=False)
        )
        db.commit()
        return int(updated or 0)

    @staticmethod
    def _payload(notification: Notification) -> str:
        payload = {
            "title": notification.title,
            "body": notification.message,
            "tag": f"notification-{notification.id}",
            "data": {
                "notification_id": notification.id,
                "url": "/notifications",
            },
        }
        return json.dumps(payload)

    @staticmethod
    def send_new_notification(db: Session, notification: Notification) -> dict:
        if not WebPushService._enabled():
            return {"sent": 0, "failed": 0, "disabled": True}

        subscriptions = (
            db.query(PushSubscription)
            .filter(
                PushSubscription.user_id == notification.user_id,
                PushSubscription.is_active == True,
            )
            .all()
        )

        sent = 0
        failed = 0
        payload = WebPushService._payload(notification)

        for sub in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {
                            "p256dh": sub.p256dh,
                            "auth": sub.auth,
                        },
                    },
                    data=payload,
                    vapid_private_key=settings.web_push_private_key_value,
                    vapid_claims={"sub": settings.WEB_PUSH_SUBJECT},
                    ttl=120,
                )
                sent += 1
            except WebPushException as exc:
                failed += 1
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code in {404, 410}:
                    sub.is_active = False
                    db.add(sub)
            except Exception:
                failed += 1

        if failed:
            db.commit()

        return {"sent": sent, "failed": failed, "disabled": False}
