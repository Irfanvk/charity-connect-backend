import importlib
import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import (
    AuditLog,
    BulkChallanGroup,
    Challan,
    ChallanStatus,
    ChallanType,
    FundUtilization,
    Member,
    MemberRequest,
    Notification,
    PasswordResetRequest,
    RequestStatus,
    RequestType,
    User,
    UserRole,
)
from app.routes import challan_routes, fund_utilization_routes
from app.schemas.schemas import (
    BulkChallanApprove,
    BulkChallanReject,
    ChallanApprove,
    ChallanCreate,
    ChallanReject,
    ChallanRevert,
    ChallanUpdate,
    FundUtilizationCreate,
    FundUtilizationReasonAction,
    FundUtilizationUpdate,
)
from app.services import password_reset_service
from app.services.notification_service import NotificationService
from app.services.request_service import RequestService

admin_router = importlib.import_module("app.routes.admin_router")

REASON = "Proof does not match the amount"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def stub_dispatch(monkeypatch):
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)


def _user(db, name, role):
    u = User(username=name, password_hash="x", role=role, full_name=name.title())
    db.add(u)
    db.flush()
    return u


def _ctx(user):
    return {"user_id": user.id, "role": user.role.value, "username": user.username}


@pytest.fixture()
def world(db):
    admin1 = _user(db, "admin1", UserRole.ADMIN)
    admin2 = _user(db, "admin2", UserRole.ADMIN)
    superadmin = _user(db, "super", UserRole.SUPERADMIN)
    regular = _user(db, "regular", UserRole.MEMBER)
    members = {}
    for key, user in {"admin1": admin1, "super": superadmin, "regular": regular}.items():
        m = Member(user_id=user.id, member_code=f"M-{key}", full_name=user.full_name)
        db.add(m)
        db.flush()
        members[key] = m
    db.commit()
    return {"admin1": admin1, "admin2": admin2, "super": superadmin, "regular": regular, "members": members}


def _challan(db, member, status=ChallanStatus.PENDING, approved_by=None, month="2026-10"):
    c = Challan(
        member_id=member.id,
        type=ChallanType.MONTHLY,
        month=month,
        amount=500,
        status=status,
        approved_by_admin_id=approved_by.id if approved_by else None,
    )
    db.add(c)
    db.commit()
    return c


def _status_of(db, challan):
    db.refresh(challan)
    return challan.status


def _bulk(db, member, creator, status="pending_approval", approved_by=None):
    c1 = _challan(db, member, month="2026-08")
    c2 = _challan(db, member, month="2026-09")
    group = BulkChallanGroup(
        bulk_group_id="BG-1",
        member_id=member.id,
        amount_per_month=500,
        total_amount=1000,
        proof_file_id="f",
        status=status,
        months_list=json.dumps(["2026-08", "2026-09"]),
        challan_ids_list=json.dumps([c1.id, c2.id]),
        created_by_user_id=creator.id,
        approved_by_admin_id=approved_by.id if approved_by else None,
    )
    db.add(group)
    for c in (c1, c2):
        c.bulk_group_id = "BG-1"
        if status == "approved":
            c.status = ChallanStatus.APPROVED
            c.approved_by_admin_id = approved_by.id
    db.commit()
    return group, [c1, c2]


def _forbidden(callable_, *args, **kwargs):
    with pytest.raises(HTTPException) as exc:
        callable_(*args, **kwargs)
    assert exc.value.status_code == 403
    return exc.value.detail


# ── Single challans ──────────────────────────────────────────────────────────

def test_admin_cannot_approve_reject_revert_own_challan(db, world):
    admin1 = world["admin1"]
    c = _challan(db, world["members"]["admin1"])

    detail = _forbidden(challan_routes.approve_challan, c.id, ChallanApprove(), _ctx(admin1), db)
    assert detail == "You cannot approve your own payment/request. Another admin must do this."
    _forbidden(challan_routes.reject_challan, ChallanReject(rejection_reason=REASON), c.id, _ctx(admin1), db)
    _forbidden(challan_routes.revert_challan, c.id, ChallanRevert(reason=REASON), _ctx(admin1), db)
    assert _status_of(db, c) == ChallanStatus.PENDING


