"""Country and city of each member: validation, self-update, admin filters, dashboard counts."""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import Member, User, UserRole
from app.routes import member_routes
from app.routes.activation_routes import MemberActivationCreate
from app.schemas import MemberLocationUpdate, MemberUpdate
from app.schemas.schemas import UserRegisterWithInvite
from app.services import member_activation_service as mas
from app.services.member_activation_service import MemberActivationService
from app.services.member_service import MemberService
from app.services.notification_service import NotificationService
from app.utils.auth import hash_password
from app.utils.countries import country_from_phone, dial_code_digits


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
    monkeypatch.setattr(member_routes, "log_audit", lambda *a, **k: None)
    mas.reset_rate_limit()
    yield
    mas.reset_rate_limit()


@pytest.fixture()
def world(db):
    people = [
        ("aisha", "+971501234567", "AE", "Dubai"),
        ("rahul", "+919876543210", "IN", "Kochi"),
        ("omar", "+966560570553", "AE", "Sharjah"),  # Saudi number, lives in the UAE
        ("newbie", "+447700900123", None, None),
        ("nophone", None, None, None),
    ]
    members = {}
    for i, (name, phone, country, city) in enumerate(people, start=1):
        user = User(username=name, password_hash=hash_password("x"), role=UserRole.MEMBER, is_active=True, phone=phone)
        db.add(user)
        db.flush()
        m = Member(user_id=user.id, member_code=f"MEM-{i:04d}", full_name=name.title(), country=country, city=city)
        db.add(m)
        members[name] = m
    db.commit()
    return members


def _names(result):
    return sorted(m["username"] for m in result["data"])


def test_country_must_be_on_the_phone_list():
    assert MemberLocationUpdate(country=" in ", city="  New   Delhi ").model_dump() == {"country": "IN", "city": "New Delhi"}
    with pytest.raises(ValidationError):
        MemberLocationUpdate(country="FR", city="Paris")
    with pytest.raises(ValidationError):
        MemberUpdate(city="x" * 101)


def test_phone_helpers():
    assert country_from_phone("+971501234567") == "AE"
    assert country_from_phone("+919876543210") == "IN"
    assert country_from_phone("+15551234567") is None  # +1 is shared by the US and Canada
    assert country_from_phone("0501234567") is None
    assert dial_code_digits("+971") == dial_code_digits("971") == dial_code_digits("ae") == "971"
    assert dial_code_digits("+33") is None


def test_member_sets_own_location(db, world):
    user_id = world["newbie"].user_id
    route = member_routes.update_my_location
    with pytest.raises(HTTPException) as exc:
        route(MemberLocationUpdate(country="GB", city=""), {"user_id": user_id, "role": "member"}, db)
    assert exc.value.status_code == 400
    member = route(MemberLocationUpdate(country="gb", city="London"), {"user_id": user_id, "role": "member"}, db)
    assert (member.country, member.city) == ("GB", "London")


def test_admin_update_cannot_clear_location(db, world):
    m = world["aisha"]
    MemberService.update_member(db, m.id, MemberUpdate(country="", city=None))
    db.refresh(m)
    assert (m.country, m.city) == ("AE", "Dubai")
    MemberService.update_member(db, m.id, MemberUpdate(country="QA", city="Doha"))
    db.refresh(m)
    assert (m.country, m.city) == ("QA", "Doha")


def test_filter_by_country(db, world):
    assert _names(MemberService.get_all_members(db, limit=50, country="AE")) == ["aisha", "omar"]
    assert _names(MemberService.get_all_members(db, limit=50, country="none")) == ["newbie", "nophone"]
    with pytest.raises(HTTPException):
        MemberService.get_all_members(db, country="FR")


