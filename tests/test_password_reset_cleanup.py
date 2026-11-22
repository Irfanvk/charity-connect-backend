"""Password reset requests: one waiting request per person, unknown names hidden from admins,
old pending / rejected ones can be deleted after 7 days (audited); approved / used are kept."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import AuditLog, Notification, PasswordResetRequest, User, UserRole
from app.services import password_reset_service as prs
from app.services.notification_service import NotificationService


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)
    session.add_all([
        User(username="boss", password_hash="x", role=UserRole.SUPERADMIN, is_active=True),
        User(username="adm", password_hash="x", role=UserRole.ADMIN, is_active=True),
        User(username="aisha", password_hash="x", role=UserRole.MEMBER, phone="+971501234567", is_active=True),
    ])
    session.commit()
    yield session
    session.close()


def _id(db, name):
    return db.query(User).filter(User.username == name).one().id


def test_asking_again_keeps_one_request_and_no_new_notice(db):
    first = prs.create_request(db, "+971501234567")
    notices = db.query(Notification).count()
    again = prs.create_request(db, "aisha")
    assert again.id == first.id and again.identifier == "aisha"
    assert db.query(PasswordResetRequest).count() == 1
    assert db.query(Notification).count() == notices  # admins are not told twice


def test_unknown_names_are_hidden_and_not_announced(db):
    prs.create_request(db, "nobody-like-this")
    assert db.query(PasswordResetRequest).count() == 1      # kept (the reply is the same either way)
    assert db.query(Notification).count() == 0
    assert prs.list_requests(db) == []


def test_delete_after_seven_days_only(db):
    req = prs.create_request(db, "aisha")
    adm = _id(db, "adm")
    assert not prs.can_delete(req)
    with pytest.raises(HTTPException, match="7 days"):
        prs.delete_request(db, req.id, adm)
    req.created_at = datetime.utcnow() - timedelta(days=8)
    db.commit()
    assert prs.can_delete(req)
    prs.delete_request(db, req.id, adm)
    assert db.query(PasswordResetRequest).count() == 0
    log = db.query(AuditLog).filter(AuditLog.action == "password_reset_request_deleted").one()
    assert log.user_id == adm


def test_approved_and_used_are_kept(db):
    for state in ("approved", "used"):
        req = PasswordResetRequest(identifier="aisha", user_id=_id(db, "aisha"), status=state,
                                   created_at=datetime.utcnow() - timedelta(days=30))
        db.add(req)
        db.commit()
        assert prs.deletable_from(req) is None
        with pytest.raises(HTTPException, match="kept as a record"):
            prs.delete_request(db, req.id, _id(db, "adm"))


def test_admin_account_requests_need_the_superadmin(db):
    req = PasswordResetRequest(identifier="adm", user_id=_id(db, "adm"), status="pending",
                               created_at=datetime.utcnow() - timedelta(days=9))
    db.add(req)
    db.commit()
    other_admin = User(username="adm2", password_hash="x", role=UserRole.ADMIN, is_active=True)
    db.add(other_admin)
    db.commit()
    with pytest.raises(HTTPException, match="superadmin"):
        prs.delete_request(db, req.id, other_admin.id)
    prs.delete_request(db, req.id, _id(db, "boss"))