def test_another_admin_can_approve_own_members_challan(db, world):
    c = _challan(db, world["members"]["admin1"])
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(world["admin2"]), db)
    assert _status_of(db, c) == ChallanStatus.APPROVED
    assert c.approved_by_admin_id == world["admin2"].id


def test_approve_ignores_spoofed_approver_id(db, world):
    c = _challan(db, world["members"]["regular"])
    challan_routes.approve_challan(
        c.id, ChallanApprove(approved_by_admin_id=world["admin2"].id), _ctx(world["admin1"]), db
    )
    db.refresh(c)
    assert c.approved_by_admin_id == world["admin1"].id


def test_superadmin_member_has_same_self_rules(db, world):
    sup = world["super"]
    c = _challan(db, world["members"]["super"])
    _forbidden(challan_routes.approve_challan, c.id, ChallanApprove(), _ctx(sup), db)
    # an admin (not the superadmin) approves, so the superadmin is not required
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(world["admin1"]), db)
    assert _status_of(db, c) == ChallanStatus.APPROVED
    _forbidden(challan_routes.revert_challan, c.id, ChallanRevert(reason=REASON), _ctx(sup), db)


def test_approver_cannot_reverse_own_approval(db, world):
    admin1, admin2 = world["admin1"], world["admin2"]
    c = _challan(db, world["members"]["regular"], status=ChallanStatus.APPROVED, approved_by=admin1)

    detail = _forbidden(challan_routes.revert_challan, c.id, ChallanRevert(reason=REASON), _ctx(admin1), db)
    assert detail == "Reversal must be done by a different admin than the one who approved it."
    _forbidden(challan_routes.reject_challan, ChallanReject(rejection_reason=REASON), c.id, _ctx(admin1), db)
    assert _status_of(db, c) == ChallanStatus.APPROVED

    challan_routes.revert_challan(c.id, ChallanRevert(reason=REASON), _ctx(admin2), db)
    db.refresh(c)
    assert c.status == ChallanStatus.PENDING
    assert c.reversed_by_admin_id == admin2.id
    assert c.reversal_reason == REASON
    assert c.reversed_at is not None


def test_different_admin_reject_of_approved_fills_reversal_columns(db, world):
    c = _challan(db, world["members"]["regular"], status=ChallanStatus.APPROVED, approved_by=world["admin1"])
    challan_routes.reject_challan(ChallanReject(rejection_reason=REASON), c.id, _ctx(world["admin2"]), db)
    db.refresh(c)
    assert c.status == ChallanStatus.REJECTED
    assert c.reversed_by_admin_id == world["admin2"].id
    assert c.reversal_reason == REASON


def test_reasons_are_required_and_min_10_chars():
    with pytest.raises(ValidationError):
        ChallanRevert()
    with pytest.raises(ValidationError):
        ChallanRevert(reason="too short")
    with pytest.raises(ValidationError):
        ChallanRevert(reason="          x")
    with pytest.raises(ValidationError):
        ChallanReject(rejection_reason="   short   ")
    assert ChallanReject(rejection_reason="  long enough reason  ").rejection_reason == "long enough reason"


def test_admin_cannot_edit_or_delete_own_challan(db, world):
    admin1 = world["admin1"]
    c = _challan(db, world["members"]["admin1"])
    _forbidden(challan_routes.update_challan, c.id, ChallanUpdate(amount=900), _ctx(admin1), db)
    _forbidden(challan_routes.delete_challan, c.id, _ctx(admin1), db)
    db.refresh(c)
    assert c.amount == 500

    challan_routes.update_challan(c.id, ChallanUpdate(amount=900), _ctx(world["admin2"]), db)
    db.refresh(c)
    assert c.amount == 900


