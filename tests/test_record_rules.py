"""The committee's record rules: new members are approved before they log in, payment records
are never deleted once approved (nor with their member or campaign), who uploaded each proof is
kept, members see names only in the directory, and the System wipe needs two superadmins and a
fresh backup."""
import os
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services  # noqa: F401  (load order)
from app.database import Base
from app.models.models import (Campaign, Challan, ChallanStatus, ChallanType, Invite, Member, User, UserRole,
                               WipeApproval)
from app.schemas import UserLogin, UserRegisterWithInvite
from app.services import fee_confirm, wipe_guard
from app.services.auth_service import AuthService
from app.services.campaign_service import CampaignService
from app.services.challan_service import ChallanService
from app.services.member_service import MemberService
from app.services.notification_service import NotificationService
from app.utils.auth import hash_password

PW = "Abcdefg1!x"


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    monkeypatch.setattr(NotificationService, "enqueue_user_notification", staticmethod(lambda **k: {"queued": False}))
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)
    admin = User(username="adm", password_hash=hash_password(PW), role=UserRole.ADMIN, is_active=True)
    s.add(admin)
    s.flush()
    s.add(Invite(invite_code="INV-NEWBIE", phone="+966560000001", expiry_date=datetime.utcnow() + timedelta(days=3),
                 created_by_admin_id=admin.id))
    s.commit()
    s.admin = admin
    yield s
    s.close()


def _join(db):
    return AuthService.register_with_invite(db, UserRegisterWithInvite(
        invite_code="INV-NEWBIE", username="newbie", password=PW, full_name="New Bie",
        country="SA", city="Riyadh", monthly_amount=300))


def _member(db, code="MEM-0100", **kw):
    u = User(username=code.lower(), password_hash="x", role=UserRole.MEMBER, is_active=True)
    db.add(u)
    db.flush()
    m = Member(user_id=u.id, member_code=code, full_name=kw.get("name", "Some One"), monthly_amount=500,
               status="active")
    db.add(m)
    db.commit()
    return m


def _pay(db, m, month="2026-10", status=ChallanStatus.APPROVED, **kw):
    c = Challan(member_id=m.id, type=kw.pop("type", ChallanType.MONTHLY), month=month, amount=500, status=status,
                approved_at=datetime.utcnow() if status == ChallanStatus.APPROVED else None, **kw)
    db.add(c)
    db.commit()
    return c


# ── New members wait for approval ─────────────────────────────────────────

def test_new_member_cannot_log_in_until_approved(db):
    user = _join(db)
    with pytest.raises(HTTPException) as e:
        AuthService.login(db, UserLogin(username="newbie", password=PW))
    assert e.value.status_code == 403 and "waiting for the committee" in e.value.detail
    member = db.query(Member).filter_by(user_id=user.id).one()
    fee_confirm.confirm(db, member, None, None, db.admin.id)
    assert AuthService.login(db, UserLogin(username="newbie", password=PW)).id == user.id


def test_decline_removes_a_new_member_without_payments(db):
    user = _join(db)
    member = db.query(Member).filter_by(user_id=user.id).one()
    with pytest.raises(HTTPException):
        fee_confirm.decline(db, member, "  ", db.admin.id)  # a reason is required
    out = fee_confirm.decline(db, member, "Not known to the committee", db.admin.id)
    assert out["member_code"] == member.member_code
    assert db.query(User).filter_by(username="newbie").first() is None
    assert db.query(Invite).filter_by(invite_code="INV-NEWBIE").one().is_used  # the code can't be reused


def test_decline_refused_when_payments_exist(db):
    user = _join(db)
    member = db.query(Member).filter_by(user_id=user.id).one()
    _pay(db, member, status=ChallanStatus.PENDING, proof_path="/p.jpg")
    with pytest.raises(HTTPException) as e:
        fee_confirm.decline(db, member, "No", db.admin.id)
    assert "payment records" in e.value.detail


# ── Payment records stay ──────────────────────────────────────────────────

def test_payment_approved_once_cannot_be_deleted(db):
    m = _member(db)
    c = _pay(db, m)
    ChallanService.revert_challan(db, c.id, reason="Wrong month", actor_id=db.admin.id)
    with pytest.raises(HTTPException) as e:
        ChallanService.delete_challan(db, c.id)
    assert "stays on record" in e.value.detail
    fresh = _pay(db, m, month="2026-11", status=ChallanStatus.GENERATED)
    ChallanService.delete_challan(db, fresh.id)  # never approved: can go


