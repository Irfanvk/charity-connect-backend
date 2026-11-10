import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import PushSubscription, Notification

try:
    from pywebpush import webpush, WebPushException
except Exception:
    webpush = None
    WebPushException = Exception

logger = logging.getLogger(__name__)

# Push services answer these when the subscription is gone or was made for another key.
DEAD_SUBSCRIPTION_STATUSES = {401, 403, 404, 410}
DEFAULT_LINK = "/notifications"


def device_label_from_user_agent(user_agent: str | None) -> str | None:
    ua = (user_agent or "").lower()
    if not ua:
        return None
    if "iphone" in ua:
        device = "iPhone"
    elif "ipad" in ua:
        device = "iPad"
    elif "android" in ua:
        device = "Android"
    elif "windows" in ua:
        device = "Windows"
    elif "mac os" in ua or "macintosh" in ua:
        device = "Mac"
    elif "linux" in ua:
        device = "Linux"
    else:
        device = "Device"
    if "edg/" in ua:
        browser = "Edge"
    elif "firefox" in ua or "fxios" in ua:
        browser = "Firefox"
    elif "chrome" in ua or "crios" in ua:
        browser = "Chrome"
    elif "safari" in ua:
        browser = "Safari"
    else:
        browser = ""
    return f"{device} {browser}".strip()[:100]


def device_type_from_user_agent(user_agent: str | None) -> str:
    ua = (user_agent or "").lower()
    if "iphone" in ua or "ipad" in ua:
        return "ios"
    if "android" in ua:
        return "android"
    return "desktop"


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
        key_id = settings.vapid_key_id or None
        label = device_label_from_user_agent(user_agent)
        existing = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
        if existing:
            existing.user_id = user_id
            existing.p256dh = p256dh
            existing.auth = auth
            existing.user_agent = user_agent or existing.user_agent
            existing.device_label = label or existing.device_label
            existing.vapid_key_id = key_id
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
            device_label=label,
            vapid_key_id=key_id,
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
    def unread_count(db: Session, user_id: int) -> int:
        return (
            db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.is_read == False)
            .count()
        )

    @staticmethod
    def _payload(notification: Notification, unread_count: int = 0) -> str:
        if notification.entity_type and notification.entity_id is not None:
            tag = f"{notification.entity_type}-{notification.entity_id}"
        else:
            tag = f"notification-{notification.id}"
        link = notification.link_url or DEFAULT_LINK
        payload = {
            "title": notification.title,
            "body": notification.message,
            "tag": tag,
            "unread_count": int(unread_count),
            "data": {
                "notification_id": notification.id,
                "url": link,
                "link_url": link,
                "unread_count": int(unread_count),
            },
        }
        return json.dumps(payload)

    @staticmethod
    def _is_stale_key(sub: PushSubscription) -> bool:
        """True when the subscription was created with a different VAPID key than the current one."""
        current = settings.vapid_key_id
        return bool(sub.vapid_key_id and current and sub.vapid_key_id != current)

    @staticmethod
    def _send_to_subscription(db: Session, sub: PushSubscription, payload: str) -> dict:
        """Send one payload to one device and record delivery stats. Never raises."""
        result = {"device": sub.device_label or "Device", "subscription_id": sub.id, "status": "sent", "error": None}
        if WebPushService._is_stale_key(sub):
            sub.is_active = False
            sub.last_failure_at = datetime.utcnow()
            sub.last_failure_reason = "VAPID key changed; device must re-subscribe"
            result.update(status="skipped", error=sub.last_failure_reason)
            return result
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=settings.web_push_private_key_value,
                vapid_claims={"sub": settings.WEB_PUSH_SUBJECT},
                ttl=120,
            )
            sub.last_success_at = datetime.utcnow()
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            sub.last_failure_at = datetime.utcnow()
            sub.last_failure_reason = (f"HTTP {status_code}" if status_code else str(exc))[:255]
            if status_code in DEAD_SUBSCRIPTION_STATUSES:
                sub.is_active = False
            result.update(status="failed", error=sub.last_failure_reason)
        except Exception as exc:
            sub.last_failure_at = datetime.utcnow()
            sub.last_failure_reason = str(exc)[:255] or exc.__class__.__name__
            result.update(status="failed", error=sub.last_failure_reason)
        return result

    @staticmethod
    def send_payload_to_user(db: Session, user_id: int, payload: str) -> dict:
        """Deliver a prepared payload to all active devices of a user."""
        if not WebPushService._enabled():
            return {"sent": 0, "failed": 0, "skipped": 0, "disabled": True, "devices": []}

        subscriptions = (
            db.query(PushSubscription)
            .filter(PushSubscription.user_id == user_id, PushSubscription.is_active == True)
            .all()
        )
        devices = [WebPushService._send_to_subscription(db, sub, payload) for sub in subscriptions]
        for sub in subscriptions:
            db.add(sub)
        db.commit()
        return {
            "sent": sum(1 for d in devices if d["status"] == "sent"),
            "failed": sum(1 for d in devices if d["status"] == "failed"),
            "skipped": sum(1 for d in devices if d["status"] == "skipped"),
            "disabled": False,
            "devices": devices,
        }

    @staticmethod
    def send_new_notification(db: Session, notification: Notification) -> dict:
        payload = WebPushService._payload(
            notification, WebPushService.unread_count(db, notification.user_id)
        )
        return WebPushService.send_payload_to_user(db, notification.user_id, payload)

    @staticmethod
    def send_test(db: Session, user_id: int) -> dict:
        payload = json.dumps({
            "title": "Test notification",
            "body": "Push notifications are working on this device.",
            "tag": "test-push",
            "unread_count": WebPushService.unread_count(db, user_id),
            "data": {"url": DEFAULT_LINK, "link_url": DEFAULT_LINK},
        })
        return WebPushService.send_payload_to_user(db, user_id, payload)