def test_admin_created_own_challan_is_never_auto_approved(db, world):
    from app.utils.timezone import current_month_business

    admin1 = world["admin1"]
    member = world["members"]["admin1"]
    created = challan_routes.create_challan(
        ChallanCreate(member_id=member.id, type=ChallanType.MONTHLY, amount=500, month=current_month_business()),
        _ctx(admin1),
        db,
    )
    assert created.status != ChallanStatus.APPROVED
    assert created.approved_by_admin_id is None
    _forbidden(challan_routes.approve_challan, created.id, ChallanApprove(), _ctx(admin1), db)
    challan = db.query(Challan).filter(Challan.id == created.id).one()
    challan.status = ChallanStatus.PENDING  # as after proof upload
    db.commit()
    _forbidden(challan_routes.approve_challan, created.id, ChallanApprove(), _ctx(admin1), db)
    challan_routes.approve_challan(created.id, ChallanApprove(), _ctx(world["admin2"]), db)
    db.refresh(challan)
    assert challan.status == ChallanStatus.APPROVED


def test_audit_rows_written_for_status_changes(db, world):
    c = _challan(db, world["members"]["regular"])
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(world["admin1"]), db)
    challan_routes.revert_challan(c.id, ChallanRevert(reason=REASON), _ctx(world["admin2"]), db)
    rows = db.query(AuditLog).filter(AuditLog.entity_id == c.id, AuditLog.entity_type == "Challan").all()
    actions = {r.action for r in rows}
    assert {"challan_approve", "challan_revert"} <= actions
    revert = next(r for r in rows if r.action == "challan_revert")
    assert json.loads(revert.old_values)["status"] == "approved"
    assert json.loads(revert.new_values)["reason"] == REASON
    assert revert.user_id == world["admin2"].id


# ── Bulk challans ────────────────────────────────────────────────────────────

def test_bulk_self_rules(db, world):
    admin1, admin2 = world["admin1"], world["admin2"]
    group, challans = _bulk(db, world["members"]["admin1"], admin1)

    _forbidden(admin_router.approve_bulk_challans, "BG-1", BulkChallanApprove(approved=True), db, _ctx(admin1))
    _forbidden(
        admin_router.reject_bulk_challans, "BG-1", BulkChallanReject(reason=REASON, action="reject"), db, _ctx(admin1)
    )
    db.refresh(group)
    assert group.status == "pending_approval"

    admin_router.approve_bulk_challans("BG-1", BulkChallanApprove(approved=True), db, _ctx(admin2))
    db.refresh(group)
    assert group.status == "approved"
    assert group.approved_by_admin_id == admin2.id


def test_bulk_revert_self_and_different_admin(db, world):
    admin1, admin2 = world["admin1"], world["admin2"]
    group, challans = _bulk(db, world["members"]["regular"], admin1, status="approved", approved_by=admin1)

    detail = _forbidden(admin_router.revert_bulk_challans, "BG-1", ChallanRevert(reason=REASON), db, _ctx(admin1))
    assert "different admin" in detail
    _forbidden(
        admin_router.reject_bulk_challans, "BG-1", BulkChallanReject(reason=REASON, action="reject"), db, _ctx(admin1)
    )

    admin_router.revert_bulk_challans("BG-1", ChallanRevert(reason=REASON), db, _ctx(admin2))
    db.refresh(group)
    assert group.status == "pending_approval"
    assert group.reversed_by_admin_id == admin2.id
    assert group.reversal_reason == REASON
    for c in challans:
        db.refresh(c)
        assert c.status == ChallanStatus.PENDING
        assert c.reversed_by_admin_id == admin2.id


def test_bulk_reject_of_approved_by_other_admin_fills_reversal(db, world):
    admin1, admin2 = world["admin1"], world["admin2"]
    group, challans = _bulk(db, world["members"]["regular"], admin1, status="approved", approved_by=admin1)
    admin_router.reject_bulk_challans("BG-1", BulkChallanReject(reason=REASON, action="reject"), db, _ctx(admin2))
    db.refresh(group)
    assert group.status == "rejected"
    assert group.reversed_by_admin_id == admin2.id
    for c in challans:
        db.refresh(c)
        assert c.status == ChallanStatus.REJECTED
        assert c.reversal_reason == REASON


