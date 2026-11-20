"""Unfinished payments: member reminders at 48 h / 7 days, the admin morning summary, remind now."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import (
    Campaign, Challan, ChallanStatus, ChallanType, Member, Notification, NudgeLog, User, UserRole,
)
from app.services import unfinished_service as us

NOW = datetime(2026, 11, 20, 6, 0)  # naive UTC = 11:30 IST


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, username="admin", password_hash="x", role=UserRole.ADMIN),
        User(id=2, username="amina", password_hash="x", role=UserRole.MEMBER, full_name="Amina"),
        User(id=3, username="basil", password_hash="x", role=UserRole.MEMBER),
    ])
    session.add_all([
        Member(id=10, user_id=2, member_code="MEM-0001", full_name="Amina", monthly_amount=500),
        Member(id=11, user_id=3, member_code="MEM-0002", full_name="Basil", monthly_amount=300),
    ])
    session.add(Campaign(id=5, title="Eid kit", created_by_admin_id=1, start_date=datetime(2026, 11, 1)))
    session.commit()
    monkeypatch.setattr(us, "_now_naive", lambda db: NOW)
    monkeypatch.setattr(us, "now_business", lambda: NOW.replace(tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=5, minutes=30))))
    monkeypatch.setattr("app.services.notification_service.NotificationService.dispatch_notification",
                        staticmethod(lambda db, n: None))
    yield session
    session.close()


def _challan(db, member_id, age, **over):
    data = dict(member_id=member_id, type=ChallanType.MONTHLY, month="2026-11", amount=500,
                status=ChallanStatus.PENDING, entry_source="self", created_by_user_id=2 if member_id == 10 else 3,
                created_at=NOW - age)
    data.update(over)
    c = Challan(**data)
    db.add(c)
    db.commit()
    return c


def _notes(db, user_id):
    return db.query(Notification).filter(Notification.user_id == user_id).all()


def test_only_member_started_without_proof_count(db):
    _challan(db, 10, timedelta(hours=50))                                         # counts
    _challan(db, 10, timedelta(hours=50), month="2026-10", proof_path="p.jpg")      # proof handed in
    _challan(db, 10, timedelta(hours=50), month="2026-09", entry_source="import")   # old imported row
    _challan(db, 10, timedelta(hours=50), month="2026-08", entry_source="admin")    # admin entry
    _challan(db, 10, timedelta(hours=50), month="2026-07", created_by_user_id=None)  # imported "self" row
    _challan(db, 10, timedelta(hours=10), month="2026-12")                          # too new for admins
    data = us.list_unfinished(db, min_hours=48)
    assert [i["month"] for i in data["items"]] == ["2026-11"]
    assert data["items"][0]["member_code"] == "MEM-0001"
    assert len(us.list_unfinished(db, min_hours=0, member_id=10)["items"]) == 2   # member sees all of theirs


def test_member_reminders_48h_then_7_days_once(db):
    a = _challan(db, 10, timedelta(hours=50))
    b = _challan(db, 10, timedelta(hours=60), type=ChallanType.CAMPAIGN, month=None, campaign_id=5, amount=1000)
    _challan(db, 11, timedelta(hours=20), amount=300)            # not yet 48 h

    out = us.run_member_reminders(db)
    assert out == {"members": 1, "first": 2, "follow_up": 0}
    notes = _notes(db, 2)
    assert len(notes) == 1 and "Nov 2026 (₹500)" in notes[0].message and "Eid kit (₹1,000)" in notes[0].message
    assert notes[0].link_url == us.MEMBER_LINK
    assert us.run_member_reminders(db)["first"] == 0             # never twice
    assert _notes(db, 3) == []

    # 7 days old and the first went 4 days ago: one follow-up
    for c in (a, b):
        c.created_at = NOW - timedelta(days=8)
    db.query(NudgeLog).update({NudgeLog.sent_at: NOW - timedelta(days=4)})
    db.commit()
    assert us.run_member_reminders(db) == {"members": 1, "first": 0, "follow_up": 2}
    assert us.run_member_reminders(db)["follow_up"] == 0
    assert len(_notes(db, 2)) == 2


def test_month_paid_by_another_challan_is_a_leftover(db):
    _challan(db, 10, timedelta(days=3))
    _challan(db, 10, timedelta(days=2), status=ChallanStatus.APPROVED)
    assert us.run_member_reminders(db)["first"] == 0
    assert us.list_unfinished(db)["items"][0]["already_paid"] is True


def test_admin_digest_once_a_day(db):
    _challan(db, 10, timedelta(hours=50))
    _challan(db, 10, timedelta(hours=50), month="2026-10")
    _challan(db, 11, timedelta(hours=72), amount=300)
    out = us.run_admin_digest(db)
    assert out["status"] == "sent" and out["open"] == 3
    [note] = _notes(db, 1)
    assert note.link_url == us.ADMIN_LINK
    assert "3 payments started by 2 members" in note.message and "MEM-0001 (Nov 2026, Oct 2026)" in note.message
    assert us.run_admin_digest(db)["status"] == "already_sent"


def test_admin_digest_waits_for_morning_and_skips_when_nothing(db, monkeypatch):
    assert us.run_admin_digest(db)["status"] == "nothing_open"
    _challan(db, 10, timedelta(hours=50))
    early = datetime(2026, 11, 20, 7, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    monkeypatch.setattr(us, "now_business", lambda: early)
    assert us.run_admin_digest(db)["status"] == "too_early"


def test_remind_now_once_a_day(db):
    c = _challan(db, 10, timedelta(hours=5))
    admin = {"user_id": 1, "role": "admin"}
    assert us.remind_now(db, admin, c.id)["status"] == "sent"
    assert len(_notes(db, 2)) == 1
    with pytest.raises(HTTPException) as exc:
        us.remind_now(db, admin, c.id)
    assert exc.value.status_code == 409
    done = _challan(db, 10, timedelta(hours=5), month="2026-07", proof_path="x.jpg")
    with pytest.raises(HTTPException) as exc:
        us.remind_now(db, admin, done.id)
    assert exc.value.status_code == 404


def test_admin_cancel_with_reason_tells_member(db):
    from app.routes import challan_routes

    c = _challan(db, 10, timedelta(days=3), status=ChallanStatus.GENERATED)
    challan_routes.delete_challan(c.id, reason="Paid in cash, recorded separately",
                                  current_user={"user_id": 1, "role": "admin"}, db=db)
    assert db.query(Challan).filter(Challan.id == c.id).first() is None
    [note] = _notes(db, 2)
    assert note.title == "Payment cancelled" and "Nov 2026 (₹500)" in note.message
    assert "Reason: Paid in cash, recorded separately" in note.message
