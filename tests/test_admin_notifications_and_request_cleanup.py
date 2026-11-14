"""Admins get every push (no settings to filter them), and admins may delete old non-critical requests."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import (
    AuditLog,
    Member,
    MemberRequest,
    Notification,
    NotificationPreference,
    RequestStatus,
    RequestType,
    User,
    UserRole,
)
from app.routes import notification_routes
from app.services import notification_service as ns_module
from app.services import payment_reminder_service as prs
from app.services.notification_service import NotificationService
from app.services.request_service import ADMIN_DELETE_AFTER_DAYS, RequestService
from app.services.web_push_service import WebPushService


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(ns_module, "publish_realtime_event", lambda user_id, event: "local")
    monkeypatch.setattr(ns_module, "can_enqueue_celery_tasks", lambda *a, **k: False)
    monkeypatch.setattr(
        WebPushService, "send_new_notification", staticmethod(lambda db, notification: sent.append(notification.user_id))
    )
    return sent


@pytest.fixture()
def world(db):
    def user(name, role):
        u = User(username=name, password_hash="x", role=role, is_active=True)
        db.add(u)
        db.flush()
        return u

    people = {
        "admin": user("admin1", UserRole.ADMIN),
        "super": user("super1", UserRole.SUPERADMIN),
        "mem": user("mem1", UserRole.MEMBER),
    }
    member = Member(user_id=people["mem"].id, member_code="MEM-0001", full_name="Mem One", monthly_amount=100)
    db.add(member)
    db.commit()
    people["member"] = member
    return people


def _ctx(user):
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return {"user_id": user.id, "role": role.lower(), "username": user.username}


# ------------------------------------------------------------ admin notifications
def _turn_everything_off(db, user):
    db.add(NotificationPreference(user_id=user.id, category="admin_requests", push_enabled=False))
    user.quiet_hours_enabled = True
    user.payment_reminder_enabled = False
    user.payment_reminder_day = 20
    db.commit()


def test_admin_push_ignores_old_category_and_quiet_settings(db, world, pushes, monkeypatch):
    monkeypatch.setattr(ns_module, "quiet_hours_resume_at", lambda user: datetime.now(timezone.utc) + timedelta(hours=3))
    for who in ("admin", "super"):
        _turn_everything_off(db, world[who])
        note = Notification(user_id=world[who].id, title="t", message="m", category="admin_requests")
        db.add(note)
        db.commit()
        NotificationService.dispatch_notification(db, note)
    # The admin still gets it; the superadmin's own settings are respected.
    assert pushes == [world["admin"].id]


def test_admin_always_gets_payment_reminders_on_default_day(db, world):
    _turn_everything_off(db, world["admin"])
    _turn_everything_off(db, world["super"])
    assert prs.reminder_enabled(world["admin"]) is True
    assert prs.reminder_day(db, world["admin"]) != 20
    assert prs.reminder_enabled(world["super"]) is False
    assert prs.reminder_day(db, world["super"]) == 20


def test_preferences_endpoint_marks_admins_simple(db, world):
    get = notification_routes.get_notification_preferences
    assert get(_ctx(world["admin"]), db)["simple_settings"] is True
    assert get(_ctx(world["super"]), db)["simple_settings"] is False
    assert get(_ctx(world["mem"]), db)["simple_settings"] is False
    with pytest.raises(HTTPException) as exc:
        notification_routes.update_notification_preferences(
            notification_routes.NotificationPreferencesUpdate(quiet_hours_enabled=True), _ctx(world["admin"]), db
        )
    assert exc.value.status_code == 403


# ------------------------------------------------------------ request cleanup
def _request(db, world, *, days_old, status=RequestStatus.PENDING, rtype=RequestType.COMPLAINT, subject="Help"):
    item = MemberRequest(
        member_id=world["member"].id, user_id=world["mem"].id, request_type=rtype, status=status,
        subject=subject, message="please", created_at=datetime.utcnow() - timedelta(days=days_old),
    )
    db.add(item)
    db.commit()
    return item


@pytest.fixture()
def quiet_dispatch(monkeypatch):
    sent = []
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: sent.append(n.title))
    return sent


def test_admin_deletes_old_pending_request_and_member_is_told(db, world, quiet_dispatch):
    item = _request(db, world, days_old=ADMIN_DELETE_AFTER_DAYS + 1)
    assert RequestService._serialize(db, item)["admin_can_delete"] is True
    RequestService.delete_request(db, _ctx(world["admin"]), item.id)
    assert db.query(MemberRequest).count() == 0
    assert quiet_dispatch == ["Request closed"]
    assert db.query(AuditLog).filter(AuditLog.action == "request_deleted").count() == 1


def test_admin_deletes_old_rejected_request_quietly(db, world, quiet_dispatch):
    item = _request(db, world, days_old=30, status=RequestStatus.REJECTED)
    RequestService.delete_request(db, _ctx(world["super"]), item.id)
    assert db.query(MemberRequest).count() == 0
    assert quiet_dispatch == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"days_old": ADMIN_DELETE_AFTER_DAYS - 1},  # too new
        {"days_old": 30, "status": RequestStatus.APPROVED},  # done requests are kept
        {"days_old": 30, "rtype": RequestType.MONTHLY_AMOUNT_CHANGE},  # critical
        {"days_old": 30, "rtype": RequestType.GENERAL, "subject": "Account closure request"},  # critical
    ],
)
def test_admin_cannot_delete(db, world, quiet_dispatch, kwargs):
    item = _request(db, world, **kwargs)
    assert RequestService._serialize(db, item)["admin_can_delete"] is False
    with pytest.raises(HTTPException) as exc:
        RequestService.delete_request(db, _ctx(world["admin"]), item.id)
    assert exc.value.status_code == 400
    assert db.query(MemberRequest).count() == 1


def test_deletable_from_date(db, world):
    item = _request(db, world, days_old=2)
    out = RequestService._serialize(db, item)
    assert out["admin_deletable_from"] == item.created_at + timedelta(days=ADMIN_DELETE_AFTER_DAYS)
    critical = _request(db, world, days_old=2, rtype=RequestType.MONTHLY_AMOUNT_CHANGE)
    assert RequestService._serialize(db, critical)["admin_deletable_from"] is None


def test_member_still_cancels_own_pending_any_time(db, world):
    item = _request(db, world, days_old=0, rtype=RequestType.MONTHLY_AMOUNT_CHANGE)
    RequestService.delete_request(db, _ctx(world["mem"]), item.id)
    assert db.query(MemberRequest).count() == 0
    rejected = _request(db, world, days_old=30, status=RequestStatus.REJECTED)
    with pytest.raises(HTTPException):
        RequestService.delete_request(db, _ctx(world["mem"]), rejected.id)