def test_bulk_reject_requires_min_reason(db, world):
    _bulk(db, world["members"]["regular"], world["admin1"])
    with pytest.raises(HTTPException) as exc:
        admin_router.reject_bulk_challans(
            "BG-1", BulkChallanReject(reason="short", action="reject"), db, _ctx(world["admin2"])
        )
    assert exc.value.status_code == 400


# ── Member requests & password resets ───────────────────────────────────────

def _member_request(db, user, member):
    req = MemberRequest(
        user_id=user.id,
        member_id=member.id,
        request_type=RequestType.COMPLAINT,
        subject="Subject",
        message="Message",
        status=RequestStatus.PENDING,
    )
    db.add(req)
    db.commit()
    return req


def test_admin_cannot_resolve_own_member_request(db, world):
    admin1, admin2 = world["admin1"], world["admin2"]
    req = _member_request(db, admin1, world["members"]["admin1"])

    _forbidden(RequestService.approve_request, db, _ctx(admin1), req.id)
    _forbidden(RequestService.reject_request, db, _ctx(admin1), req.id, "No good reason")
    db.refresh(req)
    assert req.status == RequestStatus.PENDING

    RequestService.approve_request(db, _ctx(admin2), req.id)
    db.refresh(req)
    assert req.status == RequestStatus.APPROVED


def test_superadmin_cannot_resolve_own_member_request(db, world):
    sup = world["super"]
    req = _member_request(db, sup, world["members"]["super"])
    _forbidden(RequestService.approve_request, db, _ctx(sup), req.id)


def test_admin_cannot_resolve_own_password_reset(db, world):
    admin1, admin2 = world["admin1"], world["admin2"]
    req = PasswordResetRequest(identifier="admin1", user_id=admin1.id, status="pending")
    db.add(req)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        password_reset_service.approve_request(db, req.id, admin1.id, approver_role="admin")
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        password_reset_service.reject_request(db, req.id, admin1.id, "not allowed here")
    assert exc.value.status_code == 403
    db.refresh(req)
    assert req.status == "pending"

    # another admin can NOT approve an admin's reset; only a superadmin can
    with pytest.raises(HTTPException) as exc:
        password_reset_service.approve_request(db, req.id, admin2.id, approver_role="admin")
    assert exc.value.status_code == 403
    db.refresh(req)
    assert req.status == "pending"

    password_reset_service.approve_request(db, req.id, world["super"].id)
    db.refresh(req)
    assert req.status == "approved"


# ── Fund utilization ─────────────────────────────────────────────────────────

def _fund_world(db, world):
    _challan(db, world["members"]["regular"], status=ChallanStatus.APPROVED, approved_by=world["admin2"])
    c = db.query(Challan).first()
    c.amount = 10000
    db.commit()


def _create_fund(db, admin, amount=1000):
    return fund_utilization_routes.create_fund_utilization(
        FundUtilizationCreate(title="Medical aid", amount=amount), _ctx(admin), db
    )


def test_fund_creator_cannot_approve_other_admin_can(db, world):
    _fund_world(db, world)
    created = _create_fund(db, world["admin1"])
    assert created.status == "pending"

    detail = _forbidden(fund_utilization_routes.approve_fund_utilization, created.id, _ctx(world["admin1"]), db)
    assert detail == "You cannot approve your own payment/request. Another admin must do this."
    _forbidden(
        fund_utilization_routes.reject_fund_utilization,
        created.id,
        FundUtilizationReasonAction(reason=REASON),
        _ctx(world["admin1"]),
        db,
    )

    approved = fund_utilization_routes.approve_fund_utilization(created.id, _ctx(world["admin2"]), db)
    assert approved.status == "approved"
    assert approved.approved_by_admin_id == world["admin2"].id


