"""'Not paid yet' vs submitted challans, and unpaid months following the monthly fee."""
import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import (
    Challan, ChallanStatus, ChallanType, Member, MemberRequest, RequestStatus, RequestType, User, UserRole,
)
from app.services.challan_service import ChallanService
from app.services.challan_state import is_submitted, sync_unpaid_monthly_amounts
from app.services.member_service import MemberService
from app.services.notification_service import NotificationService
from app.services.request_service import RequestService
from app.schemas.schemas import ChallanResponse, MemberUpdate


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)


@pytest.fixture()
def member(db):
    u = User(username="m1", password_hash="x", role=UserRole.MEMBER, is_active=True, full_name="Member One")
    db.add(u)
    db.flush()
    m = Member(user_id=u.id, member_code="MEM-0016", full_name="Member One", monthly_amount=100)
    db.add(m)
    db.commit()
    return m


def _ch(db, member, month, status, amount=100, **kw):
    c = Challan(member_id=member.id, type=ChallanType.MONTHLY, month=month, amount=amount, status=status, **kw)
    db.add(c)
    db.commit()
    return c


def test_what_counts_as_submitted(db, member):
    imported = _ch(db, member, "2026-01", ChallanStatus.PENDING, entry_source="self")
    generated = _ch(db, member, "2026-02", ChallanStatus.GENERATED)
    with_proof = _ch(db, member, "2026-03", ChallanStatus.PENDING, proof_path="/p.jpg", proof_uploaded_at=datetime.utcnow())
    bulk = _ch(db, member, "2026-04", ChallanStatus.PENDING, bulk_group_id=None)
    admin = _ch(db, member, "2026-05", ChallanStatus.PENDING, entry_source="admin")
    approved = _ch(db, member, "2025-12", ChallanStatus.APPROVED)
    assert [is_submitted(c) for c in (imported, generated, with_proof, admin, approved)] == [False, False, True, True, True]
    assert is_submitted(bulk) is False
    # The API tells the app which is which.
    assert ChallanResponse.model_validate(imported).submitted is False
    assert ChallanResponse.model_validate(with_proof).submitted is True


def test_fee_change_updates_only_unpaid_months(db, member):
    paid = _ch(db, member, "2025-11", ChallanStatus.APPROVED)
    submitted = _ch(db, member, "2025-12", ChallanStatus.PENDING, proof_path="/p.jpg")
    imported = _ch(db, member, "2026-01", ChallanStatus.PENDING)
    generated = _ch(db, member, "2026-02", ChallanStatus.GENERATED)
    campaign = Challan(member_id=member.id, type=ChallanType.CAMPAIGN, amount=100, status=ChallanStatus.PENDING)
    db.add(campaign)
    db.commit()

    member.monthly_amount = 500
    assert sync_unpaid_monthly_amounts(db, member) == 2
    db.commit()
    amounts = {c.month: float(db.get(Challan, c.id).amount) for c in (paid, submitted, imported, generated)}
    assert amounts == {"2025-11": 100, "2025-12": 100, "2026-01": 500, "2026-02": 500}
    assert float(db.get(Challan, campaign.id).amount) == 100


def test_admin_edit_of_monthly_amount_syncs_unpaid_months(db, member):
    imported = _ch(db, member, "2026-01", ChallanStatus.PENDING)
    MemberService.update_member(db, member.id, MemberUpdate(monthly_amount=500))
    assert float(db.get(Challan, imported.id).amount) == 500


def test_approved_amount_change_request_syncs_unpaid_months(db, member):
    admin = User(username="admin", password_hash="x", role=UserRole.ADMIN, is_active=True)
    db.add(admin)
    db.commit()
    imported = _ch(db, member, "2026-01", ChallanStatus.PENDING)
    approved = _ch(db, member, "2025-12", ChallanStatus.APPROVED)
    req = MemberRequest(user_id=member.user_id, member_id=member.id, request_type=RequestType.MONTHLY_AMOUNT_CHANGE,
                        subject="Change", message="Please", requested_amount=500, current_amount=100,
                        status=RequestStatus.PENDING)
    db.add(req)
    db.commit()
    RequestService.approve_request(db, {"user_id": admin.id, "role": "admin"}, req.id)
    assert float(db.get(Challan, imported.id).amount) == 500
    assert float(db.get(Challan, approved.id).amount) == 100


def test_review_list_can_hide_not_paid_yet(db, member):
    _ch(db, member, "2026-01", ChallanStatus.PENDING)  # imported, nothing to review
    _ch(db, member, "2026-02", ChallanStatus.PENDING, proof_path="/p.jpg", proof_uploaded_at=datetime.utcnow())
    everything = ChallanService.get_all_challans(db, status_filter="pending")
    to_review = ChallanService.get_all_challans(db, status_filter="pending", submitted=True)
    not_paid = ChallanService.get_all_challans(db, status_filter="pending", submitted=False)
    total = lambda page: page["total"] if isinstance(page, dict) else page.total
    assert (total(everything), total(to_review), total(not_paid)) == (2, 1, 1)
