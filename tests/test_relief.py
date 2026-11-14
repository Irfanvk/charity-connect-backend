"""Relief fund: eligibility warnings, hard rules, 3 approvals, fund use entry, paid, member view."""
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import (AuditLog, Challan, ChallanStatus, ChallanType, FundUtilization, Member, Notification,
                               ReliefClaim, User, UserRole)
from app.services import relief_service as relief
from app.services import report_service as rs
from app.services.notification_service import NotificationService

DOCS = {
    "death": [{"kind": "application", "url": "https://files.example/a.pdf"},
              {"kind": "death_certificate", "url": "https://files.example/d.pdf"}],
    "illness": [{"kind": "application", "url": "https://files.example/a.pdf"},
                {"kind": "medical_report", "url": "https://files.example/m.pdf"}],
    "retirement": [{"kind": "application", "url": "https://files.example/a.pdf"},
                   {"kind": "gulf_proof", "url": "https://files.example/g.pdf"}],
}


@pytest.fixture()
def db(monkeypatch):
    today = date(2026, 11, 14)
    monkeypatch.setattr(rs, "today_business", lambda: today)
    monkeypatch.setattr(relief, "today_business", lambda: today)
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _user(db, name, role):
    u = User(username=name, full_name=name.title(), password_hash="x", role=role, is_active=True)
    db.add(u)
    db.flush()
    return u


def _ctx(u):
    return {"user_id": u.id, "role": u.role.value.lower(), "username": u.username}


@pytest.fixture()
def world(db):
    admins = [_user(db, f"admin{i}", UserRole.ADMIN) for i in range(1, 5)]
    sup = _user(db, "super", UserRole.SUPERADMIN)
    mu = _user(db, "rahul", UserRole.MEMBER)
    member = Member(user_id=mu.id, member_code="MEM-0001", full_name="Rahul K", monthly_amount=500,
                    join_date=datetime(2024, 8, 1), country="AE")
    db.add(member)
    db.flush()
    # Paid every month Aug 2024 .. Sep 2026; Oct and Nov 2026 unpaid (Oct overdue, Nov is this month)
    for month in rs._months(date(2024, 8, 1), date(2026, 9, 1)):
        db.add(Challan(member_id=member.id, type=ChallanType.MONTHLY, month=month, amount=500,
                       status=ChallanStatus.APPROVED, payment_method="cash"))
    db.commit()
    return {"admins": admins, "super": sup, "member_user": mu, "member": member}


def _claim(db, world, reason="death", creator=0, **extra):
    data = {"member_id": world["member"].id, "reason": reason, "receiver_name": "Ayesha", "receiver_relation": "wife",
            "documents": DOCS[reason], **extra}
    if reason == "illness":
        data.setdefault("illness_type", "cancer")
    if reason == "retirement":
        data.setdefault("gulf_from_year", 2010)
        data.setdefault("gulf_to_year", 2026)
    return relief.create_claim(db, _ctx(world["admins"][creator]), data)


def test_eligibility_checks(db, world):
    out = relief.eligibility(db, world["member"], "death")
    checks = {c["key"]: c for c in out["checks"]}
    assert checks["unpaid_months"]["value"] == 1 and checks["unpaid_months"]["ok"] is True
    assert checks["membership_months"]["ok"] is True
    assert checks["first_year_paid"]["ok"] is True
    assert checks["lives_abroad"]["ok"] is True
    assert out["all_ok"] is True
    # Lives in India and unpaid for 4 overdue months -> warnings, not blocks
    world["member"].country = "IN"
    db.query(Challan).filter(Challan.month.in_(["2026-07", "2026-08", "2026-09"])).delete(synchronize_session=False)
    db.commit()
    out = relief.eligibility(db, world["member"], "death")
    assert set(out["warnings"]) == {"unpaid_months", "lives_abroad"}
    retire = relief.eligibility(db, world["member"], "retirement", 2020, 2026)
    assert "lives_abroad" not in retire["warnings"] and "gulf_years" in retire["warnings"]


def test_first_year_rule(db, world):
    db.query(Challan).filter(Challan.month == "2024-12").delete()
    db.commit()
    out = relief.eligibility(db, world["member"], "illness")
    first = next(c for c in out["checks"] if c["key"] == "first_year_paid")
    assert first["ok"] is False and first["months"] == ["2024-12"]


def test_hard_rules_on_create(db, world):
    with pytest.raises(HTTPException) as exc:
        _claim(db, world, documents=DOCS["death"][:1])
    assert "death certificate" in exc.value.detail
    with pytest.raises(HTTPException):
        _claim(db, world, amount=10000)  # below the ₹50,000 default
    with pytest.raises(HTTPException):
        _claim(db, world, receiver_relation="self")
    with pytest.raises(HTTPException):
        _claim(db, world, reason="illness", illness_type="flu")
    with pytest.raises(HTTPException):
        _claim(db, world, reason="retirement", gulf_from_year=None)
    with pytest.raises(HTTPException):
        _claim(db, world, documents=[{"kind": "application", "url": "javascript:alert(1)"}])
    with pytest.raises(HTTPException) as exc:
        relief.create_claim(db, {"user_id": world["member_user"].id, "role": "member"}, {})
    assert exc.value.status_code == 403


