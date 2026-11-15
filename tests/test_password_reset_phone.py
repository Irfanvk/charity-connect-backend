"""Forgot password: the phone number is found however it was typed or saved."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import User, UserRole
from app.services import password_reset_service as prs


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    for name, phone, wa in [
        ("aisha", "+971501234567", None),
        ("rahul", "+91 98765 43210", None),
        ("omar", "0560570553", "+966 55 999 8888"),   # saved without country code; WhatsApp differs
        ("twin1", "+97455512345", None),
        ("twin2", "+97466600000", "+974 5551 2345"),   # WhatsApp = twin1 phone -> ambiguous
    ]:
        session.add(User(username=name, password_hash="x", role=UserRole.MEMBER, phone=phone, whatsapp_phone=wa))
    session.commit()
    yield session
    session.close()


@pytest.mark.parametrize("typed,expected", [
    ("+971501234567", "aisha"),
    ("+971 050 123 4567", "aisha"),        # leading 0 after the code
    ("+971-50-123-4567", "aisha"),
    ("+919876543210", "rahul"),            # saved with spaces
    ("+966560570553", "omar"),             # saved without the country code
    ("+966559998888", "omar"),             # WhatsApp number
    ("AISHA", "aisha"),                    # username still works
])
def test_found(db, typed, expected):
    assert prs._find_user_by_identifier(db, typed).username == expected


@pytest.mark.parametrize("typed", ["+974 5551 2345", "+971501234568", "12345", "+1 555"])
def test_not_found_or_ambiguous(db, typed):
    assert prs._find_user_by_identifier(db, typed) is None


def test_request_saved_even_when_not_found(db, monkeypatch):
    monkeypatch.setattr(prs, "_notify_admins_new_request", lambda *a, **k: None)
    req = prs.create_request(db, "+971 050 123 4567")
    assert req.user_id is not None and req.identifier == "+971 050 123 4567"
    assert prs.create_request(db, "+999 1234567").user_id is None
