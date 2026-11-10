import asyncio
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base
from app.models.models import (
    BulkChallanGroup,
    Challan,
    ChallanStatus,
    ChallanType,
    FundUtilization,
    Member,
    Notification,
    NotificationPreference,
    PushSubscription,
    User,
    UserRole,
)
import importlib

from app.routes import notification_routes
from app.schemas.schemas import NotificationCreate
from app.services import notification_prefs, realtime_notification_service as realtime
from app.services import notification_service as ns_module
from app.services import web_push_service as wps_module
from app.services.notification_service import NotificationService
from app.services.web_push_service import WebPushService

admin_router = importlib.import_module("app.routes.admin_router")


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def pushes(monkeypatch):
    """Record push sends; no Celery, no realtime."""
    sent = []
    monkeypatch.setattr(ns_module, "publish_realtime_event", lambda user_id, event: "local")
    monkeypatch.setattr(ns_module, "can_enqueue_celery_tasks", lambda *a, **k: False)
    monkeypatch.setattr(
        WebPushService, "send_new_notification", staticmethod(lambda db, notification: sent.append(notification.id))
    )
    return sent


def _user(db, name, role=UserRole.MEMBER, active=True):
    u = User(username=name, password_hash="x", role=role, full_name=name.title(), is_active=active)
    db.add(u)
    db.flush()
    return u


@pytest.fixture()
def world(db):
    admin = _user(db, "admin1", UserRole.ADMIN)
    admin2 = _user(db, "admin2", UserRole.ADMIN)
    super_ = _user(db, "super", UserRole.SUPERADMIN)
    mem_user = _user(db, "mem")
    member = Member(user_id=mem_user.id, member_code="M1", full_name="Mem Ber")
    db.add(member)
    db.commit()
    return {"admin": admin, "admin2": admin2, "super": super_, "user": mem_user, "member": member}


def _challan(db, member, status=ChallanStatus.PENDING):
    c = Challan(member_id=member.id, type=ChallanType.MONTHLY, month="2026-10", amount=500, status=status,
                payment_method="cash")
    db.add(c)
    db.commit()
    return c


def _notes(db, user):
    return db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.id).all()


# ---------------------------------------------------------------- metadata
def test_challan_status_notification_deep_link(db, world, pushes):
    c = _challan(db, world["member"])
    NotificationService.notify_challan_status_change(db, c, "approved")
    n = _notes(db, world["user"])[0]
    assert (n.category, n.entity_type, n.entity_id) == ("payment_updates", "challan", c.id)
    assert n.link_url == f"/Challans?challan={c.id}"
    assert n.is_urgent is False


def test_bulk_notification_deep_link(db, world, pushes):
    group = BulkChallanGroup(
        bulk_group_id="BG-9", member_id=world["member"].id, amount_per_month=500, total_amount=1000,
        proof_file_id="f", months_list=json.dumps(["2026-08", "2026-09"]), challan_ids_list="[]",
        created_by_user_id=world["user"].id,
    )
    db.add(group)
    db.commit()
    NotificationService.notify_bulk_status_change(db, group, "approved")
    n = _notes(db, world["user"])[0]
    assert (n.category, n.entity_type, n.entity_id) == ("payment_updates", "bulk_challan", group.id)
    assert n.link_url == "/Challans?bulk=BG-9"


def test_proof_uploaded_links_for_admins(db, world, pushes):
    NotificationService.notify_admins_proof_uploaded(
        db, world["member"], ["2026-10"], world["user"].id, challan_id=7
    )
    n = _notes(db, world["admin"])[0]
    assert (n.category, n.entity_type, n.entity_id) == ("admin_payment_reviews", "challan", 7)
    assert n.link_url == "/Challans?status=pending&challan=7"

    NotificationService.notify_admins_proof_uploaded(
        db, world["member"], ["2026-10"], world["user"].id, bulk_group_id="BG-1", bulk_id=3
    )
    n2 = _notes(db, world["admin"])[1]
    assert (n2.entity_type, n2.entity_id) == ("bulk_challan", 3)
    assert n2.link_url == "/Challans?status=pending&bulk=BG-1"


