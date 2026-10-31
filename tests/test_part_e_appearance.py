import importlib
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import AuditLog, User, UserRole
from app.services import settings_service
from app.services.notification_service import NotificationService
from app.utils.auth import get_current_superadmin

admin_router = importlib.import_module("app.routes.admin_router")
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
    u = User(username=name, password_hash="x", role=role, full_name=name.title(), is_active=True)
    db.add(u)
    db.flush()
    return u


def _ctx(user):
    return {"user_id": user.id, "role": user.role.value, "username": user.username}


@pytest.fixture()
def world(db):
    w = {"admin": _user(db, "admin1", UserRole.ADMIN), "super": _user(db, "super", UserRole.SUPERADMIN)}
    db.commit()
    return w


def _set(db, user, **changes):
    return admin_router.update_app_settings(payload=changes, current_user=_ctx(user), db=db)


def test_scheduled_theme_active_only_inside_ist_range(db, world):
    _set(db, world["super"], active_theme="ramadan", theme_schedule_enabled=True,
         theme_start_date="2027-03-01", theme_end_date="2027-03-30")
    resolve = settings_service.resolve_theme
    assert resolve(db, date(2027, 2, 28)) == "default"
    assert resolve(db, date(2027, 3, 1)) == "ramadan"
    assert resolve(db, date(2027, 3, 30)) == "ramadan"
    assert resolve(db, date(2027, 3, 31)) == "default"


def test_unscheduled_theme_always_active_and_bad_inputs_rejected(db, world):
    _set(db, world["super"], active_theme="eid")
    assert settings_service.resolve_theme(db, date(2030, 1, 1)) == "eid"
    for bad in (
        {"active_theme": "neon"},
        {"theme_schedule_enabled": True},
        {"theme_start_date": "2027-03-10", "theme_end_date": "2027-03-01"},
        {"theme_start_date": "01/03/2027"},
    ):
        with pytest.raises(HTTPException) as exc:
            _set(db, world["super"], **bad)
        assert exc.value.status_code == 400


def test_announcement_only_inside_date_range_and_rejects_markup(db, world):
    _set(db, world["super"], announcement_enabled=True, announcement_text="Ramadan Mubarak",
         announcement_start_date="2027-03-01", announcement_end_date="2027-03-30",
         announcement_link_url="https://example.org/zakat")
    active = settings_service.active_announcement
    assert active(db, date(2027, 2, 28)) is None
    banner = active(db, date(2027, 3, 15))
    assert banner["text"] == "Ramadan Mubarak" and banner["link_url"] == "https://example.org/zakat"
    assert active(db, date(2027, 3, 31)) is None

    for bad in (
        {"announcement_text": "<script>alert(1)</script>"},
        {"announcement_text": "x" * 201},
        {"announcement_link_url": "http://insecure.example"},
        {"announcement_link_url": "javascript:alert(1)"},
    ):
        with pytest.raises(HTTPException) as exc:
            _set(db, world["super"], **bad)
        assert exc.value.status_code == 400


def test_message_templates_reject_unknown_placeholders_and_render(db, world):
    with pytest.raises(HTTPException) as exc:
        _set(db, world["super"], msg_payment_approved="Hi {member_name}, {secret} done")
    assert exc.value.status_code == 400 and "{secret}" in exc.value.detail
    with pytest.raises(HTTPException):
        _set(db, world["super"], msg_welcome="x" * 501)
    with pytest.raises(HTTPException):
        _set(db, world["super"], msg_welcome="Broken {org_name")

    _set(db, world["super"], org_display_name="Test Org",
         msg_payment_approved="Thanks {member_name}: {payment} approved by {org_name}")
    text = settings_service.render_message(db, "msg_payment_approved", {"member_name": "Ali", "payment": "P"})
    assert text == "Thanks Ali: P approved by Test Org"

    admin_router.reset_app_setting("msg_payment_approved", current_user=_ctx(world["super"]), db=db)
    assert settings_service.render_message(db, "msg_payment_approved", {"payment": "P"}) == "Your P has been approved."


def test_branding_is_public_and_has_no_private_fields(db, world):
    _set(db, world["super"], org_display_name="Test Org", landing_headline="Welcome",
         payment_upi_id="secret@upi", payment_instructions_text="Pay here",
         support_email="help@example.org", announcement_text="hidden")
    data = settings_routes.get_branding(db=db)
    assert set(data) == {
        "theme", "org_display_name", "org_tagline", "org_logo_url", "landing_headline",
        "landing_subtext", "landing_hero_image_url", "login_welcome_text",
    }
    assert data["org_display_name"] == "Test Org"
    assert "secret@upi" not in str(data) and "Pay here" not in str(data) and "help@example.org" not in str(data)


def test_public_settings_include_payment_details_theme_and_announcement(db, world):
    _set(db, world["super"], payment_upi_id="pay@upi", payment_account_number_masked_display="XXXX 4417")
    data = settings_service.public_settings(db)
    assert data["payment_upi_id"] == "pay@upi"
    assert data["payment_account_number_masked_display"] == "XXXX 4417"
    assert data["theme"] == "default" and data["announcement"] is None


def test_image_fields_accept_uploads_only(db, world):
    _set(db, world["super"], org_logo_url="/uploads/branding/logo.png")
    for bad in ("javascript:alert(1)", "http://x/logo.png", "/uploads/../etc/passwd"):
        with pytest.raises(HTTPException):
            _set(db, world["super"], org_logo_url=bad)


def test_admin_cannot_change_part_e_settings_superadmin_can_and_audited(db, world):
    with pytest.raises(HTTPException) as exc:
        get_current_superadmin(current_user=_ctx(world["admin"]))
    assert exc.value.status_code == 403

    _set(db, world["super"], org_tagline="Serving together")
    row = db.query(AuditLog).filter(AuditLog.action == "app_settings_update").one()
    assert "Serving together" in row.new_values
    assert settings_service.get_setting(db, "org_tagline") == "Serving together"


def test_blank_required_name_rejected_and_invalid_contacts_rejected(db, world):
    for bad in ({"org_display_name": "  "}, {"support_email": "nope"}, {"support_whatsapp_number": "abc"}):
        with pytest.raises(HTTPException):
            _set(db, world["super"], **bad)
