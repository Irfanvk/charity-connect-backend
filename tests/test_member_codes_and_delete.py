"""Member ID numbering ignores test codes; deleting a member removes everything and the login."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import (Challan, ChallanStatus, ChallanType, Member, MemberRequest, PaymentReminderLog,
                               ReliefApproval, ReliefClaim, RequestStatus, RequestType, User, UserRole)
from app.services.member_service import MemberService
from app.utils.member_codes import next_member_code


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _member(db, username, code, role=UserRole.MEMBER):
    u = User(username=username, password_hash="x", role=role, is_active=True)
    db.add(u)
    db.flush()
    m = Member(user_id=u.id, member_code=code, full_name=username.title(), monthly_amount=500)
    db.add(m)
    db.commit()
    return m


def test_next_code_ignores_test_codes(db):
    assert next_member_code(db) == "MEM-0001"
    _member(db, "a", "MEM-0207")
    _member(db, "b", "MEM-0012")        # an older number added later
    _member(db, "t", "TEST-0001")       # the temporary test member, added last
    assert next_member_code(db) == "MEM-0208"
    assert MemberService._next_member_code(db) == "MEM-0208"


def test_delete_removes_related_records_and_login(db):
    admin = User(username="adm", password_hash="x", role=UserRole.ADMIN, is_active=True)
    db.add(admin)
    db.flush()
    m = _member(db, "tester", "TEST-0001")
    db.add_all([
        Challan(member_id=m.id, type=ChallanType.MONTHLY, month="2026-11", amount=500, status=ChallanStatus.PENDING),
        MemberRequest(member_id=m.id, user_id=m.user_id, request_type=RequestType.GENERAL,
                      status=RequestStatus.PENDING, message="hi"),
        PaymentReminderLog(member_id=m.id, user_id=m.user_id, month="2026-11", kind="due"),
    ])
    db.flush()
    claim = ReliefClaim(member_id=m.id, reason="illness", amount=40000, created_by_user_id=admin.id,
                        receiver_name="X", documents="[]")
    db.add(claim)
    db.flush()
    db.add(ReliefApproval(claim_id=claim.id, admin_user_id=admin.id, decision="approve"))
    db.commit()
    user_id = m.user_id
    MemberService.delete_member(db, m.id)
    assert db.query(Member).count() == 0
    for model in (Challan, MemberRequest, PaymentReminderLog, ReliefClaim, ReliefApproval):
        assert db.query(model).count() == 0
    assert db.get(User, user_id).is_active is False      # cannot sign in any more
    assert db.get(User, admin.id).is_active is True


def test_deleting_an_admins_member_record_keeps_admin_login(db):
    m = _member(db, "boss", "MEM-0003", role=UserRole.ADMIN)
    MemberService.delete_member(db, m.id)
    assert db.query(User).filter(User.username == "boss").one().is_active is True
