"""Bulk (multi-month) payments: amount, proof, maker-checker, duplicates, history."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from tests.test_separation_of_duties import REASON, _ctx, admin_router, db, stub_dispatch, world  # noqa: F401
from app.models.models import BulkChallanGroup, Challan, ChallanStatus, ChallanType
from app.routes import bulk_challan_routes, challan_routes
from app.schemas.schemas import (
    BulkChallanApprove,
    BulkChallanCreate,
    BulkChallanReject,
    ChallanCreate,
    ChallanRevert,
    MultiChallanCreate,
)
from app.services.bulk_rules import GENERIC_ERROR
from app.services.challan_service import ChallanService

MONTHS = ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]


@pytest.fixture(autouse=True)
def setup(monkeypatch, world, db):
    for m in world["members"].values():
        m.status = "active"
        m.monthly_amount = 500
    db.commit()
    monkeypatch.setattr(ChallanService, "get_payable_months", staticmethod(lambda *a, **k: {"all_months": MONTHS}))
    monkeypatch.setattr(bulk_challan_routes.NotificationService, "notify_admins_proof_uploaded", lambda *a, **k: None)
    monkeypatch.setattr(admin_router.NotificationService, "notify_bulk_status_change", lambda *a, **k: None)
    monkeypatch.setattr(admin_router.NotificationService, "send_payment_receipt_whatsapp", lambda *a, **k: None)


def _create(db, user, months, amount=500, proof="proof.png", member_id=None, notes=None):
    req = BulkChallanCreate(months=months, amount_per_month=amount, proof_file_id=proof, member_id=member_id, notes=notes)
    return bulk_challan_routes.bulk_create_challans(request=req, db=db, current_user=_ctx(user))


def _approve(db, group_id, admin):
    return admin_router.approve_bulk_challans(group_id, BulkChallanApprove(approved=True), db=db, current_user=_ctx(admin))


def _reject(db, group_id, admin, action="reject"):
    return admin_router.reject_bulk_challans(group_id, BulkChallanReject(reason=REASON, action=action), db=db, current_user=_ctx(admin))


def _list(db, admin, **kw):
    params = dict(days=None, skip=0, limit=100, sort_by="created_at", order="desc", status="pending_approval")
    params.update(kw)
    return admin_router.get_pending_bulk_operations(db=db, current_user=_ctx(admin), **params)


def _raises(code, fn, *a, **k):
    with pytest.raises(HTTPException) as exc:
        fn(*a, **k)
    assert exc.value.status_code == code, exc.value.detail
    return exc.value


# ── Amount ────────────────────────────────────────────────────────────────

def test_member_always_pays_their_own_fee(db, world):
    r = _create(db, world["regular"], ["2026-08", "2026-09"], amount=1)
    assert r.total_amount == 1000
    amounts = {c.amount for c in db.query(Challan).filter_by(bulk_group_id=r.bulk_group_id)}
    assert amounts == {500}


def test_member_fee_used_for_single_and_separate_proof_months(db, world):
    member = world["members"]["regular"]
    single = challan_routes.create_challan(
        ChallanCreate(type=ChallanType.MONTHLY, month="2026-08", amount=1), _ctx(world["regular"]), db,
    )
    assert single.amount == 500
    multi = challan_routes.create_multi_challans(
        MultiChallanCreate(months=["2026-09", "2026-10"], amount=1, proof_type="individual"), _ctx(world["regular"]), db,
    )
    assert multi["total_amount"] == 1000
    assert {c.amount for c in db.query(Challan).filter(Challan.id.in_(multi["challan_ids"]))} == {500}
    assert db.query(Challan).filter_by(member_id=member.id).count() == 3


def test_member_without_a_fee_is_told_to_ask_admins(db, world):
    world["members"]["regular"].monthly_amount = 0
    db.commit()
    err = _raises(400, _create, db, world["regular"], ["2026-08"])
    assert "not set" in err.detail


def test_admin_can_record_a_different_amount(db, world):
    r = _create(db, world["admin1"], ["2026-08"], amount=300, member_id=world["members"]["regular"].id)
    assert r.total_amount == 300


# ── Proof ─────────────────────────────────────────────────────────────────

def test_member_must_attach_proof(db, world):
    _raises(400, _create, db, world["regular"], ["2026-08"], proof=None)
    assert db.query(BulkChallanGroup).count() == 0


def test_admin_without_proof_needs_a_reason_and_shows_no_link(db, world):
    member_id = world["members"]["regular"].id
    _raises(400, _create, db, world["admin1"], ["2026-08"], proof=None, member_id=member_id)
    r = _create(db, world["admin1"], ["2026-08"], proof=None, member_id=member_id, notes="Cash collected at the masjid")
    item = _list(db, world["admin2"]).bulk_operations[0]
    assert item.bulk_group_id == r.bulk_group_id
    assert item.proof_url is None and item.has_proof is False
    assert item.notes == "Cash collected at the masjid"


# ── Maker-checker ─────────────────────────────────────────────────────────

def test_admin_entered_bulk_needs_a_second_admin(db, world):
    r = _create(db, world["admin1"], ["2026-08", "2026-09"], member_id=world["members"]["regular"].id)
    assert {c.entry_source for c in db.query(Challan).filter_by(bulk_group_id=r.bulk_group_id)} == {"admin"}
    item = _list(db, world["admin2"]).bulk_operations[0]
    assert item.entered_by_admin is True and item.created_by_name == "Admin1"
    _raises(403, _approve, db, r.bulk_group_id, world["admin1"])
    _approve(db, r.bulk_group_id, world["admin2"])


def test_old_admin_entered_groups_also_need_a_second_admin(db, world):
    """Groups saved before this fix have entry_source 'self' even when an admin entered them."""
    r = _create(db, world["admin1"], ["2026-08"], member_id=world["members"]["regular"].id)
    for c in db.query(Challan).filter_by(bulk_group_id=r.bulk_group_id):
        c.entry_source = "self"
    db.commit()
    _raises(403, _approve, db, r.bulk_group_id, world["admin1"])


def test_member_submitted_bulk_any_other_admin_approves(db, world):
    r = _create(db, world["regular"], ["2026-08"])
    _approve(db, r.bulk_group_id, world["admin1"])
    assert db.query(Challan).filter_by(bulk_group_id=r.bulk_group_id).one().status == ChallanStatus.APPROVED


# ── Same month twice ──────────────────────────────────────────────────────

def test_revert_refused_when_months_were_submitted_again(db, world):
    r = _create(db, world["regular"], ["2026-08", "2026-09"])
    _reject(db, r.bulk_group_id, world["admin1"])
    _create(db, world["regular"], ["2026-08", "2026-09"])
    err = _raises(409, admin_router.revert_bulk_challans, r.bulk_group_id, ChallanRevert(reason=REASON),
                  db=db, current_user=_ctx(world["admin2"]))
    assert err.detail["duplicate_months"] == ["2026-08", "2026-09"]


def test_revert_allowed_when_months_are_still_free(db, world):
    r = _create(db, world["regular"], ["2026-08"])
    _reject(db, r.bulk_group_id, world["admin1"])
    admin_router.revert_bulk_challans(r.bulk_group_id, ChallanRevert(reason=REASON), db=db, current_user=_ctx(world["admin2"]))
    assert db.query(BulkChallanGroup).one().status == "pending_approval"


def test_approve_refused_if_month_already_paid_elsewhere(db, world):
    r = _create(db, world["regular"], ["2026-08"])
    db.add(Challan(member_id=world["members"]["regular"].id, type=ChallanType.MONTHLY, month="2026-08",
                   amount=500, status=ChallanStatus.APPROVED))
    db.commit()
    _raises(409, _approve, db, r.bulk_group_id, world["admin1"])


def test_single_payment_refused_for_an_approved_month(db, world):
    r = _create(db, world["regular"], ["2026-08"])
    _approve(db, r.bulk_group_id, world["admin1"])
    _raises(400, challan_routes.create_challan,
            ChallanCreate(type=ChallanType.MONTHLY, month="2026-08", amount=500), _ctx(world["regular"]), db)
    _raises(400, challan_routes.create_multi_challans,
            MultiChallanCreate(months=["2026-08", "2026-09"], amount=500), _ctx(world["regular"]), db)


# ── Reject keeps records ──────────────────────────────────────────────────

def test_reject_with_delete_keeps_the_records(db, world):
    r = _create(db, world["regular"], ["2026-08", "2026-09"])
    _reject(db, r.bulk_group_id, world["admin1"], action="delete")
    rows = db.query(Challan).filter_by(bulk_group_id=r.bulk_group_id).all()
    assert len(rows) == 2
    assert {c.status for c in rows} == {ChallanStatus.REJECTED}
    assert {c.rejection_reason for c in rows} == {REASON}
    _raises(400, _reject, db, r.bulk_group_id, world["admin2"])  # already rejected


def test_group_whose_months_were_deleted_cannot_come_back(db, world):
    r = _create(db, world["regular"], ["2026-08"])
    _reject(db, r.bulk_group_id, world["admin1"])
    for c in db.query(Challan).filter_by(bulk_group_id=r.bulk_group_id):
        db.delete(c)  # as the old app did
    db.commit()
    _raises(400, admin_router.revert_bulk_challans, r.bulk_group_id, ChallanRevert(reason=REASON),
            db=db, current_user=_ctx(world["admin2"]))
    assert _list(db, world["admin1"], status="rejected").bulk_operations[0].challans_missing is True


# ── Review list ───────────────────────────────────────────────────────────

def test_old_pending_payments_are_never_hidden(db, world):
    r = _create(db, world["regular"], ["2026-08"])
    db.query(BulkChallanGroup).filter_by(bulk_group_id=r.bulk_group_id).one().created_at = datetime.utcnow() - timedelta(days=800)
    db.commit()
    res = _list(db, world["admin1"])
    assert res.pending == 1 and [i.bulk_group_id for i in res.bulk_operations] == [r.bulk_group_id]


def test_history_tabs_come_from_the_server(db, world):
    a = _create(db, world["regular"], ["2026-08"])
    b = _create(db, world["regular"], ["2026-09"])
    _create(db, world["regular"], ["2026-10"])
    _approve(db, a.bulk_group_id, world["admin1"])
    _reject(db, b.bulk_group_id, world["admin1"])

    approved = _list(db, world["admin2"], status="approved")
    assert [i.bulk_group_id for i in approved.bulk_operations] == [a.bulk_group_id]
    assert approved.bulk_operations[0].approved_by_name == "Admin1"
    assert approved.pending == 1 and approved.total == 1

    rejected = _list(db, world["admin2"], status="rejected").bulk_operations
    assert [i.bulk_group_id for i in rejected] == [b.bulk_group_id] and rejected[0].rejection_reason == REASON
    assert _list(db, world["admin2"], status="all").total == 3
    _raises(400, _list, db, world["admin2"], status="nonsense")


def test_member_full_name_shown_to_reviewers(db, world):
    r = _create(db, world["regular"], ["2026-08"])
    assert _list(db, world["admin1"]).bulk_operations[0].member_name == "Regular"
    details = admin_router.get_bulk_challan_details(r.bulk_group_id, db=db, current_user=_ctx(world["admin1"]))
    assert details.member_name == "Regular" and details.member_user_id == world["regular"].id
    assert details.has_proof is True


# ── Errors ────────────────────────────────────────────────────────────────

def test_internal_errors_are_not_shown(db, world, monkeypatch):
    r = _create(db, world["regular"], ["2026-08"])
    monkeypatch.setattr(admin_router, "AuditLog", lambda **k: (_ for _ in ()).throw(RuntimeError("secret table name")))
    err = _raises(500, _approve, db, r.bulk_group_id, world["admin1"])
    assert err.detail == GENERIC_ERROR
    assert db.query(Challan).filter_by(bulk_group_id=r.bulk_group_id).one().status == ChallanStatus.PENDING


def test_double_approve_is_refused(db, world):
    r = _create(db, world["regular"], ["2026-08"])
    _approve(db, r.bulk_group_id, world["admin1"])
    _raises(400, _approve, db, r.bulk_group_id, world["admin2"])
    group = db.query(BulkChallanGroup).one()
    assert json.loads(group.challan_ids_list)


def test_month_errors_read_as_sentences():
    from app.main import _ensure_detail_list

    out = _ensure_detail_list({"message": "Challan already exists for one or more months",
                               "duplicate_months": ["2026-08", "2026-09"]}, default_type="http_error")
    assert out[0]["msg"] == "Challan already exists for one or more months: 2026-08, 2026-09"
    assert out[0]["input"]["duplicate_months"] == ["2026-08", "2026-09"]
    # details that already carry their own input (activation login) are unchanged
    kept = _ensure_detail_list({"type": "activation_pending", "msg": "Waiting", "input": {"member_code": "M1"}})
    assert kept[0]["input"] == {"member_code": "M1"} and kept[0]["type"] == "activation_pending"
