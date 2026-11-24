"""Executive: sees every report, member and payment, helps members (payments, proof, cash,
reminders) but never approves, rejects or edits. Sees admin codes; members see "the committee"."""
import importlib
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models.models import Challan, ChallanStatus, ChallanType, Member, User, UserRole
from app.routes import challan_routes, member_routes, report_routes
from app.utils.auth import create_access_token

admin_router = importlib.import_module("app.routes.admin_router")


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    app = FastAPI()
    for r in (challan_routes.router, member_routes.router, report_routes.router, admin_router.router):
        app.include_router(r)

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    from app.services.notification_service import NotificationService
    monkeypatch.setattr(NotificationService, "dispatch_notification", lambda db, n: None)

    db = Session()
    admin = User(username="adm", password_hash="x", role=UserRole.ADMIN, full_name="Real Admin Name", is_active=True)
    exe = User(username="exe", password_hash="x", role=UserRole.EXECUTIVE, full_name="Exe Name", is_active=True)
    mem = User(username="mem", password_hash="x", role=UserRole.MEMBER, full_name="Mem Ber", is_active=True)
    db.add_all([admin, exe, mem])
    db.flush()
    db.add_all([Member(user_id=admin.id, member_code="MEM-0012", full_name="Real Admin Name", monthly_amount=500,
                       status="active", join_date=date(2024, 8, 1)),
                Member(user_id=exe.id, member_code="MEM-0007", full_name="Exe Name", monthly_amount=500,
                       status="active", join_date=date(2024, 8, 1)),
                Member(user_id=mem.id, member_code="MEM-0050", full_name="Mem Ber", monthly_amount=500,
                       status="active", join_date=date(2024, 8, 1))])
    db.commit()
    m = db.query(Member).filter(Member.user_id == mem.id).one()
    paid = Challan(member_id=m.id, type=ChallanType.MONTHLY, month="2026-09", amount=500,
                   status=ChallanStatus.APPROVED, approved_by_admin_id=admin.id, entry_source="self",
                   created_by_user_id=mem.id)
    db.add(paid)
    db.commit()
    client = TestClient(app)

    def as_(user):
        return {"Authorization": "Bearer " + create_access_token({"sub": str(user.id), "role": user.role.value})}

    yield {"c": client, "db": db, "admin": admin, "exe": exe, "mem": mem, "member": m, "paid": paid, "as": as_}
    db.close()


def test_executive_sees_codes_member_sees_committee(env):
    c, paid = env["c"], env["paid"]
    staff = c.get(f"/challans/{paid.id}", headers=env["as"](env["exe"])).json()
    assert staff["approved_by_name"] == "admin (A12)"
    mine = c.get(f"/challans/{paid.id}", headers=env["as"](env["mem"])).json()
    assert mine["approved_by_name"] == "the committee"
    assert "Real Admin" not in str(mine) and "A12" not in str(mine)


def test_executive_can_view_everything(env):
    c, h = env["c"], env["as"](env["exe"])
    assert c.get("/members/", headers=h).status_code == 200
    assert c.get(f"/members/{env['member'].id}", headers=h).status_code == 200
    assert c.get(f"/members/{env['member'].id}/fees", headers=h).status_code == 200
    assert c.get("/reports/dues", headers=h).status_code == 200
    assert c.get(f"/reports/member-statement/{env['member'].id}", headers=h).status_code == 200
    assert c.get("/challans/", headers=h).status_code == 200
    assert c.get("/admin/bulk-pending-review", headers=h).status_code == 200


def test_executive_creates_a_payment_for_a_member_but_cannot_decide(env):
    c, h = env["c"], env["as"](env["exe"])
    r = c.post("/challans/", headers=h, json={"member_id": env["member"].id, "type": "monthly",
                                               "month": "2026-10", "amount": 500})
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    assert r.json()["entry_source"] == "admin"
    assert c.patch(f"/challans/{new_id}/approve", headers=h, json={}).status_code == 403
    assert c.patch(f"/challans/{new_id}/reject", headers=h, json={"rejection_reason": "x" * 20}).status_code == 403
    assert c.patch(f"/challans/{new_id}", headers=h, json={"amount": 100}).status_code == 403
    assert c.put(f"/members/{env['member'].id}", headers=h, json={"monthly_amount": 1}).status_code == 403
    # a mistake can be removed while it is not approved
    assert c.delete(f"/challans/{new_id}", headers=h).status_code == 200
    # but not someone else's approved payment
    assert c.delete(f"/challans/{env['paid'].id}", headers=h).status_code in (400, 403)


def test_member_still_cannot_see_others(env):
    c, h = env["c"], env["as"](env["mem"])
    assert c.get("/reports/dues", headers=h).status_code == 403
    admin_member = env["db"].query(Member).filter(Member.user_id == env["admin"].id).one()
    assert c.get(f"/members/{admin_member.id}", headers=h).status_code == 403


def test_dashboard_top_donors_carry_the_members_name(env):
    out = env["c"].get("/admin/dashboard/charts", headers=env["as"](env["admin"])).json()
    top = out["top_donors"][0]
    assert top["member_code"] == "MEM-0050"
    assert top["full_name"] == "Mem Ber" and top["name"] == "mem"
