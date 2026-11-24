"""Joining by invite without re-typing: existing members confirm with the last 4 digits of their
mobile, new members get the invite's contacts, and mobiles written differently still match."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services  # noqa: F401  (load order)
from app.database import Base
from app.models.models import Invite, Member, User, UserRole
from app.schemas import UserRegisterWithInvite
from app.services.auth_service import AuthService
from app.services.invite_service import InviteService
from app.services.notification_service import NotificationService
from app.utils.phones import mask_email, mask_phone, phones_match

ON_RECORD = "+971501234567"


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    monkeypatch.setattr(NotificationService, "enqueue_user_notification", staticmethod(lambda **k: {"queued": False}))
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)
    admin = User(username="adm", password_hash="x", role=UserRole.ADMIN, is_active=True)
    # An offline member the committee entered (no login yet), with no location on record.
    offline = User(username="mem-0045", password_hash="x", role=UserRole.MEMBER, is_active=False,
                   phone=ON_RECORD, full_name="Latheef Haji Universal")
    s.add_all([admin, offline])
    s.flush()
    s.add(Member(user_id=offline.id, member_code="MEM-0045", full_name="Latheef Haji Universal",
                 monthly_amount=1000, status="active"))
    # The admin typed the local form of the same mobile on the invite.
    s.add(Invite(invite_code="INV-OLD001", phone="050 123 4567", expiry_date=datetime.utcnow() + timedelta(days=3),
                 created_by_admin_id=admin.id))
    s.add(Invite(invite_code="INV-NEW001", phone="+966560000001", expiry_date=datetime.utcnow() + timedelta(days=3),
                 created_by_admin_id=admin.id))
    s.commit()
    s.offline = offline
    yield s
    s.close()


def test_phone_helpers():
    assert phones_match("+971501234567", "00971 50 123 4567")
    assert phones_match("0501234567", "+971501234567")
    assert phones_match("9746284416", "+919746284416")
    assert not phones_match("+971501234567", "+971501234568")
    assert not phones_match("4567", "+971501234567")  # too short to be a local number
    assert mask_phone("+971501234567") == "+971 ••••• 4567"
    assert mask_email("latheef@gmail.com") == "l•••@gmail.com"


def test_preview_for_existing_and_new_member(db):
    old = InviteService.signup_preview(db, db.query(Invite).filter_by(invite_code="INV-OLD001").one())
    assert old["registration_mode"] == "existing_member" and old["has_account"] is False
    assert old["member"] == {"full_name": "Latheef Haji Universal", "member_code": "MEM-0045",
                             "phone_hint": "+971 ••••• 4567", "email_hint": None, "check": "phone_last4",
                             "needs_location": True}
    new = InviteService.signup_preview(db, db.query(Invite).filter_by(invite_code="INV-NEW001").one())
    assert new == {"registration_mode": "new_member", "invite_email": None, "invite_phone": "+966560000001"}


def test_admin_sees_the_match(db):
    hit = InviteService.match_contacts(db, phone="0501234567")
    assert hit["member_code"] == "MEM-0045" and hit["has_account"] is False
    assert InviteService.match_contacts(db, phone="+966560000001") is None


def _existing(**kw):
    base = dict(invite_code="INV-OLD001", username="latheef", password="Abcdefg1!x",
                full_name="Latheef Haji Universal", country="AE", city="Dubai", monthly_amount=0)
    base.update(kw)
    return UserRegisterWithInvite(**base)


def test_existing_member_joins_with_last_four_digits(db):
    with pytest.raises(HTTPException) as e:
        AuthService.register_with_invite(db, _existing(verify="1111"))
    assert "last 4 digits" in e.value.detail
    with pytest.raises(HTTPException) as e:
        AuthService.register_with_invite(db, _existing())  # no check at all
    assert "last 4 digits" in e.value.detail
    user = AuthService.register_with_invite(db, _existing(verify="4567", full_name="Latheef H Universal"))
    assert user.id == db.offline.id and user.is_active and user.username == "latheef"
    assert user.phone == ON_RECORD  # the committee's number is kept, not the invite's local form
    member = db.query(Member).filter_by(user_id=user.id).one()
    assert member.full_name == "Latheef H Universal"  # they may correct their name
    assert (member.country, member.city) == ("AE", "Dubai")  # location saved (used to be dropped)
    assert db.query(Invite).filter_by(invite_code="INV-OLD001").one().is_used


def test_existing_member_who_already_has_an_account_is_sent_to_login(db):
    db.offline.is_active = True
    db.commit()
    with pytest.raises(HTTPException) as e:
        AuthService.register_with_invite(db, _existing(verify="4567"))
    assert e.value.status_code == 409 and "already has an account" in e.value.detail


def test_older_app_sending_the_full_mobile_still_works(db):
    user = AuthService.register_with_invite(db, _existing(phone="+971 50 123 4567"))
    assert user.id == db.offline.id


def test_new_member_needs_no_contacts_typed(db):
    user = AuthService.register_with_invite(db, UserRegisterWithInvite(
        invite_code="INV-NEW001", username="newbie", password="Abcdefg1!x", full_name="New Bie",
        country="SA", city="Riyadh", monthly_amount=300))
    assert user.phone == "+966560000001" and user.email is None  # email optional for a mobile invite
    with pytest.raises(HTTPException):
        AuthService.register_with_invite(db, UserRegisterWithInvite(
            invite_code="INV-NEW001", username="other", password="Abcdefg1!x", phone="+966560000099",
            full_name="X", country="SA", city="Riyadh", monthly_amount=300))
