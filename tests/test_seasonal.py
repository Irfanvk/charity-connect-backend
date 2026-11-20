"""Excused months, yearly pledges and members who are not monthly members (seasonal.py)."""
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import Challan, ChallanStatus, ChallanType, ExcusedMonth, Member, User, UserRole
from app.services import report_service, seasonal
from app.services.bulk_rules import monthly_amount_for
from app.services.challan_service import ChallanService


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, username="admin", password_hash="x", role=UserRole.ADMIN, is_active=True),
        User(id=2, username="haneef", password_hash="x", role=UserRole.MEMBER, is_active=True),
        Member(id=10, user_id=2, member_code="MEM-0001", full_name="Haneef", monthly_amount=500,
               join_date=datetime(2025, 8, 1)),
    ])
    session.commit()
    # Today is 20 Nov 2026 (Aug-Jul year 2026-2027).
    monkeypatch.setattr(report_service, "today_business", lambda: date(2026, 11, 20))
    monkeypatch.setattr(seasonal, "current_month_business", lambda: "2026-11")
    monkeypatch.setattr("app.services.challan_service.today_business", lambda: date(2026, 11, 20))
    monkeypatch.setattr(seasonal, "excused_limit", lambda db: 0)
    session.sent = []
    monkeypatch.setattr("app.services.notification_service.NotificationService._send_status_notification",
                        staticmethod(lambda db, uid, title, msg, *a, **k: session.sent.append((uid, title))))
    monkeypatch.setattr("app.services.notification_service.NotificationService._active_admin_ids",
                        staticmethod(lambda db, exclude_user_id=None: [1]))
    yield session
    session.close()


def _pay(db, month, status=ChallanStatus.APPROVED, amount=500, **over):
    c = Challan(member_id=10, type=ChallanType.MONTHLY, month=month, amount=amount, status=status, **over)
    db.add(c)
    db.commit()
    return c


def _states(db, frm="2026-08", to="2026-11"):
    data = report_service.member_statement(db, 10, frm, to)
    return {r["month"]: r["state"] for r in data["months"]}, data["totals"]


def test_excused_months_are_not_owed(db):
    _pay(db, "2026-08")
    placeholder = _pay(db, "2026-09", status=ChallanStatus.PENDING, entry_source="import")  # "not paid yet"
    out = seasonal.excuse_months(db, db.get(Member, 10), ["2026-09", "2026-10"], "No work", actor_id=1)
    assert out == {"excused": ["2026-09", "2026-10"], "removed_unpaid_rows": 1}
    assert db.get(Challan, placeholder.id) is None
    states, totals = _states(db)
    assert states == {"2026-08": "paid", "2026-09": "excused", "2026-10": "excused", "2026-11": "not_paid"}
    assert totals["months_due"] == 1 and totals["amount_due"] == 500 and totals["months_excused"] == 2
    payable = ChallanService.get_payable_months(db, 10)
    assert "2026-09" not in payable["all_months"] and payable["excused_months"] == ["2026-09", "2026-10"]


def test_paid_month_cannot_be_excused_and_reason_needed(db):
    _pay(db, "2026-08")
    m = db.get(Member, 10)
    with pytest.raises(HTTPException):
        seasonal.excuse_months(db, m, ["2026-08"], "No work", actor_id=1)
    with pytest.raises(HTTPException):
        seasonal.excuse_months(db, m, ["2026-09"], "  ", actor_id=1)


def test_limit_per_year(db, monkeypatch):
    monkeypatch.setattr(seasonal, "excused_limit", lambda db: 2)
    m = db.get(Member, 10)
    seasonal.excuse_months(db, m, ["2026-08", "2026-09"], "No work", actor_id=1)
    with pytest.raises(HTTPException) as exc:
        seasonal.excuse_months(db, m, ["2026-10"], "No work", actor_id=1)
    assert "At most 2" in exc.value.detail
    seasonal.excuse_months(db, m, ["2025-12"], "No work", actor_id=1)  # another year: fine


