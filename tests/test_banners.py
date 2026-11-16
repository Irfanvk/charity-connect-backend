"""Occasion banners: who can manage them, validation, and what shows where and when."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import AuditLog, Banner, User, UserRole
from app.services import banner_service as bs


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, username="admin", password_hash="x", role=UserRole.ADMIN))
    session.commit()
    yield session
    session.close()


ADMIN = {"user_id": 1, "role": "admin"}
IST = timezone(timedelta(hours=5, minutes=30))


def _data(**over):
    now = datetime.now(IST)
    data = {
        "title": "Eid Mubarak", "message": "Wishing everyone a blessed Eid", "image_url": "https://img.example/eid.jpg",
        "show_on_login": True, "show_to_members": True, "show_to_admins": False,
        "starts_at": (now - timedelta(hours=1)).isoformat(), "ends_at": (now + timedelta(days=3)).isoformat(),
    }
    data.update(over)
    return data


def test_create_and_show_where_asked(db):
    out = bs.create(db, ADMIN, _data())
    assert out["status"] == "active"
    assert [b["title"] for b in bs.active(db, "login")] == ["Eid Mubarak"]
    assert [b["title"] for b in bs.active(db, "dashboard", "member")] == ["Eid Mubarak"]
    assert bs.active(db, "dashboard", "admin") == []          # not ticked for admins
    assert bs.active(db, "dashboard", None) == []
    assert "show_on_login" not in bs.active(db, "login")[0]    # public view is short
    assert db.query(AuditLog).filter(AuditLog.action == "banner_create").count() == 1


def test_times_are_stored_in_utc_and_respected(db):
    start = datetime(2026, 11, 20, 0, 0, tzinfo=IST)
    out = bs.create(db, ADMIN, _data(starts_at=start.isoformat(), ends_at=(start + timedelta(days=1)).isoformat()))
    row = db.get(Banner, out["id"])
    assert row.starts_at == datetime(2026, 11, 19, 18, 30)    # 00:00 India time = 18:30 UTC the day before
    assert out["status"] in ("scheduled", "past", "active")


def test_scheduled_past_and_paused_are_hidden(db):
    now = datetime.now(IST)
    bs.create(db, ADMIN, _data(title="Later", starts_at=(now + timedelta(days=1)).isoformat(),
                               ends_at=(now + timedelta(days=2)).isoformat()))
    bs.create(db, ADMIN, _data(title="Old", starts_at=(now - timedelta(days=5)).isoformat(),
                               ends_at=(now - timedelta(days=1)).isoformat()))
    paused = bs.create(db, ADMIN, _data(title="Paused"))
    bs.update(db, ADMIN, paused["id"], {"is_active": False})
    assert bs.active(db, "login") == []
    counts = bs.list_all(db, ADMIN)["counts"]
    assert counts == {"active": 0, "scheduled": 1, "paused": 1, "past": 1}


@pytest.mark.parametrize("over", [
    {"title": " "},
    {"image_url": "javascript:alert(1)"},
    {"button_label": "Donate", "button_link": None},
    {"button_label": "Donate", "button_link": "http://insecure.example"},
    {"show_on_login": False, "show_to_members": False, "show_to_admins": False},
    {"ends_at": (datetime.now(IST) - timedelta(days=1)).isoformat()},
    {"ends_at": (datetime.now(IST) + timedelta(days=500)).isoformat()},
    {"message": "x" * 301},
])
def test_validation(db, over):
    with pytest.raises(HTTPException) as exc:
        bs.create(db, ADMIN, _data(**over))
    assert exc.value.status_code == 400


def test_button_links_and_members_cannot_manage(db):
    out = bs.create(db, ADMIN, _data(button_label="Donate", button_link="/Campaigns"))
    assert out["button_link"] == "/Campaigns"
    with pytest.raises(HTTPException) as exc:
        bs.create(db, {"user_id": 1, "role": "member"}, _data())
    assert exc.value.status_code == 403
    edited = bs.update(db, ADMIN, out["id"], {"message": None, "button_label": None, "button_link": None})
    assert edited["message"] is None and edited["button_link"] is None
    bs.delete(db, ADMIN, out["id"])
    assert db.query(Banner).count() == 0
