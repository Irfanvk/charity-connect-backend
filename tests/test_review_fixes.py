from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import (
    AuditLog,
    FundUtilization,
    Member,
    Notification,
    PasswordResetRequest,
    User,
    UserRole,
)
from app.routes import password_reset_routes
from app.schemas.schemas import PasswordResetApprove
from app.services import password_reset_service
from app.services.notification_service import NotificationService


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def stub_dispatch(monkeypatch):
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)


def _user(db, name, role, active=True):
    u = User(
        username=name,
        password_hash="x",
        role=role,
        full_name=name.title(),
        phone=f"+96650{sum(ord(c) * (i + 1) for i, c in enumerate(name)):07d}",
        is_active=active,
    )
    db.add(u)
    db.flush()
    return u


def _ctx(user):
    return {"user_id": user.id, "role": user.role.value, "username": user.username}


@pytest.fixture()
def world(db):
    w = {
        "admin1": _user(db, "admin1", UserRole.ADMIN),
        "admin2": _user(db, "admin2", UserRole.ADMIN),
        "super": _user(db, "super", UserRole.SUPERADMIN),
        "member": _user(db, "plainmember", UserRole.MEMBER),
    }
    db.commit()
    return w


def _reset(db, target, status="pending"):
    req = PasswordResetRequest(identifier=target.username, user_id=target.id, status=status)
    db.add(req)
    db.commit()
    return req


def _forbidden(fn, *args, **kwargs):
    with pytest.raises(HTTPException) as exc:
        fn(*args, **kwargs)
    assert exc.value.status_code == 403
    return exc.value.detail


# ── Issue 1: password reset ──────────────────────────────────────────────────

def test_admin_cannot_approve_or_reject_reset_for_another_admin(db, world):
    req = _reset(db, world["admin1"])
    detail = _forbidden(password_reset_service.approve_request, db, req.id, world["admin2"].id)
    assert detail == "Password resets for admin accounts must be handled by the superadmin"
    _forbidden(password_reset_service.reject_request, db, req.id, world["admin2"].id, "no reason given")
    db.refresh(req)
    assert req.status == "pending" and req.reset_token is None


def test_superadmin_can_approve_and_reject_admin_reset(db, world):
    req = _reset(db, world["admin1"])
    approved = password_reset_service.approve_request(db, req.id, world["super"].id)
    assert approved.status == "approved" and approved.reset_token

    req2 = _reset(db, world["admin2"])
    rejected = password_reset_service.reject_request(db, req2.id, world["super"].id, "not verified")
    assert rejected.status == "rejected"


def test_admin_can_approve_member_reset_but_not_own(db, world):
    req = _reset(db, world["member"])
    assert password_reset_service.approve_request(db, req.id, world["admin1"].id).status == "approved"

    own = _reset(db, world["admin1"])
    _forbidden(password_reset_service.approve_request, db, own.id, world["admin1"].id)
    _forbidden(password_reset_service.reject_request, db, own.id, world["admin1"].id, "no reason given")


def test_superadmin_own_reset_needs_other_superadmin(db, world):
    req = _reset(db, world["super"])
    # only one superadmin exists: nobody can resolve it through the app
    detail = _forbidden(password_reset_service.approve_request, db, req.id, world["super"].id)
    assert detail == "Superadmin password resets must be done from the server with seed_admin.py"
    detail = _forbidden(password_reset_service.approve_request, db, req.id, world["admin1"].id)
    assert detail == "Superadmin password resets must be done from the server with seed_admin.py"

    other = _user(db, "super2", UserRole.SUPERADMIN)
    db.commit()
    # own approval still blocked, and admins still cannot
    assert "your own" in _forbidden(password_reset_service.approve_request, db, req.id, world["super"].id)
    _forbidden(password_reset_service.approve_request, db, req.id, world["admin1"].id)
    assert password_reset_service.approve_request(db, req.id, other.id).status == "approved"


def test_inactive_superadmin_does_not_count_as_other_superadmin(db, world):
    _user(db, "super_off", UserRole.SUPERADMIN, active=False)
    req = _reset(db, world["super"])
    db.commit()
    detail = _forbidden(password_reset_service.approve_request, db, req.id, world["super"].id)
    assert "seed_admin.py" in detail


def test_list_endpoint_never_contains_token_but_approve_does(db, world):
    req = _reset(db, world["member"])
    admin = _ctx(world["admin1"])

    approved = password_reset_routes.approve_request(
        req.id, PasswordResetApprove(admin_notes=None), db=db, current_user=admin
    )
    db.refresh(req)
    token = req.reset_token
    assert token
    assert token in (approved.whatsapp_chat_url or "")

    for status_filter in (None, "approved"):
        items = password_reset_routes.list_requests(
            request_status=status_filter, skip=0, limit=50, db=db, current_user=admin
        )
        assert items
        for item in items:
            assert token not in (item.whatsapp_chat_url or "")
            assert token not in item.model_dump_json()