def test_admin_recorded_payment_links(db, world, pushes):
    c = _challan(db, world["member"])
    NotificationService.notify_admin_recorded_payment(db, [c], world["admin"].id, "admin1")
    admin_note = _notes(db, world["admin2"])[0]
    assert admin_note.category == "admin_payment_reviews"
    assert admin_note.link_url == f"/Challans?status=pending&challan={c.id}"
    member_note = _notes(db, world["user"])[0]
    assert (member_note.category, member_note.link_url) == ("payment_updates", f"/Challans?challan={c.id}")


def test_fund_utilization_links(db, world, pushes):
    fu = FundUtilization(title="Wells", amount=1000, registered_by_admin_id=world["admin"].id)
    db.add(fu)
    db.commit()
    NotificationService.notify_fund_utilization_created(db, fu)
    n = _notes(db, world["admin2"])[0]
    assert (n.category, n.entity_type, n.entity_id) == ("admin_fund_approvals", "fund_utilization", fu.id)
    assert n.link_url == f"/FundUtilization?tab=approval&entry={fu.id}"
    assert _notes(db, world["admin"]) == []

    NotificationService.notify_fund_utilization_status_change(db, fu, "approved")
    creator_note = _notes(db, world["admin"])[0]
    assert creator_note.link_url == f"/FundUtilization?entry={fu.id}"


def test_broadcast_and_security_metadata(db, world, pushes):
    NotificationService.create_notification(
        db, NotificationCreate(title="Eid", message="Mubarak", user_id=world["user"].id)
    )
    b = _notes(db, world["user"])[0]
    assert (b.category, b.link_url) == ("announcements", "/Notifications")

    NotificationService.notify_security_event(db, world["user"].id, "password_changed")
    s = _notes(db, world["user"])[1]
    assert s.is_urgent is True and s.category == "security"


def test_push_payload_has_link_tag_unread(db, world):
    n = Notification(user_id=world["user"].id, title="T", message="M", link_url="/Challans?challan=4",
                     entity_type="challan", entity_id=4)
    db.add(n)
    db.commit()
    data = json.loads(WebPushService._payload(n, unread_count=3))
    assert data["data"]["link_url"] == "/Challans?challan=4"
    assert data["data"]["url"] == "/Challans?challan=4"
    assert data["tag"] == "challan-4"
    assert data["unread_count"] == 3

    plain = Notification(id=9, user_id=1, title="T", message="M")
    assert json.loads(WebPushService._payload(plain))["data"]["url"] == "/notifications"


# ------------------------------------------------- preferences / quiet hours
def test_preference_off_skips_push_but_keeps_record(db, world, pushes):
    db.add(NotificationPreference(user_id=world["user"].id, category="payment_updates", push_enabled=False))
    db.commit()
    c = _challan(db, world["member"])
    NotificationService.notify_challan_status_change(db, c, "approved")
    assert len(_notes(db, world["user"])) == 1
    assert pushes == []


def test_preference_on_by_default_sends_push(db, world, pushes):
    c = _challan(db, world["member"])
    NotificationService.notify_challan_status_change(db, c, "approved")
    assert len(pushes) == 1


def test_urgent_ignores_preferences_and_quiet_hours(db, world, pushes, monkeypatch):
    db.add(NotificationPreference(user_id=world["user"].id, category="security", push_enabled=False))
    world["user"].quiet_hours_enabled = True
    db.commit()
    monkeypatch.setattr(ns_module, "quiet_hours_resume_at", lambda user: datetime.now(timezone.utc))
    NotificationService.notify_security_event(db, world["user"].id, "role_changed")
    assert len(pushes) == 1


class _FakeTask:
    def __init__(self):
        self.calls = []

    def apply_async(self, args=None, eta=None):
        self.calls.append((args, eta))

    def delay(self, *args):
        self.calls.append((args, None))


