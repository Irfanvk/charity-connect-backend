"""Audit Logs feed: filters, pages, readable names and changes, CSV export."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import AuditLog, Challan, ChallanStatus, ChallanType, Member, MemberRequest, RequestStatus, RequestType, User, UserRole
from app.routes import audit_log_routes
from app.services import audit_feed_service as feed


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def world(db):
    admin = User(username="aisha", full_name="Aisha Admin", password_hash="x", role=UserRole.ADMIN)
    sup = User(username="sam", full_name="Sam Super", password_hash="x", role=UserRole.SUPERADMIN)
    mem = User(username="rahul", password_hash="x", role=UserRole.MEMBER)
    db.add_all([admin, sup, mem])
    db.flush()
    member = Member(user_id=mem.id, member_code="MEM-0001", full_name="Rahul K")
    db.add(member)
    db.flush()
    challan = Challan(member_id=member.id, type=ChallanType.MONTHLY, month="2026-10", amount=100,
                      status=ChallanStatus.APPROVED, payment_method="cash")
    req = MemberRequest(member_id=member.id, user_id=mem.id, request_type=RequestType.COMPLAINT,
                        status=RequestStatus.PENDING, subject="Old complaint", message="x")
    db.add_all([challan, req])
    db.flush()
    now = datetime.utcnow()
    logs = [
        AuditLog(user_id=admin.id, action="challan_approve", entity_type="Challan", entity_id=challan.id,
                 old_values=json.dumps({"status": "pending"}), new_values=json.dumps({"status": "approved"}),
                 created_at=now - timedelta(hours=1)),
        AuditLog(user_id=sup.id, action="member_update", entity_type="Member", entity_id=member.id,
                 old_values=json.dumps({"monthly_amount": 100, "city": "Kochi"}),
                 new_values=json.dumps({"monthly_amount": 150, "city": "Kochi", "password_hash": "abc"}),
                 created_at=now - timedelta(days=3)),
        AuditLog(user_id=admin.id, action="request_deleted", entity_type="MemberRequest", entity_id=req.id,
                 old_values=json.dumps({"subject": "Old complaint"}), created_at=now - timedelta(days=10)),
        AuditLog(user_id=None, action="app_settings_update", entity_type="AppSetting", entity_id=0, created_at=now),
    ]
    db.add_all(logs)
    db.commit()
    return {"admin": admin, "super": sup, "member": member, "logs": logs}


def test_feed_newest_first_with_names_and_changes(db, world):
    out = feed.feed(db)
    assert out["total"] == 4 and out["has_more"] is False
    assert [i["action"] for i in out["items"]] == ["app_settings_update", "challan_approve", "member_update", "request_deleted"]
    approve = out["items"][1]
    assert approve["target_name"] == "Rahul K · Oct 2026"
    assert approve["area"] == "payments" and approve["performed_by_name"] == "Aisha Admin"
    assert approve["changes"] == [{"field": "status", "before": "pending", "after": "approved"}]
    update = out["items"][2]
    assert update["target_name"] == "Rahul K"
    # unchanged fields are left out; secrets are hidden
    assert {"field": "monthly_amount", "before": 100, "after": 150} in update["changes"]
    assert all(c["field"] != "city" for c in update["changes"])
    assert update["new_values"]["password_hash"] == "(hidden)"
    assert out["items"][3]["target_name"] == "Rahul K · Old complaint"
    assert out["counts"] == {"admin": 2, "superadmin": 1, "actors": 2}


def test_feed_filters(db, world):
    ids = lambda **kw: [i["action"] for i in feed.feed(db, **kw)["items"]]
    assert ids(user_id=world["super"].id) == ["member_update"]
    assert ids(role="admin") == ["challan_approve", "request_deleted"]
    assert ids(role="system") == ["app_settings_update"]
    assert ids(area="requests") == ["request_deleted"]
    assert ids(area="settings") == ["app_settings_update"]
    assert ids(action="member_update") == ["member_update"]
    week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    assert "request_deleted" not in ids(start_date=week_ago)
    assert ids(search="sam super") == ["member_update"]
    assert ids(search="approved") == ["challan_approve"]
    with pytest.raises(HTTPException):
        feed.feed(db, role="boss")
    with pytest.raises(HTTPException):
        feed.feed(db, area="nowhere")


def test_feed_pages(db, world):
    first = feed.feed(db, limit=3)
    assert len(first["items"]) == 3 and first["has_more"] is True
    rest = feed.feed(db, skip=3, limit=3)
    assert len(rest["items"]) == 1 and rest["has_more"] is False


def test_filter_options_list_everything(db, world):
    out = feed.filter_options(db)
    assert [a["name"] for a in out["actors"]] == ["Sam Super", "Aisha Admin"]
    assert {a["action"] for a in out["actions"]} == {"challan_approve", "member_update", "request_deleted", "app_settings_update"}
    counts = {a["area"]: a["count"] for a in out["areas"]}
    assert counts["payments"] == 1 and counts["members"] == 1 and counts["bulk"] == 0
    assert out["system_count"] == 1


def test_mixed_entity_spelling_maps_to_one_area():
    assert feed.area_of("member_request") == feed.area_of("MemberRequest") == "requests"
    assert feed.area_of("bulk_challan") == feed.area_of("BulkChallanGroup") == "bulk"
    assert feed.area_of("Something") == "other"


def test_export_csv(db, world):
    resp = audit_log_routes.export_audit_feed(area="payments", _current_user={"role": "admin"}, db=db,
                                              user_id=None, role=None, action=None, start_date=None,
                                              end_date=None, search=None)
    text = resp.body.decode()
    assert text.splitlines()[0].startswith("When (India time),Who,Role,Action")
    assert "Rahul K · Oct 2026" in text and "status: pending -> approved" in text
    assert len(text.strip().splitlines()) == 2


def test_deleted_item_named_from_recorded_values(db, world):
    db.add_all([
        AuditLog(user_id=world["admin"].id, action="bulk_approve", entity_type="BulkChallanGroup", entity_id=999,
                 new_values=json.dumps({"member_id": world["member"].id, "months": ["2027-01", "2027-02"]})),
        AuditLog(user_id=world["admin"].id, action="report_generated", entity_type="Report", entity_id=0),
    ])
    db.commit()
    items = {i["action"]: i for i in feed.feed(db, limit=100)["items"]}
    assert items["bulk_approve"]["target_name"] == "Rahul K · Jan 2027 – Feb 2027"
    assert items["report_generated"]["area"] == "reports"
