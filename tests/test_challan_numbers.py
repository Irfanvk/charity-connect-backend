"""Real payment numbers (PG-2526-0001) and paying several open months with one proof."""
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import (
    BulkChallanGroup, Challan, ChallanStatus, ChallanType, Member, User, UserRole,
)
from app.services import challan_numbers as cn
from app.services.challan_state import is_submitted
from app.services.pay_together import pay_together


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=2, username="amina", password_hash="x", role=UserRole.MEMBER),
        User(id=3, username="basil", password_hash="x", role=UserRole.MEMBER),
        Member(id=10, user_id=2, member_code="MEM-0001", full_name="Amina", monthly_amount=500),
        Member(id=11, user_id=3, member_code="MEM-0002", full_name="Basil", monthly_amount=300),
    ])
    session.commit()
    monkeypatch.setattr("app.services.notification_service.NotificationService.notify_admins_proof_uploaded",
                        staticmethod(lambda *a, **k: None))
    yield session
    session.close()


def test_numbers_run_per_calendar_year(db):
    assert cn.next_number(db, date(2026, 7, 31)) == "PG-2026-0001"
    assert cn.next_number(db, date(2026, 12, 31)) == "PG-2026-0002"
    assert cn.next_number(db, date(2027, 1, 1)) == "PG-2027-0001"   # new year starts at 0001
    assert cn.next_number(db, date(2027, 8, 15)) == "PG-2027-0002"


def test_prefix_setting(db, monkeypatch):
    monkeypatch.setattr("app.services.settings_service.get_setting",
                        lambda db, key: "gcc-1!" if key == "challan_number_prefix" else None)
    assert cn.next_number(db, date(2026, 11, 1)) == "GCC1-2026-0001"


def test_display_number_falls_back_to_id():
    assert cn.display_number(Challan(id=19561)) == "CH-19561"
    assert cn.display_number(Challan(id=5, challan_no="PG-2627-0007")) == "PG-2627-0007"


def _open(db, member_id, month, **over):
    data = dict(member_id=member_id, type=ChallanType.MONTHLY, month=month, amount=500,
                status=ChallanStatus.GENERATED, entry_source="self", created_by_user_id=2,
                created_at=datetime(2026, 11, 1))
    data.update(over)
    c = Challan(**data)
    db.add(c)
    db.commit()
    return c


ME = {"user_id": 2, "role": "member"}


def test_pay_together_makes_one_bulk_payment(db):
    a = _open(db, 10, "2026-09", challan_no="PG-2627-0003")
    b = _open(db, 10, "2026-10", challan_no="PG-2627-0004")
    placeholder = _open(db, 10, "2026-04", status=ChallanStatus.PENDING, entry_source="import",
                        created_by_user_id=None, amount=400)   # old imported "not paid yet" row
    out = pay_together(db, ME, [a.id, b.id, placeholder.id], "uploads/proof.jpg", "One transfer")
    assert out["months"] == ["2026-04", "2026-09", "2026-10"]
    assert out["total_amount"] == 1500        # the imported row follows the current fee
    assert out["challan_no"].startswith("PG-")
    group = db.query(BulkChallanGroup).one()
    assert group.challan_no == out["challan_no"] and group.proof_file_id == "uploads/proof.jpg"
    for c in (a, b, placeholder):
        db.refresh(c)
        assert c.bulk_group_id == group.bulk_group_id and c.challan_no == out["challan_no"]
        assert c.status == ChallanStatus.PENDING and is_submitted(c)


def test_pay_together_keeps_a_shared_number(db):
    a = _open(db, 10, "2026-09", challan_no="PG-2627-0009")
    b = _open(db, 10, "2026-10", challan_no="PG-2627-0009")   # started with "one proof, upload later"
    assert pay_together(db, ME, [a.id, b.id], "uploads/p.jpg")["challan_no"] == "PG-2627-0009"


@pytest.mark.parametrize("case", ["other_member", "already_sent", "one_month", "no_proof", "campaign"])
def test_pay_together_refuses(db, case):
    a = _open(db, 10, "2026-09")
    b = {
        "other_member": lambda: _open(db, 11, "2026-10", created_by_user_id=3),
        "already_sent": lambda: _open(db, 10, "2026-10", status=ChallanStatus.PENDING, proof_path="x.jpg"),
        "one_month": lambda: None,
        "no_proof": lambda: _open(db, 10, "2026-10"),
        "campaign": lambda: _open(db, 10, None, type=ChallanType.CAMPAIGN),
    }[case]()
    ids = [a.id] + ([b.id] if b else [])
    with pytest.raises(HTTPException) as exc:
        pay_together(db, ME, ids, "" if case == "no_proof" else "uploads/p.jpg")
    assert exc.value.status_code in (400, 403, 409)
    assert db.query(BulkChallanGroup).count() == 0
