"""Self-activation of existing (imported) members with admin approval."""
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import (
    AuditLog, Challan, ChallanStatus, ChallanType, Member, MemberActivation, Notification, User, UserRole,
)
from app.routes.activation_routes import MemberActivationCreate
from app.schemas.schemas import UserLogin
from app.services import member_activation_service as mas
from app.services.auth_service import AuthService
from app.services.member_activation_service import MemberActivationService, find_member_by_code, name_match
from app.services.notification_service import NotificationService
from app.utils.auth import hash_password, verify_password


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
    for name in ("_assert_not_rate_limited", "_register_failed_attempt", "_reset_failed_attempts"):
        monkeypatch.setattr(AuthService, name, staticmethod(lambda *a, **k: None))
    mas.reset_rate_limit()
    yield
    mas.reset_rate_limit()


@pytest.fixture()
def world(db):
    admin = User(username="admin1", password_hash=hash_password("Admin@1234"), role=UserRole.ADMIN, is_active=True)
    imported = User(username="mohammed_ali_0001", password_hash=hash_password("unknown-placeholder"),
                    role=UserRole.MEMBER, is_active=False, full_name="Mohammed Ali")
    active = User(username="already", password_hash=hash_password("x"), role=UserRole.MEMBER, is_active=True,
                  phone="+966511111111", email="taken@example.org")
    db.add_all([admin, imported, active])
    db.flush()
    member = Member(user_id=imported.id, member_code="MEM-0001", full_name="Mohammed Ali", monthly_amount=100)
    other = Member(user_id=active.id, member_code="MEM-0002", full_name="Already Active")
    db.add_all([member, other])
    db.flush()
    for month in ("2026-08", "2026-09"):
        db.add(Challan(member_id=member.id, type=ChallanType.MONTHLY, month=month, amount=100,
                       status=ChallanStatus.APPROVED))
    db.commit()
    return {"admin": admin, "imported": imported, "member": member}


def _payload(**overrides):
    data = dict(member_code="0001", full_name="Mohamed Ali", phone="+966 500 000 001",
                email="Ali@Example.org", username="mali", password="Secret@123", last_paid_month="2026-09")
    data.update(overrides)
    return MemberActivationCreate(**data)


def _admin(world):
    return {"user_id": world["admin"].id, "role": "admin"}


def _login(db, username, password):
    return AuthService.login(db, UserLogin(username=username, password=password))


def test_member_code_lookup_is_forgiving(db, world):
    for entered in ("0001", "1", "#0001", "MEM-0001", "mem-1", "MEM 0001"):
        assert find_member_by_code(db, entered).member_code == "MEM-0001", entered
    assert find_member_by_code(db, "9999") is None


def test_name_matching():
    assert name_match("Mohammed Ali", "mohammed ali") == "match"
    assert name_match("Ali Mohammed", "Mohammed Ali") == "match"
    assert name_match("Mohamed Ali", "Mohammed Ali") == "match"
    assert name_match("Mohd Ali K", "Mohammed Ali") == "close"
    assert name_match("Rahul Sharma", "Mohammed Ali") == "different"


def test_submit_creates_pending_request_and_notifies_admins(db, world):
    result = MemberActivationService.submit(db, _payload(), source_ip="1.2.3.4")
    assert result["status"] == "pending" and result["member_code"] == "MEM-0001"
    item = db.get(MemberActivation, result["id"])
    assert item.phone == "+966500000001" and item.email == "ali@example.org"
    assert verify_password("Secret@123", item.password_hash)
    # Nothing on the member's account changes before approval.
    db.refresh(world["imported"])
    assert world["imported"].is_active is False and world["imported"].username == "mohammed_ali_0001"
    notes = db.query(Notification).filter(Notification.entity_type == "member_activation").all()
    assert [n.user_id for n in notes] == [world["admin"].id]


def test_unknown_member_id_and_active_member_are_refused(db, world):
    with pytest.raises(HTTPException) as exc:
        MemberActivationService.submit(db, _payload(member_code="0099"))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        MemberActivationService.submit(db, _payload(member_code="0002", username="other1"))
    assert exc.value.status_code == 409


def test_contact_and_username_conflicts(db, world):
    for overrides in ({"phone": "+966511111111"}, {"email": "TAKEN@example.org"}, {"username": "admin1"}):
        with pytest.raises(HTTPException) as exc:
            MemberActivationService.submit(db, _payload(**overrides))
        assert exc.value.status_code == 409, overrides


def test_email_or_whatsapp_required(db, world):
    with pytest.raises(HTTPException) as exc:
        MemberActivationService.submit(db, _payload(email=None, no_email=True))
    assert exc.value.status_code == 400
    ok = MemberActivationService.submit(db, _payload(email=None, no_email=True, whatsapp_phone="+966500000001"))
    assert db.get(MemberActivation, ok["id"]).email is None


def test_resubmission_updates_the_same_request(db, world):
    first = MemberActivationService.submit(db, _payload())
    second = MemberActivationService.submit(db, _payload(password="NewSecret@1", last_paid_month=None))
    assert first["id"] == second["id"] and second["updated"] is True
    assert db.query(MemberActivation).count() == 1
    assert db.query(Notification).filter(Notification.entity_type == "member_activation").count() == 1


def test_pending_username_is_reserved(db, world):
    MemberActivationService.submit(db, _payload())
    db.add(Member(user_id=db.query(User).filter_by(username="admin1").one().id, member_code="MEM-0003"))
    db.commit()
    # A different member cannot take the same pending username.
    with pytest.raises(HTTPException) as exc:
        MemberActivationService.submit(db, _payload(member_code="0003", phone="+966522222222", email="b@x.org"))
    assert exc.value.status_code in (409,)