def test_fund_notifications(db, world):
    _fund_world(db, world)
    created = _create_fund(db, world["admin1"], amount=1500)
    for other in (world["admin2"], world["super"]):
        notes = db.query(Notification).filter(Notification.user_id == other.id).all()
        assert [n.message for n in notes] == ["Fund utilization of ₹1,500 for Medical aid needs your approval"]
    assert db.query(Notification).filter(Notification.user_id == world["admin1"].id).count() == 0

    fund_utilization_routes.approve_fund_utilization(created.id, _ctx(world["admin2"]), db)
    creator_notes = db.query(Notification).filter(Notification.user_id == world["admin1"].id).all()
    assert len(creator_notes) == 1 and creator_notes[0].type == "success"


def test_fund_revert_rules_and_reason(db, world):
    _fund_world(db, world)
    created = _create_fund(db, world["admin1"])
    fund_utilization_routes.approve_fund_utilization(created.id, _ctx(world["admin2"]), db)

    with pytest.raises(ValidationError):
        FundUtilizationReasonAction(reason="short")
    _forbidden(
        fund_utilization_routes.revert_fund_utilization,
        created.id,
        FundUtilizationReasonAction(reason=REASON),
        _ctx(world["admin2"]),
        db,
    )
    reverted = fund_utilization_routes.revert_fund_utilization(
        created.id, FundUtilizationReasonAction(reason=REASON), _ctx(world["admin1"]), db
    )
    assert reverted.status == "pending"
    assert reverted.reversed_by_admin_id == world["admin1"].id
    assert reverted.reversal_reason == REASON


def test_fund_summary_excludes_pending(db, world):
    _fund_world(db, world)
    pending = _create_fund(db, world["admin1"], amount=1000)
    approved = _create_fund(db, world["admin1"], amount=2000)
    fund_utilization_routes.approve_fund_utilization(approved.id, _ctx(world["admin2"]), db)

    summary = fund_utilization_routes.get_fund_utilization_summary(_ctx(world["admin1"]), db)
    assert summary.total_collected == 10000
    assert summary.total_utilized == 2000
    assert summary.available_balance == 8000
    assert summary.pending_utilized_total == 1000
    assert summary.pending_count == 1
    assert pending.status == "pending"


def test_fund_approved_cannot_be_edited_or_deleted_pending_creator_only(db, world):
    _fund_world(db, world)
    created = _create_fund(db, world["admin1"])

    # pending: only the creator may edit/delete
    _forbidden(
        fund_utilization_routes.update_fund_utilization,
        created.id,
        FundUtilizationUpdate(title="Changed"),
        _ctx(world["admin2"]),
        db,
    )
    _forbidden(fund_utilization_routes.delete_fund_utilization, created.id, _ctx(world["admin2"]), db)
    updated = fund_utilization_routes.update_fund_utilization(
        created.id, FundUtilizationUpdate(title="Changed"), _ctx(world["admin1"]), db
    )
    assert updated.title == "Changed"

    fund_utilization_routes.approve_fund_utilization(created.id, _ctx(world["admin2"]), db)
    for call in (
        lambda: fund_utilization_routes.update_fund_utilization(
            created.id, FundUtilizationUpdate(title="x"), _ctx(world["admin1"]), db
        ),
        lambda: fund_utilization_routes.delete_fund_utilization(created.id, _ctx(world["admin1"]), db),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 400

    pending2 = _create_fund(db, world["admin1"], amount=100)
    fund_utilization_routes.delete_fund_utilization(pending2.id, _ctx(world["admin1"]), db)
    assert db.query(FundUtilization).filter(FundUtilization.id == pending2.id).first() is None


def test_superadmin_creator_cannot_approve_own_fund_entry(db, world):
    _fund_world(db, world)
    created = _create_fund(db, world["super"])
    _forbidden(fund_utilization_routes.approve_fund_utilization, created.id, _ctx(world["super"]), db)
    fund_utilization_routes.approve_fund_utilization(created.id, _ctx(world["admin1"]), db)
