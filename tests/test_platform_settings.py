import asyncio
import io
import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import UploadFile

import importlib

from app.database import Base
from app.models.models import AppSetting, AuditLog, PasswordResetRequest, User, UserRole
from app.services import password_reset_service, settings_service
from app.services.notification_service import NotificationService
from app.utils.auth import get_current_superadmin
from app.utils.permissions import require_reason

admin_router = importlib.import_module("app.routes.admin_router")
file_routes = importlib.import_module("app.routes.file_routes")
settings_routes = importlib.import_module("app.routes.settings_routes")


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    settings_service.invalidate_cache()
    yield session
    session.close()
    settings_service.invalidate_cache()


@pytest.fixture(autouse=True)
def stub_dispatch(monkeypatch):
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)


def _user(db, name, role):
    u = User(
        username=name,
        password_hash="x",
        role=role,
        full_name=name.title(),
        phone=f"+96650{sum(ord(c) * (i + 1) for i, c in enumerate(name)):07d}",
        is_active=True,
    )
    db.add(u)
    db.flush()
    return u


def _ctx(user):
    return {"user_id": user.id, "role": user.role.value, "username": user.username}


@pytest.fixture()
def world(db):
    w = {
        "admin": _user(db, "admin1", UserRole.ADMIN),
        "super": _user(db, "super", UserRole.SUPERADMIN),
        "member": _user(db, "plainmember", UserRole.MEMBER),
    }
    db.commit()
    return w


def test_defaults_when_nothing_stored(db):
    assert settings_service.get_setting(db, "password_reset_link_expiry_minutes") == 30
    assert settings_service.get_setting(db, "proof_max_upload_mb") == 5
    assert settings_service.get_setting(db, "monthly_reminder_enabled") is True
    assert settings_service.get_setting(db, "whatsapp_payment_receipts") is False


def test_member_stats_visible_keeps_stored_value(db):
    db.add(AppSetting(key="member_stats_visible", value="1"))
    db.commit()
    assert settings_service.get_setting(db, "member_stats_visible") is True


def test_superadmin_updates_within_range_and_audit_has_old_and_new(db, world):
    resp = admin_router.update_app_settings(
        {"proof_max_upload_mb": 8, "monthly_reminder_enabled": False},
        current_user=_ctx(world["super"]),
        db=db,
    )
    assert settings_service.get_setting(db, "proof_max_upload_mb") == 8
    assert settings_service.get_setting(db, "monthly_reminder_enabled") is False
    by_key = {s["key"]: s for s in resp.settings}
    assert by_key["proof_max_upload_mb"]["updated_by"] == "Super"

    log = db.query(AuditLog).filter(AuditLog.action == "app_settings_update").one()
    assert json.loads(log.old_values)["proof_max_upload_mb"] == 5
    assert json.loads(log.new_values)["proof_max_upload_mb"] == 8


def test_out_of_range_is_400_and_nothing_saved(db, world):
    with pytest.raises(HTTPException) as exc:
        admin_router.update_app_settings(
            {"proof_max_upload_mb": 8, "login_max_failed_attempts": 99},
            current_user=_ctx(world["super"]),
            db=db,
        )
    assert exc.value.status_code == 400
    assert "must be between 3 and 20" in exc.value.detail
    assert settings_service.get_setting(db, "proof_max_upload_mb") == 5
    assert db.query(AppSetting).count() == 0


def test_wrong_type_and_unknown_key_rejected(db, world):
    for payload in ({"proof_max_upload_mb": "abc"}, {"monthly_reminder_enabled": 1}, {"nope": 1}):
        with pytest.raises(HTTPException) as exc:
            admin_router.update_app_settings(payload, current_user=_ctx(world["super"]), db=db)
        assert exc.value.status_code == 400


def test_min_reason_length_cannot_go_below_10(db, world):
    with pytest.raises(HTTPException) as exc:
        admin_router.update_app_settings({"min_reason_length": 5}, current_user=_ctx(world["super"]), db=db)
    assert exc.value.status_code == 400


def test_admin_cannot_put_settings_but_can_read(db, world):
    with pytest.raises(HTTPException) as exc:
        get_current_superadmin(_ctx(world["admin"]))
    assert exc.value.status_code == 403

    view = admin_router.get_app_settings(current_user=_ctx(world["admin"]), db=db)
    assert view.can_edit is False
    assert len(view.settings) == len(settings_service.SETTINGS_REGISTRY)
    assert {"value", "default", "min", "max", "unit", "label", "description", "category"} <= set(view.settings[0])

    member_view = admin_router.get_app_settings(current_user=_ctx(world["member"]), db=db)
    assert member_view.settings == []


