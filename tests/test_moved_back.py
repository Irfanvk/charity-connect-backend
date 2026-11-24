"""A payment approved, moved back for checking, fixed and approved again: two people every
time, the date is kept, old values are logged, the story is shown, admins are reminded after
7 days, and the receipt says it is corrected."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException

import app.services  # noqa: F401  (load order)
from app.models.models import AuditLog, ChallanStatus, Notification, NudgeLog, UserRole
from app.schemas.schemas import BulkChallanApprove, ChallanApprove, ChallanRevert, ChallanUpdate
from app.services import payment_history, receipt_service, unfinished_service
from tests.test_separation_of_duties import (  # noqa: F401
    REASON, _bulk, _challan, _ctx, _forbidden, _user, admin_router, challan_routes, db, stub_dispatch, world,
)

PAID_ON = date(2026, 10, 3)


def _approved_then_moved_back(db, world):
    admin1, admin2 = world["admin1"], world["admin2"]
    c = _challan(db, world["members"]["regular"])
    challan_routes.approve_challan(c.id, ChallanApprove(received_on=PAID_ON), _ctx(admin1), db)
    challan_routes.revert_challan(c.id, ChallanRevert(reason="Wrong date: paid on 3 Oct"), _ctx(admin2), db)
    db.refresh(c)
    return c


def test_admin_who_moved_it_back_cannot_approve_it_again(db, world):
    c = _approved_then_moved_back(db, world)
    detail = _forbidden(challan_routes.approve_challan, c.id, ChallanApprove(), _ctx(world["admin2"]), db)
    assert "different admin" in detail
    # someone else can (and the first approver too: a second person checked the change)
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(world["admin1"]), db)
    db.refresh(c)
    assert c.status == ChallanStatus.APPROVED


def test_admin_who_changed_it_after_moving_back_cannot_approve(db, world):
    c = _approved_then_moved_back(db, world)
    third = _user(db, "admin3", UserRole.ADMIN)
    challan_routes.update_challan(c.id, ChallanUpdate(amount=600), _ctx(world["admin1"]), db)
    _forbidden(challan_routes.approve_challan, c.id, ChallanApprove(), _ctx(world["admin1"]), db)
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(third), db)
    db.refresh(c)
    assert c.status == ChallanStatus.APPROVED


def test_edit_log_keeps_old_values(db, world):
    c = _approved_then_moved_back(db, world)
    challan_routes.update_challan(c.id, ChallanUpdate(amount=600), _ctx(world["admin1"]), db)
    row = db.query(AuditLog).filter_by(action="challan_update", entity_id=c.id).one()
    assert json.loads(row.old_values)["amount"] == 500
    assert json.loads(row.new_values)["amount"] == 600


def test_approve_again_needs_the_date_received(db, world):
    admin1, admin2 = world["admin1"], world["admin2"]
    c = _challan(db, world["members"]["regular"])
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(admin1), db)  # first time: no date given
    challan_routes.revert_challan(c.id, ChallanRevert(reason=REASON), _ctx(admin2), db)
    third = _user(db, "admin3", UserRole.ADMIN)
    with pytest.raises(HTTPException) as e:
        challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(third), db)
    assert e.value.status_code == 400 and "date the money was received" in e.value.detail
    challan_routes.approve_challan(c.id, ChallanApprove(received_on=PAID_ON), _ctx(third), db)


def test_normal_first_approval_is_unchanged(db, world):
    c = _challan(db, world["members"]["regular"])
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(world["admin2"]), db)
    db.refresh(c)
    assert c.status == ChallanStatus.APPROVED


def test_history_tells_the_story(db, world):
    c = _approved_then_moved_back(db, world)
    challan_routes.update_challan(c.id, ChallanUpdate(amount=600), _ctx(world["admin1"]), db)
    third = _user(db, "admin3", UserRole.ADMIN)
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(third), db)

    staff = challan_routes.get_payment_history(c.id, _ctx(world["admin1"]), db)
    labels = [s["label"] for s in staff["steps"]]
    assert labels == ["Payment started", "Approved", "Moved back for checking", "Details changed", "Approved again"]
    moved = staff["steps"][2]
    assert moved["reason"] == "Wrong date: paid on 3 Oct"
    assert staff["steps"][3]["changes"] == [{"field": "Amount", "from": 500, "to": 600}]
    assert staff["steps"][3]["by"] == "You"
    assert staff["moved_back"] is True

    member = challan_routes.get_payment_history(c.id, _ctx(world["regular"]), db)
    assert {s["by"] for s in member["steps"][1:]} == {"the committee"}
    assert member["steps"][2]["reason"] == "Wrong date: paid on 3 Oct"


def test_member_cannot_see_someone_elses_history(db, world):
    c = _challan(db, world["members"]["admin1"])
    _forbidden(challan_routes.get_payment_history, c.id, _ctx(world["regular"]), db)


def test_bulk_moved_back_two_person_rule_and_history(db, world):
    admin1, admin2 = world["admin1"], world["admin2"]
    regular_creator = world["regular"]
    group, challans = _bulk(db, world["members"]["regular"], regular_creator)
    admin_router.approve_bulk_challans("BG-1", BulkChallanApprove(approved=True, received_on=PAID_ON), db, _ctx(admin1))
    admin_router.revert_bulk_challans("BG-1", ChallanRevert(reason="Proof problem: blurry"), db, _ctx(admin2))
    _forbidden(admin_router.approve_bulk_challans, "BG-1", BulkChallanApprove(approved=True), db, _ctx(admin2))
    admin_router.approve_bulk_challans("BG-1", BulkChallanApprove(approved=True), db, _ctx(admin1))

    story = challan_routes.get_bulk_payment_history("BG-1", _ctx(admin1), db)
    assert [s["label"] for s in story["steps"]][-2:] == ["Moved back for checking", "Approved again"]


def test_moved_back_list_and_weekly_reminder(db, world, monkeypatch):
    c = _approved_then_moved_back(db, world)
    listed = challan_routes.get_moved_back_payments(_ctx(world["admin1"]), db)
    assert listed["count"] == 1 and listed["items"][0]["reason"] == "Wrong date: paid on 3 Oct"
    assert listed["items"][0]["days"] == 0

    class Nine:
        hour = 10
    monkeypatch.setattr(unfinished_service, "now_business", lambda: Nine)
    assert unfinished_service.run_moved_back_reminder(db)["status"] == "nothing_due"

    c.reversed_at = datetime.utcnow() - timedelta(days=8)
    db.commit()
    result = unfinished_service.run_moved_back_reminder(db)
    assert result["status"] == "sent" and result["payments"] == 1
    note = db.query(Notification).filter_by(title="Payments waiting to be approved again").first()
    assert "8 days" in note.message
    # not again the same week
    assert unfinished_service.run_moved_back_reminder(db)["status"] == "nothing_due"
    assert db.query(NudgeLog).count() == 1


def test_receipt_is_marked_corrected(db, world):
    c = _approved_then_moved_back(db, world)
    assert receipt_service.for_challan(db, c)["corrected"] is False  # not valid while moved back
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(world["admin1"]), db)
    db.refresh(c)
    data = receipt_service.for_challan(db, c)
    assert data["valid"] and data["corrected"] is True
    assert receipt_service.public_view(db, data["token"])["corrected"] is True


def test_people_who_changed_it_is_empty_when_never_moved_back(db, world):
    c = _challan(db, world["members"]["regular"])
    assert payment_history.people_who_changed_it(db, [c], None) == set()