def test_quiet_hours_defer_with_eta(db, world, pushes, monkeypatch):
    import app.workers.tasks as tasks

    fake = _FakeTask()
    resume = datetime(2026, 11, 1, 1, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(tasks, "send_web_push_notification", fake)
    monkeypatch.setattr(ns_module, "can_enqueue_celery_tasks", lambda *a, **k: True)
    monkeypatch.setattr(ns_module, "quiet_hours_resume_at", lambda user: resume)

    c = _challan(db, world["member"])
    NotificationService.notify_challan_status_change(db, c, "approved")
    note = _notes(db, world["user"])[0]
    assert fake.calls == [([note.id], resume)]
    assert pushes == []


def test_quiet_hours_without_celery_skips_push_keeps_record(db, world, pushes, monkeypatch):
    monkeypatch.setattr(ns_module, "quiet_hours_resume_at", lambda user: datetime.now(timezone.utc))
    c = _challan(db, world["member"])
    NotificationService.notify_challan_status_change(db, c, "approved")
    assert len(_notes(db, world["user"])) == 1
    assert pushes == []


def _quiet_user(start="22:00", end="07:00"):
    return User(username="q", password_hash="x", role=UserRole.MEMBER,
                quiet_hours_enabled=True, quiet_hours_start=start, quiet_hours_end=end)


def test_quiet_hours_cross_midnight_ist():
    u = _quiet_user()
    # 23:30 IST on 31 Oct -> resumes 07:00 IST on 1 Nov (= 01:30 UTC)
    late = datetime(2026, 10, 31, 18, 0, tzinfo=timezone.utc)
    assert notification_prefs.quiet_hours_resume_at(u, late) == datetime(2026, 11, 1, 1, 30, tzinfo=timezone.utc)
    # 03:00 IST on 1 Nov -> resumes 07:00 IST the same day
    early = datetime(2026, 10, 31, 21, 30, tzinfo=timezone.utc)
    assert notification_prefs.quiet_hours_resume_at(u, early) == datetime(2026, 11, 1, 1, 30, tzinfo=timezone.utc)
    # 12:00 IST is outside the window
    noon = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
    assert notification_prefs.quiet_hours_resume_at(u, noon) is None


def test_quiet_hours_same_day_window_and_disabled():
    u = _quiet_user("13:00", "15:00")
    inside = datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc)  # 14:00 IST
    assert notification_prefs.quiet_hours_resume_at(u, inside) == datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
    u.quiet_hours_enabled = False
    assert notification_prefs.quiet_hours_resume_at(u, inside) is None


def test_preferences_endpoint_roundtrip_and_validation(db, world):
    ctx = {"user_id": world["user"].id, "role": "member", "username": "mem"}
    out = notification_routes.update_notification_preferences(
        notification_routes.NotificationPreferencesUpdate(
            categories={"reminders": False}, quiet_hours_enabled=True,
            quiet_hours_start="21:00", quiet_hours_end="06:30",
        ),
        ctx, db,
    )
    assert out["categories"]["reminders"] is False and out["categories"]["payment_updates"] is True
    assert out["quiet_hours"]["enabled"] is True and out["quiet_hours"]["start"] == "21:00"
    assert "admin_requests" not in out["categories"]

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        notification_routes.update_notification_preferences(
            notification_routes.NotificationPreferencesUpdate(categories={"admin_requests": False}), ctx, db
        )
    assert exc.value.status_code == 422


# ------------------------------------------------------------- VAPID / push
class _FakeWebPush:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)