def test_reset_restores_default_and_is_audited(db, world):
    admin_router.update_app_settings({"login_lockout_minutes": 60}, current_user=_ctx(world["super"]), db=db)
    admin_router.reset_app_setting("login_lockout_minutes", current_user=_ctx(world["super"]), db=db)
    assert settings_service.get_setting(db, "login_lockout_minutes") == 15
    log = db.query(AuditLog).filter(AuditLog.action == "app_settings_reset").one()
    assert json.loads(log.old_values) == {"login_lockout_minutes": 60}
    assert json.loads(log.new_values) == {"login_lockout_minutes": 15}


def test_public_endpoint_hides_non_public_keys(db, world):
    public = settings_routes.get_public_settings(current_user=_ctx(world["member"]), db=db)
    assert set(public) == {
        "proof_max_upload_mb",
        "upcoming_months_payable",
        "max_months_per_payment",
        "default_campaign_min_amount",
        "member_stats_visible",
    }


def test_changed_reset_expiry_is_used_by_next_approval(db, world):
    admin_router.update_app_settings(
        {"password_reset_link_expiry_minutes": 120}, current_user=_ctx(world["super"]), db=db
    )
    req = PasswordResetRequest(identifier="plainmember", user_id=world["member"].id, status="pending")
    db.add(req)
    db.commit()
    password_reset_service.approve_request(db, req.id, world["admin"].id)
    db.refresh(req)
    remaining = req.token_expires_at - datetime.utcnow()
    assert timedelta(minutes=119) < remaining <= timedelta(minutes=120)


def test_changed_proof_limit_rejects_larger_file(db, world):
    admin_router.update_app_settings({"proof_max_upload_mb": 1}, current_user=_ctx(world["super"]), db=db)
    big = UploadFile(file=io.BytesIO(b"x" * (2 * 1024 * 1024)), filename="proof.png")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(file_routes.upload_file(file=big, _current_user=_ctx(world["member"]), db=db))
    assert exc.value.status_code == 400
    assert "1MB" in exc.value.detail


def test_min_reason_length_setting_is_enforced(db, world):
    assert require_reason("a" * 10, "Reason", db) == "a" * 10
    admin_router.update_app_settings({"min_reason_length": 30}, current_user=_ctx(world["super"]), db=db)
    with pytest.raises(HTTPException) as exc:
        require_reason("a" * 10, "Reason", db)
    assert exc.value.status_code == 400 and "30" in exc.value.detail
    assert require_reason("a" * 30, "Reason", db)


def test_upcoming_months_setting_caps_payable_months(db, world):
    from app.models.models import Member
    from app.services.challan_service import ChallanService

    member = Member(user_id=world["member"].id, member_code="MEM-0001", monthly_amount=500)
    db.add(member)
    db.commit()

    default = ChallanService.get_payable_months(db, member.id, include_upcoming=True)
    assert len(default["upcoming_months"]) == 3

    admin_router.update_app_settings({"upcoming_months_payable": 1}, current_user=_ctx(world["super"]), db=db)
    capped = ChallanService.get_payable_months(db, member.id, include_upcoming=True, upcoming_count=3)
    assert len(capped["upcoming_months"]) == 1


def test_login_lockout_uses_settings(db):
    from app.services.auth_service import AuthService

    AuthService._failed_login_attempts.clear()
    keys = ["id:setting-test"]
    AuthService._register_failed_attempt(keys, 3, 5)
    AuthService._register_failed_attempt(keys, 3, 5)
    AuthService._register_failed_attempt(keys, 3, 5)
    with pytest.raises(HTTPException) as exc:
        AuthService._assert_not_rate_limited(keys)
    assert exc.value.status_code == 429
    AuthService._failed_login_attempts.clear()


def test_invite_default_expiry_uses_setting(db, world):
    from app.schemas import InviteCreate
    from app.services.invite_service import InviteService

    admin_router.update_app_settings({"invite_default_expiry_days": 14}, current_user=_ctx(world["super"]), db=db)
    invite = InviteService.create_invite(db, InviteCreate(phone="+966500000001"), world["admin"].id)
    remaining = invite.expiry_date - datetime.utcnow()
    assert timedelta(days=13, hours=23) < remaining <= timedelta(days=14)
