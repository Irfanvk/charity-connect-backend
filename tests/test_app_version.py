"""Devices report the web app build they run; admins see who is on the newest one."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import User, UserRole
import importlib

from app.routes import user_routes
from app.schemas.schemas import DeviceStatusUpdate

admin_router = importlib.import_module("app.routes.admin_router")  # the package exports the router object under this name


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _user(db, name, role=UserRole.MEMBER):
    u = User(username=name, password_hash="x", role=role, is_active=True, full_name=name.title())
    db.add(u)
    db.commit()
    return u


def _report(db, user, version):
    request = SimpleNamespace(headers={"user-agent": "Mozilla/5.0 (Linux; Android 14)"})
    payload = DeviceStatusUpdate(notification_permission="granted", device_display_mode="standalone", app_version=version)
    user_routes.report_device_status(payload, request, {"user_id": user.id, "role": "member"}, db)


def test_device_status_stores_app_version(db):
    user = _user(db, "ali")
    _report(db, user, "20261111.0930-4f6ccfa")
    db.refresh(user)
    assert user.app_version == "20261111.0930-4f6ccfa"
    assert user.app_version_seen_at is not None


def test_older_clients_without_version_still_work(db):
    user = _user(db, "basheer")
    request = SimpleNamespace(headers={})
    user_routes.report_device_status(
        DeviceStatusUpdate(notification_permission="default"), request, {"user_id": user.id, "role": "member"}, db,
    )
    db.refresh(user)
    assert user.app_version is None and user.notification_permission == "default"


def test_version_format_is_validated():
    with pytest.raises(ValidationError):
        DeviceStatusUpdate(notification_permission="granted", app_version="<script>")


def test_overview_counts_users_on_latest_version(db):
    admin = _user(db, "boss", UserRole.SUPERADMIN)
    old, new1, new2 = _user(db, "old"), _user(db, "new1"), _user(db, "new2")
    _user(db, "never")
    _report(db, old, "20261101.1000-aaaaaaa")
    _report(db, new1, "20261111.0930-4f6ccfa")
    _report(db, new2, "20261111.0930-4f6ccfa")

    result = admin_router.get_notification_delivery_overview(
        search="", skip=0, limit=50, current_user={"user_id": admin.id, "role": "superadmin"}, db=db,
    )
    assert result["latest_app_version"] == "20261111.0930-4f6ccfa"
    assert result["users_on_latest_version"] == 2
    assert result["by_app_version"]["20261101.1000-aaaaaaa"] == 1
    assert result["by_app_version"]["not reported"] == 2  # the admin and "never"
    rows = {r["username"]: r for r in result["users"]}
    assert rows["new1"]["on_latest_version"] is True
    assert rows["old"]["on_latest_version"] is False