def test_member_request_then_admin_decides(db):
    out = seasonal.request_months(db, 2, ["2026-12", "2027-01"], "No work in winter")
    assert out == {"requested": ["2026-12", "2027-01"]} and db.sent == [(1, "Excused months requested")]
    reqs = seasonal.waiting_requests(db)
    assert [r["month"] for r in reqs] == ["2026-12", "2027-01"] and reqs[0]["member_code"] == "MEM-0001"
    m = db.get(Member, 10)
    seasonal.decide_request(db, m, reqs[0]["id"], True, None, actor_id=1)
    with pytest.raises(HTTPException):          # rejecting needs a reason
        seasonal.decide_request(db, m, reqs[1]["id"], False, "", actor_id=1)
    seasonal.decide_request(db, m, reqs[1]["id"], False, "We need January", actor_id=1)
    statuses = {e.month: e.status for e in db.query(ExcusedMonth)}
    assert statuses == {"2026-12": "approved", "2027-01": "rejected"}
    assert db.sent[-1] == (2, "Excused month not approved")
    states, _ = _states(db, "2026-12", "2027-01")
    assert states == {"2026-12": "excused", "2027-01": "not_paid"}


def test_pledge_year(db):
    _pay(db, "2026-08")
    _pay(db, "2026-09", status=ChallanStatus.PENDING, proof_path="uploads/p.jpg")   # waiting approval
    m = db.get(Member, 10)
    seasonal.set_pledge(db, m, 2026, 3000, "Works 6 months a year", actor_id=1)
    states, totals = _states(db)
    assert states == {"2026-08": "paid", "2026-09": "waiting", "2026-10": "pledge", "2026-11": "pledge"}
    assert totals["months_due"] == 0
    assert totals["pledges"][0] | {} == {"year": 2026, "label": "2026-2027", "amount": 3000.0, "note": "Works 6 months a year",
                                         "paid": 500.0, "waiting": 500.0, "left": 2000.0, "ended": False}
    assert totals["amount_due"] == 2000
    dues = report_service.dues(db)
    # last year (2025-2026, no pledge) is still owed month by month: 12 months
    assert dues["members"][0]["pledge_left"] == 2000 and dues["members"][0]["months_due"] == 12
    # changing it replaces the amount
    seasonal.set_pledge(db, m, 2026, 1000, None, actor_id=1)
    assert _states(db)[1]["pledge_left"] == 0
    with pytest.raises(HTTPException):
        seasonal.set_pledge(db, m, 2026, 0, None, actor_id=1)


def test_not_a_monthly_member(db):
    _pay(db, "2026-08")
    _pay(db, "2026-09", status=ChallanStatus.PENDING, entry_source="import")
    m = db.get(Member, 10)
    out = seasonal.set_monthly_member(db, m, False, actor_id=1)
    assert out == {"monthly_member": False, "removed_unpaid_rows": 1}
    assert m.monthly_amount == 0
    states, totals = _states(db)
    assert states == {"2026-08": "paid", "2026-09": "not_monthly", "2026-10": "not_monthly", "2026-11": "not_monthly"}
    assert totals["months_due"] == 0 and totals["amount_due"] == 0
    assert report_service.dues(db)["members"] == []
    assert ChallanService.get_payable_months(db, 10)["all_months"] == []
    with pytest.raises(HTTPException):
        monthly_amount_for(m, None, "self", "2026-11", db)
    with pytest.raises(HTTPException):
        seasonal.excuse_months(db, m, ["2026-10"], "x", actor_id=1)


def test_paid_list_marks(db):
    _pay(db, "2026-08")
    m = db.get(Member, 10)
    seasonal.excuse_months(db, m, ["2026-09"], "No work", actor_id=1)
    row = report_service.paid_list(db, 2026)["rows"][0]
    assert row["months"][:4] == ["P", "E", "", ""]
    assert row["pending_months"] == 2 and row["excused_months"] == 1 and row["pledge"] is None
    seasonal.set_monthly_member(db, m, False, actor_id=1)
    row = report_service.paid_list(db, 2026)["rows"][0]
    assert row["months"][:4] == ["P", "-", "-", "-"] and row["pending_months"] == 0 and row["monthly_member"] is False


def test_reminders_skip_months_not_owed(db, monkeypatch):
    from app.services import payment_reminder_service as prs

    monkeypatch.setattr(prs, "get_setting", lambda db, key: True if key == "monthly_reminder_enabled" else 5)
    sent = []
    monkeypatch.setattr(prs, "_send", lambda db, member, user, month, label, kind: sent.append(month) or True)
    m = db.get(Member, 10)
    seasonal.excuse_months(db, m, ["2026-11"], "No work", actor_id=1)
    counts = prs.run_due_reminders(db, date(2026, 11, 5))
    assert sent == [] and counts["skipped_not_owed"] == 1
    db.query(ExcusedMonth).delete()
    db.commit()
    prs.run_due_reminders(db, date(2026, 11, 5))
    assert sent == ["2026-11"]
