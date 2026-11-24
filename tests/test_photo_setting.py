"""The superadmin decides in Settings who changes their own profile photo straight away:
members (one switch) and admins/executives (another). Off = the photo waits for approval."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services  # noqa: F401  (load order)
from app.database import Base
from app.models.models import Member, User, UserRole
from app.routes.auth_routes import _require_photo_request, photo_change_is_direct
from app.services import settings_service


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    settings_service._cache.clear()
    sa = User(username="sa", password_hash="x", role=UserRole.SUPERADMIN, is_active=True)
    adm = User(username="adm", password_hash="x", role=UserRole.ADMIN, is_active=True)
    mem = User(username="mem", password_hash="x", role=UserRole.MEMBER, is_active=True)
    s.add_all([sa, adm, mem])
    s.flush()
    s.add_all([Member(user_id=adm.id, member_code="MEM-0001", monthly_amount=500, status="active"),
               Member(user_id=mem.id, member_code="MEM-0002", monthly_amount=500, status="active")])
    s.commit()
    s.users = {"sa": sa, "adm": adm, "mem": mem}
    yield s
    settings_service._cache.clear()
    s.close()


def _who(db, name):
    u = db.users[name]
    return {"user_id": u.id, "role": u.role.value}


def test_default_everyone_with_a_member_record_needs_approval(db):
    with pytest.raises(HTTPException):
        _require_photo_request(db, _who(db, "mem"))
    with pytest.raises(HTTPException):
        _require_photo_request(db, _who(db, "adm"))
    _require_photo_request(db, _who(db, "sa"))  # superadmin without a member record: always direct


def test_switches_are_separate(db):
    settings_service.update_settings(db, {"members_can_change_photo": True}, db.users["sa"].id)
    settings_service._cache.clear()
    _require_photo_request(db, _who(db, "mem"))
    with pytest.raises(HTTPException):
        _require_photo_request(db, _who(db, "adm"))  # admins' switch is still off

    settings_service.update_settings(db, {"members_can_change_photo": False, "admins_can_change_photo": True},
                                     db.users["sa"].id)
    settings_service._cache.clear()
    _require_photo_request(db, _who(db, "adm"))
    assert photo_change_is_direct(db, "executive", True) is True  # executives follow the admins' switch
    with pytest.raises(HTTPException):
        _require_photo_request(db, _who(db, "mem"))