def test_member_with_payments_cannot_be_deleted_test_member_can(db):
    m = _member(db)
    _pay(db, m)
    with pytest.raises(HTTPException) as e:
        MemberService.delete_member(db, m.id)
    assert "inactive instead" in e.value.detail
    t = _member(db, "TEST-0001")
    _pay(db, t)
    MemberService.delete_member(db, t.id)
    assert db.query(Member).filter_by(member_code="TEST-0001").first() is None


def test_campaign_with_donations_cannot_be_deleted(db):
    m = _member(db)
    camp = Campaign(title="Flood", target_amount=1000, start_date=datetime(2026, 9, 1), created_by_admin_id=db.admin.id)
    db.add(camp)
    db.commit()
    _pay(db, m, month=None, type=ChallanType.CAMPAIGN, campaign_id=camp.id)
    with pytest.raises(HTTPException) as e:
        CampaignService.delete_campaign(db, camp.id)
    assert "must stay linked" in e.value.detail


def test_who_uploaded_the_proof_is_kept(db, monkeypatch):
    from app.services import proof_service

    monkeypatch.setattr(proof_service, "store_proof", lambda *a, **k: ("/private/p.jpg", "abc"))
    m = _member(db)
    c = _pay(db, m, status=ChallanStatus.GENERATED)
    ChallanService.upload_proof(db, c.id, b"%PDF-1.4 x", "p.pdf", uploaded_by=db.admin.id)
    db.refresh(c)
    assert c.proof_uploaded_by_user_id == db.admin.id
    assert c.proof_uploaded_by_name  # e.g. "admin (A..)" for staff, "the committee" for members


# ── Directory ─────────────────────────────────────────────────────────────

def test_members_get_names_only_in_the_directory(db):
    from app.routes.member_routes import get_community_directory

    _member(db, "MEM-0101", name="Aisha")
    mine = get_community_directory(skip=0, limit=50, search=None, _current_user={"role": "member"}, db=db)
    assert all(r.member_code is None and r.status is None for r in mine)
    assert {r.full_name for r in mine} >= {"Aisha"}
    assert get_community_directory(skip=0, limit=50, search="MEM-0101", _current_user={"role": "member"}, db=db) == []
    staff = get_community_directory(skip=0, limit=50, search="MEM-0101", _current_user={"role": "admin"}, db=db)
    assert [r.member_code for r in staff] == ["MEM-0101"]


# ── System wipe ───────────────────────────────────────────────────────────

def test_wipe_needs_a_second_superadmin_and_a_fresh_backup(db, tmp_path, monkeypatch):
    a = User(username="sa1", password_hash=hash_password(PW), role=UserRole.SUPERADMIN, is_active=True)
    b = User(username="sa2", password_hash=hash_password(PW), role=UserRole.SUPERADMIN, is_active=True)
    db.add_all([a, b])
    db.commit()
    req = wipe_guard.request(db, a.id, "Reset the test copy before go-live", PW)
    with pytest.raises(HTTPException):
        wipe_guard.use(db, req.id, a.id)  # not approved yet
    with pytest.raises(HTTPException):
        wipe_guard.approve(db, req.id, a.id, PW)  # can't approve your own request
    with pytest.raises(HTTPException):
        wipe_guard.approve(db, req.id, b.id, "wrong")
    wipe_guard.approve(db, req.id, b.id, PW)
    with pytest.raises(HTTPException):
        wipe_guard.use(db, req.id, b.id)  # only the asker runs it

    marker = tmp_path / "last_ok"
    monkeypatch.setenv("WIPE_BACKUP_MARKER", str(marker))
    with pytest.raises(HTTPException) as e:
        wipe_guard.check_fresh_backup()
    assert "No database backup" in e.value.detail
    marker.write_text("2026-11-24 10:00 OK charity_db.sql.gz.enc 2M")
    old = (datetime.now() - timedelta(hours=3)).timestamp()
    os.utime(marker, (old, old))
    with pytest.raises(HTTPException):
        wipe_guard.check_fresh_backup()
    os.utime(marker, None)
    assert "OK" in wipe_guard.check_fresh_backup()

    wipe_guard.use(db, req.id, a.id)
    db.commit()
    with pytest.raises(HTTPException):
        wipe_guard.use(db, req.id, a.id)  # once only
    assert db.get(WipeApproval, req.id).used_at is not None
