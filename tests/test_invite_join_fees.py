"""Joining by invite: no crash after the account is saved; new members' fees wait for an admin;
existing members are told their fee on record."""
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services  # noqa: F401  (load order)
from app.database import Base
from app.models.models import (Challan, ChallanStatus, ChallanType, Invite, Member, MemberFee, Notification,
                               User, UserRole)
from app.schemas import UserRegisterWithInvite
from app.services import fee_confirm
from app.services.auth_service import AuthService
from app.services.notification_service import NotificationService

PHONE = "+971501234567"


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    monkeypatch.setattr(NotificationService, "enqueue_user_notification", staticmethod(lambda **k: {"queued": False}))
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)
    admin = User(username="adm", password_hash="x", role=UserRole.ADMIN, is_active=True)
    session.add(admin)
    session.flush()
    session.add(Invite(invite_code="INV-AAAAAA", phone=PHONE, expiry_date=datetime.utcnow() + timedelta(days=3),
                       created_by_admin_id=admin.id))
    session.commit()
    session.admin = admin
    yield session
    session.close()


def _reg(amount):
    return UserRegisterWithInvite(invite_code="INV-AAAAAA", username="newbie", password="Abcdefg1!x", phone=PHONE,
                                  full_name="New Bie", country="AE", city="Dubai", monthly_amount=amount)


def test_new_member_fee_below_minimum_is_refused(db):
    with pytest.raises(HTTPException) as e:
        AuthService.register_with_invite(db, _reg(50))
    assert "at least ₹100" in e.value.detail
    assert db.query(Invite).first().is_used is False  # nothing saved


def test_new_member_joins_and_fee_waits_for_admin(db):
    user = AuthService.register_with_invite(db, _reg(300))  # used to crash here after saving
    member = db.query(Member).filter(Member.user_id == user.id).one()
    assert member.monthly_amount == 300 and member.fee_confirmed is False
    task = db.query(Notification).filter(Notification.user_id == db.admin.id).one()
    assert member.member_code in task.message and "₹300" in task.message
    welcome = db.query(Notification).filter(Notification.user_id == user.id).one()
    assert "waiting for the committee to confirm" in welcome.message
    assert [w["member_id"] for w in fee_confirm.waiting(db)] == [member.id]


def test_admin_confirms_or_changes_the_fee(db):
    user = AuthService.register_with_invite(db, _reg(300))
    member = db.query(Member).filter(Member.user_id == user.id).one()
    db.add(Challan(member_id=member.id, type=ChallanType.MONTHLY, month="2026-11", amount=300,
                   status=ChallanStatus.GENERATED))
    db.commit()
    with pytest.raises(HTTPException):  # a different fee needs a reason
        fee_confirm.confirm(db, member, 500, None, db.admin.id)
    out = fee_confirm.confirm(db, member, 500, "Committee rate for new members", db.admin.id)
    assert out["changed"] and out["unpaid_rows_updated"] == 1
    db.refresh(member)
    assert member.fee_confirmed and member.monthly_amount == 500
    assert db.query(Challan).one().amount == 500
    assert db.query(MemberFee).filter(MemberFee.member_id == member.id).one().amount == 500
    told = db.query(Notification).filter(Notification.user_id == user.id, Notification.title == "Membership approved").one()
    assert "₹500" in told.message and "Committee rate" in told.message
    with pytest.raises(HTTPException):
        fee_confirm.confirm(db, member, None, None, db.admin.id)  # already confirmed
    assert fee_confirm.waiting(db) == []


def test_existing_member_claims_account_and_hears_fee(db):
    old = User(username="offline1", password_hash="x", role=UserRole.MEMBER, phone=PHONE, is_active=False)
    db.add(old)
    db.flush()
    db.add(Member(user_id=old.id, member_code="MEM-0042", full_name="Old Member", monthly_amount=500,
                  join_date=date(2024, 8, 1)))
    db.commit()
    user = AuthService.register_with_invite(db, _reg(0))  # used to crash here after saving
    assert user.id == old.id and user.is_active
    member = db.query(Member).filter(Member.user_id == old.id).one()
    assert member.monthly_amount == 500 and member.fee_confirmed is True  # fee on record kept
    welcome = db.query(Notification).filter(Notification.user_id == old.id).one()
    assert "Your monthly fee on our records is ₹500" in welcome.message
