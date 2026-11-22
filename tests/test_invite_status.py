"""Opening a used invite link again: the sign-up page asks the server first."""
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import Invite, User, UserRole
from app.services.invite_service import InviteService


def test_invite_status():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    admin = User(username="a", password_hash="x", role=UserRole.ADMIN)
    db.add(admin)
    db.flush()
    later, before = datetime.utcnow() + timedelta(days=3), datetime.utcnow() - timedelta(days=1)
    db.add_all([
        Invite(invite_code="INV-AAAAAA", phone="+971500000001", expiry_date=later, created_by_admin_id=admin.id),
        Invite(invite_code="INV-BBBBBB", phone="+971500000002", expiry_date=later, is_used=True, created_by_admin_id=admin.id),
        Invite(invite_code="INV-CCCCCC", phone="+971500000003", expiry_date=before, created_by_admin_id=admin.id),
    ])
    db.commit()
    assert InviteService.invite_status(db, "inv-aaaaaa") == "valid"
    assert InviteService.invite_status(db, "INV-BBBBBB") == "used"
    assert InviteService.invite_status(db, "INV-CCCCCC") == "expired"
    assert InviteService.invite_status(db, "INV-ZZZZZZ") == "not_found"
    assert InviteService.invite_status(db, "") == "not_found"


def test_invite_mode_new_or_existing():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    from app.models.models import Member

    admin = User(username="a", password_hash="x", role=UserRole.ADMIN)
    old = User(username="old", password_hash="x", role=UserRole.MEMBER, phone="+971500000009", is_active=False)
    db.add_all([admin, old])
    db.flush()
    db.add(Member(user_id=old.id, member_code="MEM-0009", monthly_amount=500))
    later = datetime.utcnow() + timedelta(days=3)
    db.add_all([
        Invite(invite_code="INV-NEW111", phone="+971500000008", expiry_date=later, created_by_admin_id=admin.id),
        Invite(invite_code="INV-OLD111", phone="+971500000009", expiry_date=later, created_by_admin_id=admin.id),
    ])
    db.commit()
    assert InviteService.invite_mode(db, "INV-NEW111") == "new_member"
    assert InviteService.invite_mode(db, "INV-OLD111") == "existing_member"
    assert InviteService.invite_mode(db, "INV-NONE00") is None
