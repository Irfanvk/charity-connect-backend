"""Admin reports: member statement, dues, payments list and year grid."""
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import Campaign, Challan, ChallanStatus, ChallanType, Member, User, UserRole
from app.services import report_service as rs


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setattr(rs, "today_business", lambda: date(2026, 11, 14))
    monkeypatch.setattr(rs, "org_name", lambda db: "Test Org")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _member(db, code, name, *, fee=500, joined=datetime(2026, 7, 10), country="AE", status="active", phone=None):
    user = User(username=code.lower(), password_hash="x", role=UserRole.MEMBER, is_active=True, phone=phone)
    db.add(user)
    db.flush()
    m = Member(user_id=user.id, member_code=code, full_name=name, monthly_amount=fee, join_date=joined,
               country=country, status=status)
    db.add(m)
    db.flush()
    return m


def _pay(db, m, month, status, **kw):
    c = Challan(member_id=m.id, type=ChallanType.MONTHLY, month=month, amount=kw.pop("amount", 500),
                status=status, payment_method=kw.pop("method", "cash"), **kw)
    db.add(c)
    db.flush()
    return c


@pytest.fixture()
def world(db):
    aisha = _member(db, "MEM-0001", "Aisha", phone="+971501234567")
    _pay(db, aisha, "2026-07", ChallanStatus.APPROVED, approved_at=datetime(2026, 7, 20))
    _pay(db, aisha, "2026-08", ChallanStatus.PENDING, proof_path="/p.jpg")          # waiting
    _pay(db, aisha, "2026-09", ChallanStatus.GENERATED)                              # not paid
    _pay(db, aisha, "2026-10", ChallanStatus.REJECTED, rejection_reason="blurry")    # not paid
    _pay(db, aisha, "2026-12", ChallanStatus.APPROVED, approved_at=datetime(2026, 11, 1))  # ahead
    camp = Campaign(title="Flood relief", target_amount=1000, start_date=datetime(2026, 9, 1), created_by_admin_id=aisha.user_id)
    db.add(camp)
    db.flush()
    db.add(Challan(member_id=aisha.id, type=ChallanType.CAMPAIGN, campaign_id=camp.id, amount=250,
                   status=ChallanStatus.APPROVED, payment_method="upi", created_at=datetime(2026, 9, 5)))
    rahul = _member(db, "MEM-0002", "Rahul", fee=300, joined=datetime(2026, 10, 1), country="IN")
    _pay(db, rahul, "2026-10", ChallanStatus.APPROVED, amount=300)
    _pay(db, rahul, "2026-11", ChallanStatus.APPROVED, amount=300)
    _member(db, "MEM-0003", "Old Omar", fee=200, joined=datetime(2026, 9, 1), status="inactive")
    db.commit()
    return {"aisha": aisha, "rahul": rahul, "campaign": camp}


def test_statement_months_and_totals(db, world):
    out = rs.member_statement(db, world["aisha"].id)
    states = {r["month"]: r["state"] for r in out["months"]}
    assert states == {"2026-07": "paid", "2026-08": "waiting", "2026-09": "not_paid", "2026-10": "not_paid",
                      "2026-11": "not_paid", "2026-12": "paid"}
    assert out["from_month"] == "2026-07" and out["to_month"] == "2026-11"
    t = out["totals"]
    assert (t["months_paid"], t["amount_paid"]) == (2, 1000)
    assert (t["months_waiting"], t["months_due"], t["amount_due"]) == (1, 3, 1500)
    assert t["months_overdue"] == 2 and t["this_month_due"] is True
    assert t["last_paid_month"] == "2026-12"
    assert t["paid_up_to"] == "2026-08" and t["due_months"] == ["2026-09", "2026-10", "2026-11"]
    oct_row = next(r for r in out["months"] if r["month"] == "2026-10")
    assert oct_row["note"] == "blurry"
    assert out["donations"] == [{"date": "2026-09-05", "campaign": "Flood relief", "amount": 250.0, "state": "paid"}]
    assert out["donations_total"] == 250 and out["organisation"] == "Test Org"
    assert out["member"]["country_name"] == "United Arab Emirates"


def test_statement_range_and_errors(db, world):
    out = rs.member_statement(db, world["aisha"].id, from_month="2026-09", to_month="2026-10")
    assert [r["month"] for r in out["months"]] == ["2026-09", "2026-10", "2026-12"]
    with pytest.raises(HTTPException):
        rs.member_statement(db, world["aisha"].id, from_month="2026-11", to_month="2026-10")
    with pytest.raises(HTTPException):
        rs.member_statement(db, world["aisha"].id, from_month="Nov")
    with pytest.raises(HTTPException):
        rs.member_statement(db, 9999)


def test_dues_list(db, world):
    out = rs.dues(db)
    assert [m["member_code"] for m in out["members"]] == ["MEM-0001"]  # Rahul is paid up, Omar inactive
    assert out["total_amount_due"] == 1500 and out["members_with_dues"] == 1
    assert out["members"][0]["phone"] == "+971501234567"
    every = rs.dues(db, status="all", sort="name")
    assert [m["name"] for m in every["members"]] == ["Aisha", "Old Omar"]
    assert next(m for m in every["members"] if m["name"] == "Old Omar")["months_due"] == 3
    assert rs.dues(db, min_months=4)["members"] == []
    assert rs.dues(db, country="IN")["members"] == []
    assert rs.dues(db, search="aish")["members_with_dues"] == 1
    with pytest.raises(HTTPException):
        rs.dues(db, sort="random")


def test_payments_filters_and_totals(db, world):
    out = rs.payments(db)
    assert out["total"] == 8
    assert out["totals"]["paid"] == {"count": 5, "amount": 1850.0}
    assert out["totals"]["waiting"]["count"] == 1 and out["totals"]["not_paid"]["count"] == 1
    assert out["totals"]["rejected"]["count"] == 1
    codes = lambda **kw: [(i["member_code"], i["month"] or i["campaign"]) for i in rs.payments(db, **kw)["items"]]
    assert codes(state="waiting") == [("MEM-0001", "2026-08")]
    assert codes(type="campaign") == [("MEM-0001", "Flood relief")]
    assert codes(month_from="2026-11", month_to="2026-11") == [("MEM-0002", "2026-11")]
    assert ("MEM-0001", "Flood relief") in codes(month_from="2026-09", month_to="2026-09")
    assert codes(country="IN", sort="month_asc") == [("MEM-0002", "2026-10"), ("MEM-0002", "2026-11")]
    assert len(codes(search="rahul")) == 2
    assert codes(method="upi") == [("MEM-0001", "Flood relief")]
    page = rs.payments(db, limit=3)
    assert len(page["items"]) == 3 and page["has_more"] is True
    with pytest.raises(HTTPException):
        rs.payments(db, state="maybe")
    with pytest.raises(HTTPException):
        rs.payments(db, sort="random")


def test_year_grid(db, world):
    out = rs.year_grid(db, 2026)
    rows = {r["member_code"]: r for r in out["rows"]}
    aisha = rows["MEM-0001"]["months"]
    assert aisha[:6] == ["before_join"] * 6
    assert aisha[6:] == ["paid", "waiting", "not_paid", "not_paid", "not_paid", "paid"]
    rahul = rows["MEM-0002"]["months"]
    assert rahul[9:] == ["paid", "paid", "future"]
    assert "MEM-0003" not in rows  # inactive
    with pytest.raises(HTTPException):
        rs.year_grid(db, 2020)
