import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import (
    BulkChallanGroup,
    Campaign,
    Challan,
    ChallanStatus,
    ChallanType,
    Member,
    Notification,
    User,
    UserRole,
)
import importlib

from app.routes import challan_routes
admin_router = importlib.import_module("app.routes.admin_router")
from app.schemas.schemas import (
    BulkChallanApprove,
    BulkChallanReject,
    ChallanApprove,
    ChallanReject,
    ChallanRevert,
)
from app.services.notification_service import NotificationService


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def stub_dispatch(monkeypatch):
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)


@pytest.fixture()
def world(db):
    admin = User(username="admin", password_hash="x", role=UserRole.ADMIN, full_name="Admin")
    user = User(username="mem", password_hash="x", role=UserRole.MEMBER, full_name="Mem Ber")
    db.add_all([admin, user])
    db.flush()
    member = Member(user_id=user.id, member_code="M1", full_name="Mem Ber")
    db.add(member)
    db.flush()
    return admin, user, member


def _challan(db, member, month="2026-10", amount=500, status=ChallanStatus.PENDING):
    c = Challan(member_id=member.id, type=ChallanType.MONTHLY, month=month, amount=amount, status=status)
    db.add(c)
    db.commit()
    return c


def _member_notifications(db, user):
    return db.query(Notification).filter(Notification.user_id == user.id).order_by(Notification.id).all()


def _admin_ctx(admin):
    return {"user_id": admin.id, "role": "admin", "username": admin.username}


def test_single_approve(db, world):
    admin, user, member = world
    c = _challan(db, member)
    challan_routes.approve_challan(c.id, ChallanApprove(), _admin_ctx(admin), db)
    notes = _member_notifications(db, user)
    assert len(notes) == 1
    assert notes[0].title == "Payment approved"
    assert notes[0].message == "Your monthly payment for Oct 2026 (₹500) has been approved."
    assert notes[0].type == "success"


def test_single_reject_and_revert(db, world):
    admin, user, member = world
    c = _challan(db, member)
    challan_routes.reject_challan(ChallanReject(rejection_reason="Blurry proof"), c.id, _admin_ctx(admin), db)
    notes = _member_notifications(db, user)
    assert len(notes) == 1
    assert "Blurry proof" in notes[0].message and "Challans page" in notes[0].message
    assert notes[0].type == "warning"

    challan_routes.revert_challan(c.id, ChallanRevert(reason="Checked again"), _admin_ctx(admin), db)
    notes = _member_notifications(db, user)
    assert len(notes) == 2
    assert notes[1].title == "Payment status changed"
    assert "Checked again" in notes[1].message


def test_campaign_message(db, world):
    admin, user, member = world
    camp = Campaign(title="Flood Relief", start_date=datetime.utcnow(), created_by_admin_id=admin.id)
    db.add(camp)
    db.flush()
    c = Challan(member_id=member.id, type=ChallanType.CAMPAIGN, campaign_id=camp.id, amount=1000, status=ChallanStatus.PENDING)
    db.add(c)
    db.commit()
    NotificationService.notify_challan_status_change(db, c, "approved")
    msg = _member_notifications(db, user)[0].message
    assert msg == "Your donation of ₹1,000 to Flood Relief has been approved."


def test_indian_format():
    assert NotificationService._format_inr(1500000) == "₹15,00,000"
    assert NotificationService._format_inr(1500) == "₹1,500"


def _bulk(db, member, admin):
    months = ["2026-08", "2026-09", "2026-10"]
    ids = []
    group = BulkChallanGroup(
        bulk_group_id="BCH-0001", member_id=member.id, amount_per_month=500, total_amount=1500,
        proof_file_id="p", months_list=json.dumps(months), challan_ids_list="[]",
        created_by_user_id=admin.id,
    )
    db.add(group)
    db.flush()
    for m in months:
        c = Challan(member_id=member.id, type=ChallanType.MONTHLY, month=m, amount=500,
                    status=ChallanStatus.PENDING, bulk_group_id="BCH-0001")
        db.add(c)
        db.flush()
        ids.append(c.id)
    group.challan_ids_list = json.dumps(ids)
    db.commit()
    return group


def test_bulk_approve_single_notification(db, world):
    admin, user, member = world
    _bulk(db, member, admin)
    admin_router.approve_bulk_challans("BCH-0001", BulkChallanApprove(approved=True), db, _admin_ctx(admin))
    notes = _member_notifications(db, user)
    assert len(notes) == 1
    assert notes[0].message == "Your payment for 3 months (Aug–Oct 2026, ₹1,500) has been approved."


def test_bulk_reject_single_notification(db, world):
    admin, user, member = world
    _bulk(db, member, admin)
    admin_router.reject_bulk_challans(
        "BCH-0001", BulkChallanReject(reason="Wrong amount", action="reject"), db, _admin_ctx(admin)
    )
    notes = _member_notifications(db, user)
    assert len(notes) == 1
    assert "Wrong amount" in notes[0].message


def test_failing_dispatch_does_not_affect_status(db, world, monkeypatch):
    admin, user, member = world

    def boom(*_a, **_k):
        raise RuntimeError("push down")

    monkeypatch.setattr(NotificationService, "dispatch_notification", boom)
    c = _challan(db, member)
    result = challan_routes.approve_challan(c.id, ChallanApprove(), _admin_ctx(admin), db)
    db.expire_all()
    assert db.get(Challan, c.id).status == ChallanStatus.APPROVED
    assert result is not None


def test_admins_notified_once_per_upload(db, world):
    admin, user, member = world
    sa = User(username="sa", password_hash="x", role=UserRole.SUPERADMIN)
    db.add(sa)
    db.commit()
    NotificationService.notify_admins_proof_uploaded(db, member, ["2026-09", "2026-10"])
    assert db.query(Notification).filter(Notification.user_id == admin.id).count() == 1
    assert db.query(Notification).filter(Notification.user_id == sa.id).count() == 1
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 0