def _configure_push(monkeypatch, public="PUB-NEW"):
    monkeypatch.setattr(settings, "WEB_PUSH_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "WEB_PUSH_PRIVATE_KEY", "private")
    fake = _FakeWebPush()
    monkeypatch.setattr(wps_module, "webpush", fake)
    return fake


def test_old_vapid_key_subscription_skipped_and_deactivated(db, world, monkeypatch):
    fake = _configure_push(monkeypatch)
    current = settings.vapid_key_id
    old = PushSubscription(user_id=world["user"].id, endpoint="e-old", p256dh="a", auth="b", vapid_key_id="stale")
    new = PushSubscription(user_id=world["user"].id, endpoint="e-new", p256dh="a", auth="b", vapid_key_id=current)
    db.add_all([old, new])
    n = Notification(user_id=world["user"].id, title="T", message="M")
    db.add(n)
    db.commit()

    result = WebPushService.send_new_notification(db, n)
    db.refresh(old)
    db.refresh(new)
    assert [c["subscription_info"]["endpoint"] for c in fake.calls] == ["e-new"]
    assert old.is_active is False and new.is_active is True
    assert new.last_success_at is not None
    assert result["sent"] == 1 and result["skipped"] == 1


def test_subscribe_stores_current_key_id_and_device_label(db, world, monkeypatch):
    _configure_push(monkeypatch)
    WebPushService.upsert_subscription(
        db, world["user"].id, "e1", "a", "b",
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit Version/17.0 Safari/604.1",
    )
    sub = db.query(PushSubscription).one()
    assert sub.vapid_key_id == settings.vapid_key_id and sub.vapid_key_id
    assert sub.device_label == "iPhone Safari"


def test_failed_send_records_reason(db, world, monkeypatch):
    _configure_push(monkeypatch)

    class _Resp:
        status_code = 410

    class _Boom(Exception):
        response = _Resp()

    monkeypatch.setattr(wps_module, "WebPushException", _Boom)

    def boom(**kwargs):
        raise _Boom("gone")

    monkeypatch.setattr(wps_module, "webpush", boom)
    sub = PushSubscription(user_id=world["user"].id, endpoint="e", p256dh="a", auth="b",
                           vapid_key_id=settings.vapid_key_id)
    n = Notification(user_id=world["user"].id, title="T", message="M")
    db.add_all([sub, n])
    db.commit()
    WebPushService.send_new_notification(db, n)
    db.refresh(sub)
    assert sub.is_active is False and sub.last_failure_reason == "HTTP 410" and sub.last_failure_at


def test_missing_vapid_env_disables_push_without_crash(db, world, monkeypatch):
    monkeypatch.setattr(settings, "WEB_PUSH_PUBLIC_KEY", "")
    monkeypatch.setattr(settings, "WEB_PUSH_PRIVATE_KEY", "")
    assert settings.web_push_configured is False
    assert settings.vapid_key_id == ""
    n = Notification(user_id=world["user"].id, title="T", message="M")
    db.add(n)
    db.commit()
    assert WebPushService.send_new_notification(db, n)["disabled"] is True
    assert notification_routes.get_push_public_key() == {"enabled": False, "public_key": "", "key_id": ""}


def test_public_key_endpoint_returns_key_id(monkeypatch):
    _configure_push(monkeypatch)
    out = notification_routes.get_push_public_key()
    assert out["enabled"] is True and out["public_key"] == "PUB-NEW" and out["key_id"] == settings.vapid_key_id


def test_vapid_env_names_take_priority(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("VAPID_PUBLIC_KEY", "new-pub")
    monkeypatch.setenv("WEB_PUSH_PUBLIC_KEY", "legacy-pub")
    assert Settings().WEB_PUSH_PUBLIC_KEY == "new-pub"
    monkeypatch.delenv("VAPID_PUBLIC_KEY")
    assert Settings().WEB_PUSH_PUBLIC_KEY == "legacy-pub"


# ------------------------------------------------------------ Redis bridge
class _FakeRedisClient:
    published = []

    def publish(self, channel, data):
        _FakeRedisClient.published.append((channel, data))

    def close(self):
        pass


def test_event_from_worker_reaches_sse_hub_via_redis(monkeypatch):
    import redis

    _FakeRedisClient.published = []
    monkeypatch.setattr(settings, "REDIS_URL", "redis://fake:6379/0")
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, url, **kw: _FakeRedisClient()))

    hub = realtime.notification_realtime_hub
    queue = asyncio.Queue()
    hub._queues[42].add(queue)
    try:
        # Worker side: published to Redis only, nothing delivered locally yet.
        assert realtime.publish_realtime_event(42, {"type": "create", "data": {"id": 1}}) == "redis"
        assert queue.empty()
        channel, raw = _FakeRedisClient.published[0]
        assert channel == "notifications:events"
        # Web side: the subscriber forwards the message to the local hub.
        assert realtime.forward_redis_message(raw.encode()) is True
        assert queue.get_nowait() == {"type": "create", "data": {"id": 1}}
    finally:
        hub._queues.pop(42, None)


def test_without_redis_events_stay_in_process(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "")
    monkeypatch.setattr(settings, "CELERY_BROKER_URL", "memory://")
    hub = realtime.notification_realtime_hub
    queue = asyncio.Queue()
    hub._queues[43].add(queue)
    try:
        assert realtime.publish_realtime_event(43, {"type": "create"}) == "local"
        assert queue.get_nowait() == {"type": "create"}
    finally:
        hub._queues.pop(43, None)


