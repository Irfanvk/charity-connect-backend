from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import Member, User, UserRole
from app.services.challan_service import ChallanService
from app.utils import timezone as tz


def freeze(monkeypatch, year, month, day, hour, minute=0):
    fixed = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    monkeypatch.setattr(tz, "now_utc", lambda: fixed)


def test_business_tz_is_kolkata():
    assert str(tz.BUSINESS_TZ) == "Asia/Kolkata"


def test_now_utc_is_aware_utc():
    assert tz.now_utc().utcoffset().total_seconds() == 0


def test_to_business_treats_naive_as_utc():
    result = tz.to_business(datetime(2026, 10, 31, 20, 0))
    assert (result.year, result.month, result.day, result.hour, result.minute) == (2026, 11, 1, 1, 30)


def test_to_business_converts_aware():
    gst = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc).astimezone(tz.ZoneInfo("Asia/Dubai"))
    result = tz.to_business(gst)
    assert (result.hour, result.minute) == (5, 30)


def test_helpers_after_ist_midnight(monkeypatch):
    freeze(monkeypatch, 2026, 10, 31, 20)
    assert tz.today_business() == date(2026, 11, 1)
    assert tz.current_month_business() == "2026-11"
    assert tz.now_business().utcoffset().total_seconds() == 5.5 * 3600


def test_helpers_before_ist_midnight(monkeypatch):
    freeze(monkeypatch, 2026, 10, 31, 18)
    assert tz.today_business() == date(2026, 10, 31)
    assert tz.current_month_business() == "2026-10"


@pytest.fixture()
def member_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = User(username="m", password_hash="x", role=UserRole.MEMBER)
    db.add(user)
    db.flush()
    member = Member(user_id=user.id, member_code="M1", join_date=datetime(2026, 9, 5))
    db.add(member)
    db.commit()
    yield db, member
    db.close()


def test_payable_months_after_ist_rollover(monkeypatch, member_db):
    db, member = member_db
    freeze(monkeypatch, 2026, 10, 31, 20)
    result = ChallanService.get_payable_months(db, member.id)
    assert result["current_month"] == "2026-11"
    assert result["business_timezone"] == "Asia/Kolkata"
    assert result["all_months"][-1] == "2026-11"


def test_payable_months_before_ist_rollover(monkeypatch, member_db):
    db, member = member_db
    freeze(monkeypatch, 2026, 10, 31, 18)
    result = ChallanService.get_payable_months(db, member.id)
    assert result["current_month"] == "2026-10"
    assert "2026-11" not in result["all_months"]
