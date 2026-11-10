"""Remember-me logins: long-lived tokens that end on deactivation, password change or role change."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import User, UserRole
from app.routes import auth_routes
from app.schemas.schemas import UserLogin
from app.services.auth_service import AuthService
from app.utils.auth import ALGORITHM, SECRET_KEY, get_current_user, hash_password


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    for name in ("_assert_not_rate_limited", "_register_failed_attempt", "_reset_failed_attempts"):
        monkeypatch.setattr(AuthService, name, staticmethod(lambda *a, **k: None))


@pytest.fixture()
def admin(db):
    user = User(username="admin1", password_hash=hash_password("Secret@123"), role=UserRole.ADMIN, is_active=True)
    db.add(user)
    db.commit()
    return user


def _login(db, remember):
    request = SimpleNamespace(client=None)
    creds = UserLogin(username="admin1", password="Secret@123", remember_me=remember)
    return auth_routes.login(creds, request, db)


def _lifetime_seconds(token):
    claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return claims["exp"] - claims["iat"], claims


def _me(db, token):
    return asyncio.run(get_current_user(SimpleNamespace(credentials=token), db))


def test_default_login_uses_session_timeout(db, admin):
    resp = _login(db, remember=False)
    lifetime, claims = _lifetime_seconds(resp["access_token"])
    assert resp["remember_me"] is False
    assert lifetime <= 720 * 60
    assert "rm" not in claims


def test_remember_me_login_lasts_remember_me_days(db, admin):
    resp = _login(db, remember=True)
    lifetime, claims = _lifetime_seconds(resp["access_token"])
    assert resp["remember_me"] is True
    assert lifetime == 30 * 24 * 3600 == resp["expires_in"]
    assert claims["rm"] is True and claims["pwv"]
    assert "Secret@123" not in resp["access_token"]
    assert _me(db, resp["access_token"]) == {"user_id": admin.id, "role": "admin"}


def test_remember_me_token_ends_when_password_changes(db, admin):
    token = _login(db, remember=True)["access_token"]
    admin.password_hash = hash_password("NewSecret@456")
    db.commit()
    with pytest.raises(HTTPException) as exc:
        _me(db, token)
    assert exc.value.status_code == 401


def test_remember_me_token_ends_when_account_deactivated(db, admin):
    token = _login(db, remember=True)["access_token"]
    admin.is_active = False
    db.commit()
    with pytest.raises(HTTPException) as exc:
        _me(db, token)
    assert exc.value.status_code == 401


def test_remember_me_token_follows_current_role(db, admin):
    token = _login(db, remember=True)["access_token"]
    admin.role = UserRole.MEMBER
    db.commit()
    assert _me(db, token)["role"] == "member"