def test_redis_failure_falls_back_to_local(monkeypatch):
    import redis

    def boom(cls, url, **kw):
        raise ConnectionError("down")

    monkeypatch.setattr(settings, "REDIS_URL", "redis://fake:6379/0")
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(boom))
    hub = realtime.notification_realtime_hub
    queue = asyncio.Queue()
    hub._queues[44].add(queue)
    try:
        assert realtime.publish_realtime_event(44, {"type": "create"}) == "local"
        assert queue.get_nowait() == {"type": "create"}
    finally:
        hub._queues.pop(44, None)


def test_sse_frames_use_real_newlines():
    frame = realtime.NotificationRealtimeHub._to_sse({"type": "create"})
    assert frame.startswith("event: create\ndata: ") and frame.endswith("\n\n")


# --------------------------------------------------- delivery / test push
def _sub(db, user, ua, ok=True, label=None):
    s = PushSubscription(
        user_id=user.id, endpoint=f"e-{user.id}-{ua[:5]}", p256dh="a", auth="b", user_agent=ua,
        device_label=label, last_success_at=datetime.utcnow() if ok else None,
        last_failure_at=None if ok else datetime.utcnow(), last_failure_reason=None if ok else "HTTP 410",
    )
    db.add(s)
    db.commit()


def test_delivery_overview_superadmin_sees_all_admin_sees_own(db, world):
    _sub(db, world["user"], "Mozilla iPhone Safari", label="iPhone Safari")
    _sub(db, world["admin"], "Mozilla Android Chrome", ok=False, label="Android Chrome")
    _sub(db, world["admin2"], "Mozilla Windows Chrome", label="Windows Chrome")

    super_ctx = {"user_id": world["super"].id, "role": "superadmin", "username": "super"}
    full = admin_router.get_notification_delivery_overview("", 0, 25, super_ctx, db)
    assert full["scope"] == "all"
    assert full["users_with_active_subscription"] == 3
    assert full["by_device_type"] == {"ios": 1, "android": 1, "desktop": 1}
    assert full["failures_last_7_days"] == 1
    assert {u["user_id"] for u in full["users"]} == {u.id for u in world.values() if isinstance(u, User)}
    failing = next(u for u in full["users"] if u["user_id"] == world["admin"].id)
    assert failing["last_failure_reason"] == "HTTP 410"

    admin_ctx = {"user_id": world["admin"].id, "role": "admin", "username": "admin1"}
    own = admin_router.get_notification_delivery_overview("", 0, 25, admin_ctx, db)
    assert own["scope"] == "own"
    assert [u["user_id"] for u in own["users"]] == [world["admin"].id]
    assert len(own["users"][0]["devices"]) == 1

    found = admin_router.get_notification_delivery_overview("super", 0, 25, super_ctx, db)
    assert [u["username"] for u in found["users"]] == ["super"]


def test_test_push_own_and_other_user(db, world, monkeypatch):
    from fastapi import HTTPException

    sent_to = []
    monkeypatch.setattr(
        WebPushService, "send_test",
        staticmethod(lambda db, user_id: sent_to.append(user_id) or
                     {"sent": 1, "failed": 0, "skipped": 0, "disabled": False,
                      "devices": [{"device": "iPhone Safari", "status": "sent", "error": None}]}),
    )
    admin_ctx = {"user_id": world["admin"].id, "role": "admin", "username": "admin1"}

    own = notification_routes.send_test_push(notification_routes.TestPushRequest(), admin_ctx, db)
    assert sent_to == [world["admin"].id] and own["devices"][0]["status"] == "sent"

    with pytest.raises(HTTPException) as exc:
        notification_routes.send_test_push(
            notification_routes.TestPushRequest(user_id=world["user"].id), admin_ctx, db
        )
    assert exc.value.status_code == 403

    super_ctx = {"user_id": world["super"].id, "role": "superadmin", "username": "super"}
    out = notification_routes.send_test_push(
        notification_routes.TestPushRequest(user_id=world["user"].id), super_ctx, db
    )
    assert out["user_id"] == world["user"].id and sent_to[-1] == world["user"].id

    from app.models.models import AuditLog
    log = db.query(AuditLog).filter(AuditLog.action == "notification_test_push").one()
    assert log.user_id == world["super"].id and log.entity_id == world["user"].id
