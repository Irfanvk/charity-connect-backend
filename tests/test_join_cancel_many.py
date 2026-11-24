"""Undo for many "not paid yet" payments made one by one by mistake: join them into one payment,
or cancel them all at once. Money received for a far-ahead month that already has an open
payment can be recorded (it fills that payment)."""
from datetime import datetime

import pytest
from fastapi import HTTPException

import app.services  # noqa: F401  (load order)
from app.models.models import AuditLog, BulkChallanGroup, Challan, ChallanStatus, ChallanType
from app.routes.challan_routes import ManyChallans
from app.services import admin_payment_service
from app.services.challan_service import ChallanService
from app.utils.timezone import today_business
from tests.test_separation_of_duties import (  # noqa: F401
    _ctx, challan_routes, db, stub_dispatch, world,
)

MONTHS = ["2028-01", "2028-02", "2028-03"]


def _made_by_mistake(db, member, admin, months=MONTHS):
    made = datetime.utcnow()
    rows = []
    for i, m in enumerate(months):
        c = Challan(member_id=member.id, type=ChallanType.MONTHLY, month=m, amount=500,
                    status=ChallanStatus.GENERATED, entry_source="admin", created_by_user_id=admin.id,
                    challan_no=f"PG-2026-{i + 1:04d}", created_at=made)
        db.add(c)
        rows.append(c)
    db.commit()
    return rows


def test_join_gives_one_payment_number(db, world):
    rows = _made_by_mistake(db, world["members"]["regular"], world["admin1"])
    out = challan_routes.join_into_one_payment(ManyChallans(challan_ids=[c.id for c in rows]), _ctx(world["admin1"]), db)
    assert out["challan_no"] == "PG-2026-0001" and out["total_amount"] == 1500
    for c in rows:
        db.refresh(c)
        assert c.challan_no == "PG-2026-0001"
    logs = db.query(AuditLog).filter_by(action="challan_join").all()
    assert {(l.entity_id) for l in logs} == {c.id for c in rows}


def test_join_refuses_paid_or_mixed(db, world):
    rows = _made_by_mistake(db, world["members"]["regular"], world["admin1"])
    rows[0].proof_path = "proofs/x.png"
    rows[0].status = ChallanStatus.PENDING
    db.commit()
    with pytest.raises(HTTPException) as e:
        challan_routes.join_into_one_payment(ManyChallans(challan_ids=[c.id for c in rows]), _ctx(world["admin1"]), db)
    assert e.value.status_code == 409
    other = _made_by_mistake(db, world["members"]["admin1"], world["admin2"], months=["2028-05"])
    with pytest.raises(HTTPException) as e:
        challan_routes.join_into_one_payment(ManyChallans(challan_ids=[rows[1].id, other[0].id]), _ctx(world["admin1"]), db)
    assert e.value.status_code == 400


def test_only_the_admin_who_made_them_can_join_or_cancel(db, world):
    rows = _made_by_mistake(db, world["members"]["regular"], world["admin1"])
    with pytest.raises(HTTPException) as e:
        challan_routes.cancel_many_payments(ManyChallans(challan_ids=[c.id for c in rows]), _ctx(world["admin2"]), db)
    assert e.value.status_code == 403
    assert db.query(Challan).count() == 3


def test_cancel_all_at_once_is_logged(db, world):
    rows = _made_by_mistake(db, world["members"]["regular"], world["admin1"])
    out = challan_routes.cancel_many_payments(
        ManyChallans(challan_ids=[c.id for c in rows], reason="Made one by one by mistake"), _ctx(world["admin1"]), db)
    assert out["cancelled"] == 3
    assert db.query(Challan).count() == 0
    logs = db.query(AuditLog).filter_by(action="challan_delete").all()
    assert len(logs) == 3


def test_far_ahead_open_months_are_offered_and_can_be_recorded(db, world, monkeypatch):
    member = world["members"]["regular"]
    member.monthly_amount = 500
    db.commit()
    rows = _made_by_mistake(db, member, world["admin1"])
    payable = ChallanService.get_payable_months(db, member.id, include_upcoming=True, include_unpaid_placeholders=True)
    assert set(MONTHS) <= set(payable["all_months"])
    # a member never sees them as payable ahead
    plain = ChallanService.get_payable_months(db, member.id, include_upcoming=True)
    assert not set(MONTHS) & set(plain["all_months"])

    created = admin_payment_service.record_payment(
        db, _ctx(world["admin2"]), member_id=member.id, challan_type="monthly", months=MONTHS, campaign_id=None,
        amount_per_month=None, amount=None, payment_method="cash", transaction_ref=None,
        received_on=today_business(), collected_by_user_id=None, entry_notes="Paid 3 years ahead in cash")
    assert {c.id for c in created} == {c.id for c in rows}  # filled, not duplicated
    assert db.query(BulkChallanGroup).count() == 1
    assert db.query(Challan).count() == 3
