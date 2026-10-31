import importlib
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import Challan, ChallanStatus, ChallanType, Member, User, UserRole
from app.routes import challan_routes, member_routes
from app.schemas.schemas import ChallanApprove, MemberCreate
from app.services import admin_payment_service
from app.services.challan_service import ChallanService
from app.services.notification_service import NotificationService
from app.services.settings_service import invalidate_cache
from app.utils.auth import get_current_admin
from app.utils.timezone import today_business

admin_router = importlib.import_module("app.routes.admin_router")

MONTHS = ["2026-08", "2026-09"]


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    invalidate_cache()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)
    monkeypatch.setattr(
        ChallanService, "get_payable_months", staticmethod(lambda db, member_id, include_upcoming=True: {"all_months": MONTHS + ["2026-10"]})
    )


def _user(db, name, role):
    u = User(username=name, password_hash="x", role=role, full_name=name.title(), is_active=True)
    db.add(u)
    db.flush()
    return u


def _ctx(u):
    return {"user_id": u.id, "role": u.role.value, "username": u.username}


@pytest.fixture()
def world(db):
    admin1 = _user(db, "admin1", UserRole.ADMIN)
    admin2 = _user(db, "admin2", UserRole.ADMIN)
    sup = _user(db, "super", UserRole.SUPERADMIN)
    regular = _user(db, "regular", UserRole.MEMBER)
    members = {}
    for key, user in {"admin1": admin1, "regular": regular}.items():
        m = Member(user_id=user.id, member_code=f"M-{key}", full_name=user.full_name, monthly_amount=500, status="active")
        db.add(m)
        db.flush()
        members[key] = m
    db.commit()
    return {"admin1": admin1, "admin2": admin2, "super": sup, "regular": regular, "members": members}


def _record(db, actor, member, **over):
    args = dict(
        member_id=member.id,
        challan_type="monthly",
        months=["2026-08"],
        campaign_id=None,
        amount_per_month=None,
        amount=None,
        payment_method="cash",
        transaction_ref=None,
        received_on=today_business(),
        collected_by_user_id=None,
        entry_notes="Collected at the mosque",
    )
    args.update(over)
    return admin_payment_service.record_payment(db, _ctx(actor), **args)


def _err(status, fn, *a, **k):
    with pytest.raises(HTTPException) as exc:
        fn(*a, **k)
    assert exc.value.status_code == status
    return exc.value.detail


def test_cash_record_is_pending_with_creator_and_collector(db, world):
    created = _record(db, world["admin1"], world["members"]["regular"])
    c = created[0]
    assert c.status == ChallanStatus.PENDING
    assert c.entry_source == "admin"
    assert c.created_by_user_id == world["admin1"].id
    assert c.collected_by_user_id == world["admin1"].id


def test_creator_and_collector_cannot_approve_other_admin_can(db, world):
    c = _record(db, world["admin1"], world["members"]["regular"], collected_by_user_id=world["admin2"].id)[0]
    assert "different admin" in _err(403, challan_routes.approve_challan, c.id, ChallanApprove(), _ctx(world["admin1"]), db)
    assert "did not collect" in _err(403, challan_routes.approve_challan, c.id, ChallanApprove(), _ctx(world["admin2"]), db)
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(world["super"]), db)
    db.refresh(c)
    assert c.status == ChallanStatus.APPROVED


def test_superadmin_creator_is_blocked_too(db, world):
    c = _record(db, world["super"], world["members"]["regular"])[0]
    _err(403, challan_routes.approve_challan, c.id, ChallanApprove(), _ctx(world["super"]), db)
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(world["admin2"]), db)


def test_import_challans_not_subject_to_rules(db, world):
    c = Challan(
        member_id=world["members"]["regular"].id, type=ChallanType.MONTHLY, month="2026-07", amount=500,
        status=ChallanStatus.PENDING, entry_source="import", created_by_user_id=world["admin1"].id,
    )
    db.add(c)
    db.commit()
    challan_routes.approve_challan(c.id, ChallanApprove(), _ctx(world["admin1"]), db)
    db.refresh(c)
    assert c.status == ChallanStatus.APPROVED


