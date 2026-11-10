"""Profile-photo requests: status casing, one pending request per member, temporary storage."""
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base
from app.models.models import Member, MemberRequest, RequestStatus, RequestType, User, UserRole
from app.services import request_service as request_service_module
from app.services.notification_service import NotificationService
from app.services.request_service import RequestService
from app.utils.file_handler import is_pending_avatar_url

FOLDER = settings.CLOUDINARY_FOLDER


def _pending(n):
    return f"https://res.cloudinary.com/demo/image/upload/v1/{FOLDER}/avatars_pending/img{n}.jpg"


def _permanent(n):
    return f"https://res.cloudinary.com/demo/image/upload/v2/{FOLDER}/avatars/img{n}.jpg"


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


@pytest.fixture()
def storage(monkeypatch):
    """Record storage calls instead of talking to Cloudinary."""
    calls = {"promoted": [], "discarded": [], "deleted": []}

    def promote(url):
        calls["promoted"].append(url)
        return url.replace("/avatars_pending/", "/avatars/").replace("/v1/", "/v2/")

    def discard(url):
        if is_pending_avatar_url(url):
            calls["discarded"].append(url)
            return True
        return False

    monkeypatch.setattr(request_service_module, "promote_pending_avatar", promote)
    monkeypatch.setattr(request_service_module, "discard_pending_avatar", discard)
    monkeypatch.setattr(request_service_module, "delete_file", lambda url: calls["deleted"].append(url))
    return calls


def _user(db, name, role):
    u = User(username=name, password_hash="x", role=role, full_name=name.title())
    db.add(u)
    db.flush()
    return u


def _ctx(user):
    return {"user_id": user.id, "role": user.role.value, "username": user.username}


@pytest.fixture()
def world(db):
    admin = _user(db, "admin1", UserRole.ADMIN)
    member_user = _user(db, "kmhanief", UserRole.MEMBER)
    member_user.avatar_url = _permanent(0)
    db.add(Member(user_id=member_user.id, member_code="MEM-0200", full_name="Km Hanief"))
    db.commit()
    return {"admin": admin, "member": member_user}


def _photo_request(db, user, url):
    return RequestService.create_request(
        db,
        _ctx(user),
        RequestType.PROFILE_UPDATE,
        "Profile photo update request",
        "Please update my profile photo.",
        None,
        {"avatar_url": url},
    )


def test_status_is_serialized_lowercase(db, world, storage):
    created = _photo_request(db, world["member"], _pending(1))
    assert created["status"] == "pending"

    page = RequestService.admin_list_requests(db, "pending", None, None, 0, 50)
    assert [i["status"] for i in page["items"]] == ["pending"]
    # Upper-case filter from older clients still works.
    assert RequestService.admin_list_requests(db, "PENDING", None, None, 0, 50)["total"] == 1


def test_repeated_photo_requests_collapse_into_one(db, world, storage):
    first = _photo_request(db, world["member"], _pending(1))
    second = _photo_request(db, world["member"], _pending(2))
    third = _photo_request(db, world["member"], _pending(3))

    assert first["id"] == second["id"] == third["id"]
    assert db.query(MemberRequest).count() == 1
    assert json.loads(third["requested_changes"]) == {"avatar_url": _pending(3)}
    # Superseded temporary uploads are deleted.
    assert storage["discarded"] == [_pending(1), _pending(2)]


def test_removal_request_also_reuses_pending_photo_request(db, world, storage):
    first = _photo_request(db, world["member"], _pending(1))
    removal = _photo_request(db, world["member"], None)
    assert removal["id"] == first["id"]
    assert json.loads(removal["requested_changes"]) == {"avatar_url": None}
    assert storage["discarded"] == [_pending(1)]


def test_resolved_photo_request_does_not_block_a_new_one(db, world, storage):
    first = _photo_request(db, world["member"], _pending(1))
    RequestService.reject_request(db, _ctx(world["admin"]), first["id"], "Photo is blurry")
    second = _photo_request(db, world["member"], _pending(2))
    assert second["id"] != first["id"]


def test_non_photo_profile_requests_are_not_merged(db, world, storage):
    photo = _photo_request(db, world["member"], _pending(1))
    other = RequestService.create_request(
        db, _ctx(world["member"]), RequestType.PROFILE_UPDATE, "Phone", "Update my phone",
        None, {"phone": "+966500000000"},
    )
    assert other["id"] != photo["id"]


def test_arbitrary_avatar_url_is_rejected(db, world, storage):
    with pytest.raises(HTTPException) as exc:
        _photo_request(db, world["member"], "https://evil.example.com/x.jpg")
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException):
        _photo_request(db, world["member"], _permanent(9))


def test_approve_promotes_temp_photo_and_deletes_old_avatar(db, world, storage):
    req = _photo_request(db, world["member"], _pending(1))
    approved = RequestService.approve_request(db, _ctx(world["admin"]), req["id"])

    assert approved["status"] == "approved"
    assert storage["promoted"] == [_pending(1)]
    db.refresh(world["member"])
    assert world["member"].avatar_url == _permanent(1)
    # Stored request now points at the permanent file so it still renders.
    assert json.loads(approved["requested_changes"]) == {"avatar_url": _permanent(1)}
    assert storage["deleted"] == [_permanent(0)]


def test_failed_promotion_leaves_request_pending(db, world, monkeypatch, storage):
    def boom(url):
        raise RuntimeError("Cloudinary down")

    monkeypatch.setattr(request_service_module, "promote_pending_avatar", boom)
    req = _photo_request(db, world["member"], _pending(1))
    with pytest.raises(HTTPException) as exc:
        RequestService.approve_request(db, _ctx(world["admin"]), req["id"])
    assert exc.value.status_code == 502
    db.rollback()
    item = db.get(MemberRequest, req["id"])
    assert item.status == RequestStatus.PENDING
    db.refresh(world["member"])
    assert world["member"].avatar_url == _permanent(0)
    assert storage["deleted"] == []


def test_reject_discards_temp_photo(db, world, storage):
    req = _photo_request(db, world["member"], _pending(1))
    RequestService.reject_request(db, _ctx(world["admin"]), req["id"], "Not appropriate")
    assert storage["discarded"] == [_pending(1)]
    db.refresh(world["member"])
    assert world["member"].avatar_url == _permanent(0)


def test_cancel_discards_temp_photo(db, world, storage):
    req = _photo_request(db, world["member"], _pending(1))
    RequestService.delete_request(db, _ctx(world["member"]), req["id"])
    assert storage["discarded"] == [_pending(1)]
    assert db.query(MemberRequest).count() == 0


def test_pending_url_detection():
    assert is_pending_avatar_url(_pending(1))
    assert not is_pending_avatar_url(_permanent(1))
    assert is_pending_avatar_url("/uploads/avatars_pending/abc.jpg")
    assert not is_pending_avatar_url("/uploads/avatars/abc.jpg")
    assert not is_pending_avatar_url(None)