def test_filter_by_phone_code(db, world):
    assert _names(MemberService.get_all_members(db, limit=50, phone_code="+966")) == ["omar"]
    assert _names(MemberService.get_all_members(db, limit=50, phone_code="IN")) == ["rahul"]
    assert _names(MemberService.get_all_members(db, limit=50, phone_code="other")) == ["nophone"]
    # Both filters together: lives in the UAE with a Saudi number
    assert _names(MemberService.get_all_members(db, limit=50, country="AE", phone_code="966")) == ["omar"]
    with pytest.raises(HTTPException):
        MemberService.get_all_members(db, phone_code="33")


def test_search_finds_phone_and_city(db, world):
    assert _names(MemberService.get_all_members(db, limit=50, search="98765")) == ["rahul"]
    assert _names(MemberService.get_all_members(db, limit=50, search="sharjah")) == ["omar"]


def test_list_returns_country_and_city(db, world):
    row = next(r for r in MemberService.get_all_members(db, limit=50)["data"] if r["username"] == "rahul")
    assert (row["country"], row["city"]) == ("IN", "Kochi")


def test_country_breakdown(db, world):
    out = MemberService.get_country_breakdown(db)
    assert out["countries"][0] == {"country": "AE", "name": "United Arab Emirates", "count": 2}
    assert {c["country"] for c in out["countries"]} == {"AE", "IN"}
    assert out["not_set"] == 2 and out["total"] == 5


def test_registration_accepts_location():
    reg = UserRegisterWithInvite(invite_code="INV-1", username="abc", password="Secret@123", country="om", city="Muscat")
    assert (reg.country, reg.city) == ("OM", "Muscat")
    with pytest.raises(ValidationError):
        UserRegisterWithInvite(invite_code="INV-1", username="abc", password="Secret@123", country="XX")


def test_activation_carries_location_to_member(db, monkeypatch):
    monkeypatch.setattr(MemberActivationService, "is_enabled", staticmethod(lambda db: True))
    admin = User(username="admin1", password_hash=hash_password("x"), role=UserRole.ADMIN, is_active=True)
    imported = User(username="imp", password_hash=hash_password("x"), role=UserRole.MEMBER, is_active=False)
    db.add_all([admin, imported])
    db.flush()
    member = Member(user_id=imported.id, member_code="MEM-0100", full_name="Imported Person")
    db.add(member)
    db.commit()
    payload = MemberActivationCreate(member_code="0100", full_name="Imported Person", phone="+97455512345",
                                     email="p@example.org", username="imported1", password="Secret@123",
                                     country="QA", city="Doha")
    created = MemberActivationService.submit(db, payload)
    with pytest.raises(HTTPException):
        MemberActivationService.submit(db, payload.model_copy(update={"country": "XX"}))
    MemberActivationService.approve(db, {"user_id": admin.id, "role": "admin"}, created["id"])
    db.refresh(member)
    assert (member.country, member.city) == ("QA", "Doha")


def test_filter_by_phone_digits(db, world):
    world["aisha"].user.whatsapp_phone = "+971 55 999 8888"
    db.commit()
    assert _names(MemberService.get_all_members(db, limit=50, phone="050 123 4567")) == ["aisha"]
    assert _names(MemberService.get_all_members(db, limit=50, phone="+91-98765")) == ["rahul"]
    assert _names(MemberService.get_all_members(db, limit=50, phone="559998888")) == ["aisha"]  # WhatsApp
    with pytest.raises(HTTPException):
        MemberService.get_all_members(db, phone="abc")


def test_filter_registered(db, world):
    world["newbie"].user.is_active = False
    world["nophone"].user.is_active = False
    db.commit()
    assert _names(MemberService.get_all_members(db, limit=50, registered="no")) == ["newbie", "nophone"]
    assert _names(MemberService.get_all_members(db, limit=50, registered="yes")) == ["aisha", "omar", "rahul"]
    assert _names(MemberService.get_all_members(db, limit=50, registered="no", country="none")) == ["newbie", "nophone"]
    assert MemberService.get_members_summary(db)["registered_members"] == 3
    with pytest.raises(HTTPException):
        MemberService.get_all_members(db, registered="maybe")
