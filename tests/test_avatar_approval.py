"""Photo changes go through approval for anyone with a member record, admins included."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import Member, User, UserRole
from app.routes import auth_routes


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _user(db, name, role, member=True):
    u = User(username=name, password_hash="x", role=role, is_active=True, avatar_url="/uploads/avatars/old.png")
    db.add(u)
    db.flush()
    if member:
        db.add(Member(user_id=u.id, member_code=f"MEM-{u.id:04d}", full_name=name))
    db.commit()
    return {"user_id": u.id, "role": role.value.lower()}


@pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.ADMIN, UserRole.SUPERADMIN])
def test_anyone_with_member_record_must_request(db, role):
    ctx = _user(db, f"u-{role.value}", role)
    with pytest.raises(HTTPException) as exc:
        auth_routes.remove_avatar(current_user=ctx, db=db)
    assert exc.value.status_code == 403


def test_account_without_member_record_changes_directly(db, monkeypatch):
    monkeypatch.setattr(auth_routes, "delete_file", lambda url: None)
    ctx = _user(db, "boss", UserRole.SUPERADMIN, member=False)
    out = auth_routes.remove_avatar(current_user=ctx, db=db)
    assert out.avatar_url is None