def test_three_approvals_then_fund_use_then_paid(db, world):
    claim = _claim(db, world, amount=60000)
    assert claim["status"] == "pending" and claim["amount"] == 60000 and claim["approvals_needed"] == 3
    assert claim["eligibility"]["all_ok"] is True
    a = world["admins"]
    with pytest.raises(HTTPException) as exc:
        relief.approve(db, _ctx(a[0]), claim["id"])  # the creator
    assert exc.value.status_code == 403
    relief.approve(db, _ctx(a[1]), claim["id"])
    with pytest.raises(HTTPException):
        relief.approve(db, _ctx(a[1]), claim["id"])  # twice
    out = relief.approve(db, _ctx(a[2]), claim["id"], note="ok")
    assert out["status"] == "pending" and out["approvals_count"] == 2
    assert db.query(FundUtilization).count() == 0
    out = relief.approve(db, _ctx(world["super"]), claim["id"])
    assert out["status"] == "approved" and out["can_mark_paid"] is True
    fund = db.query(FundUtilization).one()
    assert (fund.amount, fund.status, fund.category, fund.recipient) == (60000, "approved", "Relief", "Ayesha")
    with pytest.raises(HTTPException):
        relief.mark_paid(db, _ctx(a[0]), claim["id"], {"paid_on": "2026-11-30", "method": "cash"})  # future
    paid = relief.mark_paid(db, _ctx(a[0]), claim["id"], {"paid_on": "2026-11-14", "method": "bank_transfer",
                                                          "reference": "UTR123"})
    assert paid["status"] == "paid" and paid["paid_reference"] == "UTR123"
    titles = {n.title for n in db.query(Notification).filter(Notification.user_id == world["member_user"].id)}
    assert {"Relief claim opened", "Relief approved", "Relief paid"} <= titles
    actions = {a.action for a in db.query(AuditLog).all()}
    assert {"relief_claim_create", "relief_claim_approve", "relief_claim_paid"} <= actions


def test_one_rejection_stops(db, world):
    claim = _claim(db, world, reason="illness")
    relief.approve(db, _ctx(world["admins"][1]), claim["id"])
    with pytest.raises(HTTPException):
        relief.reject(db, _ctx(world["admins"][2]), claim["id"], "  ")
    out = relief.reject(db, _ctx(world["admins"][2]), claim["id"], "Report is not clear")
    assert out["status"] == "rejected" and out["rejection_reason"] == "Report is not clear"
    with pytest.raises(HTTPException):
        relief.approve(db, _ctx(world["admins"][3]), claim["id"])
    # A rejected claim does not block a new one for the same reason
    assert _claim(db, world, reason="illness")["status"] == "pending"


def test_once_per_reason(db, world):
    _claim(db, world, reason="retirement")
    with pytest.raises(HTTPException) as exc:
        _claim(db, world, reason="retirement")
    assert exc.value.status_code == 409
    assert _claim(db, world, reason="illness")["status"] == "pending"  # another reason is fine
    out = relief.eligibility(db, world["member"], "illness")
    assert out["blocked_reasons"] == ["illness", "retirement"]


def test_cancel_and_lists(db, world):
    claim = _claim(db, world)
    with pytest.raises(HTTPException):
        relief.cancel(db, _ctx(world["admins"][1]), claim["id"], "duplicate")  # not the creator
    lst = relief.list_claims(db, _ctx(world["admins"][1]), "to_decide")
    assert [c["id"] for c in lst["items"]] == [claim["id"]] and lst["counts"]["to_decide"] == 1
    assert relief.list_claims(db, _ctx(world["admins"][0]), "to_decide")["items"] == []  # own claim
    out = relief.cancel(db, _ctx(world["admins"][0]), claim["id"], "Entered twice")
    assert out["status"] == "cancelled"
    assert relief.list_claims(db, _ctx(world["admins"][1]), search="rahul")["counts"]["cancelled"] == 1


def test_member_view_hides_bank_details(db, world):
    _claim(db, world, receiver_bank_account="123456789")
    me = relief.my_relief(db, {"user_id": world["member_user"].id, "role": "member"})
    assert me["scheme"]["amounts"] == {"death": 50000, "illness": 40000, "retirement": 40000}
    assert me["eligibility"]["all_ok"] is True
    assert len(me["claims"]) == 1 and "receiver" not in me["claims"][0]
    assert db.query(ReliefClaim).one().receiver_bank_account == "123456789"