def test_token_expiry_is_30_minutes_and_single_use(db, world):
    req = _reset(db, world["member"])
    password_reset_service.approve_request(db, req.id, world["admin1"].id)
    db.refresh(req)
    token = req.reset_token
    remaining = req.token_expires_at - datetime.utcnow()
    assert timedelta(minutes=29) < remaining <= timedelta(minutes=30)

    assert password_reset_service.verify_token(db, token) is not None
    password_reset_service.complete_reset(db, token, "NewPassw0rd!")
    db.refresh(req)
    assert req.status == "used"
    assert password_reset_service.verify_token(db, token) is None
    with pytest.raises(ValueError):
        password_reset_service.complete_reset(db, token, "Another1!")


def test_expired_token_is_rejected(db, world):
    req = _reset(db, world["member"])
    password_reset_service.approve_request(db, req.id, world["admin1"].id)
    db.refresh(req)
    token = req.reset_token
    req.token_expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    assert password_reset_service.verify_token(db, token) is None
    with pytest.raises(ValueError):
        password_reset_service.complete_reset(db, token, "NewPassw0rd!")


def test_reset_actions_are_audited_with_target_and_role(db, world):
    req = _reset(db, world["admin1"])
    password_reset_service.approve_request(db, req.id, world["super"].id)
    db.refresh(req)
    password_reset_service.complete_reset(db, req.reset_token, "NewPassw0rd!")

    rej = _reset(db, world["member"])
    password_reset_service.reject_request(db, rej.id, world["admin2"].id, "cannot verify identity")

    logs = {a.action: a for a in db.query(AuditLog).filter(AuditLog.entity_type == "PasswordResetRequest")}
    assert {"password_reset_approve", "password_reset_complete", "password_reset_reject"} <= set(logs)
    assert f'"target_user_id": {world["admin1"].id}' in logs["password_reset_approve"].new_values
    assert '"target_role": "admin"' in logs["password_reset_approve"].new_values
    assert '"target_role": "member"' in logs["password_reset_reject"].new_values
    assert logs["password_reset_complete"].user_id == world["admin1"].id


# ── Issue 2: proof-upload notifications ──────────────────────────────────────

def _member_for(db, user):
    m = Member(user_id=user.id, member_code=f"M-{user.username}", full_name=user.full_name)
    db.add(m)
    db.commit()
    return m


def _recipients(db):
    return {n.user_id for n in db.query(Notification).all()}


def test_admin_own_proof_notifies_other_active_admins_only(db, world):
    inactive = _user(db, "admin_off", UserRole.ADMIN, active=False)
    member = _member_for(db, world["admin1"])

    NotificationService.notify_admins_proof_uploaded(db, member, ["2026-10"], world["admin1"].id)

    assert _recipients(db) == {world["admin2"].id, world["super"].id}
    assert inactive.id not in _recipients(db)
    for n in db.query(Notification).all():
        assert n.message.endswith("(admin's own payment — please review)")


def test_superadmin_own_proof_excludes_uploader(db, world):
    member = _member_for(db, world["super"])
    NotificationService.notify_admins_proof_uploaded(db, member, ["2026-10"], world["super"].id)
    assert _recipients(db) == {world["admin1"].id, world["admin2"].id}


def test_member_upload_notifies_all_active_admins_without_suffix(db, world):
    _user(db, "admin_off", UserRole.ADMIN, active=False)
    member = _member_for(db, world["member"])

    NotificationService.notify_admins_proof_uploaded(db, member, ["2026-10"], world["member"].id)

    assert _recipients(db) == {world["admin1"].id, world["admin2"].id, world["super"].id}
    for n in db.query(Notification).all():
        assert "admin's own payment" not in n.message


def test_fund_utilization_created_skips_inactive_and_creator(db, world):
    inactive = _user(db, "admin_off", UserRole.ADMIN, active=False)
    util = FundUtilization(
        title="Medical aid",
        amount=1000,
        date=datetime.utcnow(),
        registered_by_admin_id=world["admin1"].id,
        status="pending",
    )
    db.add(util)
    db.commit()

    NotificationService.notify_fund_utilization_created(db, util)

    assert _recipients(db) == {world["admin2"].id, world["super"].id}
    assert inactive.id not in _recipients(db)
