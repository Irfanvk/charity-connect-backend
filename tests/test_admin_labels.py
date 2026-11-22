"""Who did something: staff see "admin (A12)" / "executive (E12)"; members see "the committee"."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import Member, Notification, User, UserRole
from app.services.notification_service import NotificationService
from app.utils.admin_codes import (COMMITTEE, actor_label, actor_label_for, actor_labels, set_viewer,
                                   viewer_is_staff, viewing_as)


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


def _people(db):
    admin = User(username="irfan", password_hash="x", role=UserRole.ADMIN, full_name="Irfan Admin")
    boss = User(username="boss", password_hash="x", role=UserRole.SUPERADMIN, full_name="Big Boss")
    exe = User(username="exec", password_hash="x", role=UserRole.EXECUTIVE, full_name="Exe Cutive")
    mem = User(username="mem", password_hash="x", role=UserRole.MEMBER, full_name="Mem Ber")
    db.add_all([admin, boss, exe, mem])
    db.flush()
    db.add_all([Member(user_id=admin.id, member_code="MEM-0012", full_name="Irfan Admin"),
                Member(user_id=exe.id, member_code="MEM-0007", full_name="Exe Cutive"),
                Member(user_id=mem.id, member_code="MEM-0050", full_name="Mem Ber")])
    db.commit()
    return admin, boss, exe, mem


def test_staff_see_codes(db):
    admin, boss, exe, mem = _people(db)
    with viewing_as(True):
        assert actor_label(admin) == "admin (A12)"
        assert actor_label(boss) == f"admin (AD{boss.id})"  # no member record
        assert actor_label(exe) == "executive (E7)"
        assert actor_label(mem) == "Mem Ber"  # members keep their own name
        assert admin.actor_label == "admin (A12)"
        assert actor_labels(db, [admin.id, mem.id, None]) == {admin.id: "admin (A12)", mem.id: "Mem Ber"}


def test_members_see_the_committee(db):
    admin, boss, exe, mem = _people(db)
    with viewing_as(False):
        assert {actor_label(u) for u in (admin, boss, exe)} == {COMMITTEE}
        assert actor_label(mem) == "Mem Ber"
    assert actor_label(admin) == COMMITTEE  # nobody set the viewer: the safe wording
    assert actor_label(admin, staff=True) == "admin (A12)"  # explicit override
    assert actor_label_for(db, None) is None


def test_viewer_comes_from_role():
    with viewing_as(False):
        set_viewer("executive")
        assert viewer_is_staff()
        set_viewer("member")
        assert not viewer_is_staff()


def test_done_by_sentence(db):
    admin, _, _, _ = _people(db)
    assert NotificationService._done_by(db, "rejected", admin.id) == " Rejected by the committee."
    assert NotificationService._done_by(db, "reverted", admin.id, staff=True) == " Moved back by admin (A12)."
    assert NotificationService._done_by(db, "approved", None) == ""


def test_excused_decision_tells_member_the_committee(db):
    from app.models.models import ExcusedMonth
    from app.services import seasonal

    admin, _, _, mem = _people(db)
    member = db.query(Member).filter(Member.user_id == mem.id).one()
    e = ExcusedMonth(member_id=member.id, month="2026-05", status=seasonal.REQUESTED, reason="no work",
                     requested_by_user_id=mem.id)
    db.add(e)
    db.commit()
    with viewing_as(True):  # an admin decides; the member's notification still says "the committee"
        seasonal.decide_request(db, member, e.id, False, "please pay", admin.id)
        assert seasonal.overview(db, member)["excused"][0]["decided_by"] == "admin (A12)"
    note = db.query(Notification).filter(Notification.user_id == mem.id).one()
    assert "by the committee" in note.message and "A12" not in note.message and "Irfan" not in note.message
    with viewing_as(False):
        assert seasonal.overview(db, member)["excused"][0]["decided_by"] == COMMITTEE