def test_bank_and_upi_need_reference_and_duplicate_is_409(db, world):
    m = world["members"]["regular"]
    _err(400, _record, db, world["admin1"], m, payment_method="upi", transaction_ref=None, entry_notes=None)
    first = _record(db, world["admin1"], m, payment_method="bank_transfer", transaction_ref="UTR123", entry_notes=None)[0]
    detail = _err(409, _record, db, world["admin2"], m, months=["2026-09"], payment_method="upi", transaction_ref="utr123", entry_notes=None)
    assert f"#{first.id}" in detail


def test_notes_required_for_cash_other_and_custom_amount(db, world):
    m = world["members"]["regular"]
    _err(400, _record, db, world["admin1"], m, entry_notes=None)
    _err(400, _record, db, world["admin1"], m, payment_method="other", entry_notes=None)
    _err(400, _record, db, world["admin1"], m, payment_method="upi", transaction_ref="R1", entry_notes=None, amount_per_month=300)
    ok = _record(db, world["admin1"], m, payment_method="upi", transaction_ref="R2", entry_notes="Partial", amount_per_month=300)
    assert float(ok[0].amount) == 300


def test_cannot_record_own_payment(db, world):
    detail = _err(403, _record, db, world["admin1"], world["members"]["admin1"])
    assert "cannot record your own" in detail


def test_future_received_on_rejected(db, world):
    _err(400, _record, db, world["admin1"], world["members"]["regular"], received_on=today_business() + timedelta(days=1))


def test_multi_month_creates_one_challan_each(db, world):
    created = _record(db, world["admin1"], world["members"]["regular"], months=MONTHS)
    assert [c.month for c in created] == MONTHS


def test_collector_must_be_active_admin(db, world):
    _err(400, _record, db, world["admin1"], world["members"]["regular"], collected_by_user_id=world["regular"].id)


def test_creator_only_can_edit_pending_admin_entry(db, world):
    c = _record(db, world["admin1"], world["members"]["regular"])[0]
    _err(403, challan_routes.delete_challan, c.id, _ctx(world["admin2"]), db)


def test_record_notifies_other_admins_and_member_once(db, world):
    created = _record(db, world["admin1"], world["members"]["regular"])
    NotificationService.notify_admin_recorded_payment(db, created, world["admin1"].id, "Admin1")
    from app.models.models import Notification

    recipients = sorted(n.user_id for n in db.query(Notification).all())
    assert recipients == sorted([world["admin2"].id, world["super"].id, world["regular"].id])


def test_offline_member_creation_allowed_for_admin_and_superadmin_not_member(db, world):
    for actor in (world["admin1"], world["super"]):
        member = member_routes.create_member(
            MemberCreate(full_name=f"Offline {actor.username}", phone=f"90000000{actor.id}", monthly_amount=100), _ctx(actor), db
        )
        assert member.id
    assert get_current_admin(_ctx(world["admin1"]))
    assert get_current_admin(_ctx(world["super"]))
    _err(403, get_current_admin, _ctx(world["regular"]))


def test_cash_report_totals_by_collector(db, world):
    m = world["members"]["regular"]
    a = _record(db, world["admin1"], m, months=["2026-08"])[0]
    _record(db, world["admin1"], m, months=["2026-09"], collected_by_user_id=world["admin2"].id)
    challan_routes.approve_challan(a.id, ChallanApprove(), _ctx(world["admin2"]), db)
    month = today_business().strftime("%Y-%m")
    report = admin_router.cash_collected_report(month, _ctx(world["admin1"]), db)
    by = {r["collected_by_user_id"]: r for r in report["collectors"]}
    assert by[world["admin1"].id]["approved_amount"] == 500
    assert by[world["admin2"].id]["pending_amount"] == 500
    assert report["total_approved_amount"] == 500 and report["total_pending_amount"] == 500
