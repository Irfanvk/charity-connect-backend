"""Per-member monthly payment reminders with a follow-up and no duplicates."""
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import (
    Challan, ChallanStatus, ChallanType, Member, Notification, PaymentReminderLog, User, UserRole,
)
from app.services import payment_reminder_service as prs
from app.services.notification_service import NotificationService

SETTINGS = {"monthly_reminder_enabled": True, "monthly_reminder_day": 1}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)
    monkeypatch.setattr(prs, "get_setting", lambda db, key: SETTINGS[key])
    monkeypatch.setattr(prs, "render_message", lambda db, key, ctx: f"{key}:{ctx['month']}:{ctx['amount']}")
    monkeypatch.setattr(prs, "org_name", lambda db: "Org")


def _member(db, name, *, day=None, enabled=None, amount=1000, active=True):
    user = User(username=name, password_hash="x", role=UserRole.MEMBER, is_active=active,
                payment_reminder_day=day, payment_reminder_enabled=enabled)
    db.add(user)
    db.flush()
    member = Member(user_id=user.id, member_code=f"MEM-{user.id:04d}", full_name=name.title(), monthly_amount=amount)
    db.add(member)
    db.commit()
    return member


def _notes(db, member):
    return db.query(Notification).filter(Notification.user_id == member.user_id).all()


def _pay(db, member, month, status=ChallanStatus.APPROVED):
    db.add(Challan(member_id=member.id, type=ChallanType.MONTHLY, month=month, amount=member.monthly_amount, status=status))
    db.commit()


def test_default_day_and_own_day(db):
    default = _member(db, "ali")              # organisation day: 1st
    own = _member(db, "basheer", day=10)

    result = prs.run_due_reminders(db, date(2026, 12, 1))
    assert result["first"] == 1
    assert len(_notes(db, default)) == 1 and _notes(db, own) == []

    prs.run_due_reminders(db, date(2026, 12, 10))
    note = _notes(db, own)[0]
    assert note.category == "reminders" and note.link_url == "/Challans"
    assert "msg_monthly_reminder:December 2026:₹1,000" in note.message


def test_never_sent_twice_even_when_run_repeatedly(db):
    member = _member(db, "ali", day=5)
    for _ in range(4):
        prs.run_due_reminders(db, date(2026, 12, 5))
    prs.run_due_reminders(db, date(2026, 12, 6))
    assert len(_notes(db, member)) == 1
    assert db.query(PaymentReminderLog).count() == 1


def test_skips_when_paid_or_submitted(db):
    approved = _member(db, "ali", day=5)
    pending = _member(db, "basheer", day=5)
    other_month = _member(db, "chandni", day=5)
    _pay(db, approved, "2026-12")
    _pay(db, pending, "2026-12", ChallanStatus.PENDING)
    _pay(db, other_month, "2026-11")

    result = prs.run_due_reminders(db, date(2026, 12, 5))
    assert result["skipped_paid"] == 2 and result["first"] == 1
    assert _notes(db, approved) == [] and _notes(db, pending) == []
    assert len(_notes(db, other_month)) == 1


def test_follow_up_after_seven_days_only_if_unpaid(db):
    unpaid = _member(db, "ali", day=5)
    paid_later = _member(db, "basheer", day=5)
    prs.run_due_reminders(db, date(2026, 12, 5))
    # first reminders are logged on the 5th
    for log in db.query(PaymentReminderLog).all():
        log.sent_at = datetime(2026, 12, 5, 4, 0)
    db.commit()
    _pay(db, paid_later, "2026-12")

    assert prs.run_due_reminders(db, date(2026, 12, 11))["follow_up"] == 0   # day 6: too early
    result = prs.run_due_reminders(db, date(2026, 12, 12))
    assert result["follow_up"] == 1
    titles = [n.title for n in _notes(db, unpaid)]
    assert titles == ["Monthly payment reminder", "Gentle reminder: payment still due"]
    assert len(_notes(db, paid_later)) == 1
    # never a third one
    prs.run_due_reminders(db, date(2026, 12, 13))
    assert len(_notes(db, unpaid)) == 2


def test_late_day_follow_up_is_capped_at_month_end(db):
    member = _member(db, "ali", day=25)
    prs.run_due_reminders(db, date(2026, 11, 25))
    db.query(PaymentReminderLog).update({"sent_at": datetime(2026, 11, 25, 4, 0)})
    db.commit()
    # 25 + 7 = 32 -> 30 November
    assert prs.run_due_reminders(db, date(2026, 11, 30))["follow_up"] == 1
    assert len(_notes(db, member)) == 2


def test_catch_up_when_server_was_down(db):
    member = _member(db, "ali", day=5)
    assert prs.run_due_reminders(db, date(2026, 12, 7))["first"] == 1   # 2 days late: still sent
    late = _member(db, "basheer", day=5)
    assert prs.run_due_reminders(db, date(2026, 12, 8))["first"] == 0   # 3 days late: skipped
    assert len(_notes(db, member)) == 1 and _notes(db, late) == []


def test_opt_out_inactive_and_zero_amount_are_skipped(db):
    off = _member(db, "ali", enabled=False)
    inactive = _member(db, "basheer", active=False)
    zero = _member(db, "chandni", amount=0)
    assert prs.run_due_reminders(db, date(2026, 12, 1))["first"] == 0
    assert _notes(db, off) == _notes(db, inactive) == _notes(db, zero) == []


def test_organisation_switch_off(db, monkeypatch):
    _member(db, "ali")
    monkeypatch.setattr(prs, "get_setting", lambda db, key: False if key == "monthly_reminder_enabled" else 1)
    assert prs.run_due_reminders(db, date(2026, 12, 1)) == {"status": "skipped", "reason": "disabled"}


def test_preferences_and_validation(db):
    member = _member(db, "ali")
    user = db.get(User, member.user_id)
    prefs = prs.preferences_for(db, user)
    assert prefs == {"enabled": True, "day": 1, "uses_default_day": True, "default_day": 1,
                     "applies": True, "organisation_enabled": True}
    prs.save_preferences(user, enabled=True, day=12)
    assert prs.preferences_for(db, user)["day"] == 12
    with pytest.raises(ValueError):
        prs.save_preferences(user, day=29)
    prs.save_preferences(user, enabled=False)
    assert prs.preferences_for(db, user)["enabled"] is False


def test_onboarding_saves_address_only_when_empty(db, monkeypatch):
    from app.routes import auth_routes
    monkeypatch.setattr(auth_routes.payment_reminder_service, "get_setting", lambda db, key: SETTINGS[key])
    member = _member(db, "ali")
    ctx = {"user_id": member.user_id, "role": "member"}

    first = auth_routes.complete_onboarding(
        auth_routes.OnboardingPayload(address="  12 Main  Road, Kasaragod ", payment_reminder_day=7), ctx, db,
    )
    assert first["address_saved"] is True and first["payment_reminder"]["day"] == 7
    db.refresh(member)
    assert member.address == "12 Main Road, Kasaragod"
    completed_at = db.get(User, member.user_id).onboarding_completed_at
    assert completed_at is not None

    again = auth_routes.complete_onboarding(auth_routes.OnboardingPayload(address="Somewhere else"), ctx, db)
    assert again["address_saved"] is False and again["address_needs_approval"] is True
    db.refresh(member)
    assert member.address == "12 Main Road, Kasaragod"
    assert db.get(User, member.user_id).onboarding_completed_at == completed_at