def test_login_shows_pending_status_then_rejection(db, world):
    result = MemberActivationService.submit(db, _payload())
    with pytest.raises(HTTPException) as exc:
        _login(db, "mali", "Secret@123")
    assert exc.value.status_code == 403
    assert exc.value.detail["type"] == "activation_pending"
    assert exc.value.detail["input"]["member_code"] == "MEM-0001"
    # Wrong password stays a normal failure.
    with pytest.raises(HTTPException) as exc:
        _login(db, "mali", "wrong-password")
    assert exc.value.status_code == 401

    MemberActivationService.reject(db, _admin(world), result["id"], "Name does not match our records")
    with pytest.raises(HTTPException) as exc:
        _login(db, "mali", "Secret@123")
    assert exc.value.detail["type"] == "activation_rejected"
    assert exc.value.detail["input"]["reason"] == "Name does not match our records"
    # The username is free again for a new attempt.
    again = MemberActivationService.submit(db, _payload())
    assert again["id"] != result["id"]


def test_admin_list_shows_checks(db, world):
    MemberActivationService.submit(db, _payload())
    page = MemberActivationService.list(db, "pending", 0, 50)
    item = page["items"][0]
    assert page["pending_total"] == 1
    assert item["checks"]["name"] == "match"
    assert item["checks"]["last_paid_month"] == "match"
    assert item["checks"]["conflicts"] == [] and item["checks"]["already_active"] is False
    assert item["record"]["months_paid"] == 2 and item["record"]["last_paid_month"] == "2026-09"
    assert "password_hash" not in item


def test_approve_activates_existing_account(db, world):
    result = MemberActivationService.submit(db, _payload(whatsapp_phone="+966500000009"))
    approved = MemberActivationService.approve(db, _admin(world), result["id"], "Known to me")
    assert approved["status"] == "approved"

    user = db.get(User, world["imported"].id)
    assert user.is_active is True and user.welcome_pending is True
    assert user.username == "mali" and user.phone == "+966500000001"
    assert user.email == "ali@example.org" and user.whatsapp_phone == "+966500000009"
    assert user.member.member_code == "MEM-0001"  # same member, history kept
    assert _login(db, "mali", "Secret@123").id == user.id
    assert db.query(AuditLog).filter_by(action="member_activation_approved").count() == 1
    assert db.query(Notification).filter_by(user_id=user.id).count() == 1

    summary = MemberActivationService.welcome_summary(db, user.id)
    assert summary["show"] and summary["months_paid"] == 2 and summary["total_paid"] == 200
    MemberActivationService.mark_welcome_seen(db, user.id)
    assert MemberActivationService.welcome_summary(db, user.id) == {"show": False}


def test_approving_one_rejects_competing_requests(db, world):
    mine = MemberActivationService.submit(db, _payload())
    impostor = MemberActivationService.submit(
        db, _payload(full_name="Someone Else", phone="+966533333333", email="s@x.org", username="someone"),
    )
    assert MemberActivationService.list(db, "pending", 0, 50)["items"][0]["checks"]["other_pending"] == 1
    MemberActivationService.approve(db, _admin(world), mine["id"])
    other = db.get(MemberActivation, impostor["id"])
    assert other.status == "rejected" and "approved" in other.rejection_reason
    with pytest.raises(HTTPException) as exc:
        MemberActivationService.approve(db, _admin(world), impostor["id"])
    assert exc.value.status_code == 409


def test_reject_needs_a_reason_and_leaves_account_untouched(db, world):
    result = MemberActivationService.submit(db, _payload())
    with pytest.raises(HTTPException):
        MemberActivationService.reject(db, _admin(world), result["id"], "no")
    MemberActivationService.reject(db, _admin(world), result["id"], "This Member ID belongs to someone else")
    user = db.get(User, world["imported"].id)
    assert user.is_active is False and user.username == "mohammed_ali_0001"
    assert json.loads(db.query(AuditLog).filter_by(action="member_activation_rejected").one().new_values)["reason"]


def test_rate_limit_per_ip(db, world):
    for _ in range(mas.SUBMIT_LIMIT):
        with pytest.raises(HTTPException) as exc:
            MemberActivationService.submit(db, _payload(member_code="0099"), source_ip="9.9.9.9")
        assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        MemberActivationService.submit(db, _payload(), source_ip="9.9.9.9")
    assert exc.value.status_code == 429


def test_turned_off_by_setting(db, world, monkeypatch):
    monkeypatch.setattr(mas, "get_setting", lambda db, key: False if key == "self_activation_enabled" else 10)
    with pytest.raises(HTTPException) as exc:
        MemberActivationService.submit(db, _payload())
    assert exc.value.status_code == 403


def test_login_still_works_if_activation_lookup_fails(db, world, monkeypatch):
    """A broken/missing activation table must not turn wrong-password into a server error."""
    original_query = db.query

    def failing_query(*entities, **kw):
        if entities and entities[0] is MemberActivation:
            raise RuntimeError("relation member_activations does not exist")
        return original_query(*entities, **kw)

    monkeypatch.setattr(db, "query", failing_query)
    with pytest.raises(HTTPException) as exc:
        _login(db, "admin1", "wrong-password")
    assert exc.value.status_code == 401
    assert _login(db, "admin1", "Admin@1234").username == "admin1"
