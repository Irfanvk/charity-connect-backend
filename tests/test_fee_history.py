"""Monthly fee history: a change starts next month; each month keeps the fee that applied then."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import Challan, ChallanStatus, ChallanType, Member, MemberFee, User, UserRole
from app.services import fee_history as fh
from app.services.challan_state import sync_unpaid_monthly_amounts


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, username="admin", password_hash="x", role=UserRole.ADMIN),
        User(id=2, username="amina", password_hash="x", role=UserRole.MEMBER),
        Member(id=10, user_id=2, member_code="MEM-0001", monthly_amount=300, join_date=datetime(2025, 3, 10)),
    ])
    session.commit()
    session.month = {"now": "2026-01"}
    monkeypatch.setattr(fh, "current_month_business", lambda: session.month["now"])
    yield session
    session.close()


def _change(db, new):
    """What the member edit does: put the new amount on the member, then record the change."""
    m = db.get(Member, 10)
    old = m.monthly_amount
    m.monthly_amount = new
    fh.record_change(db, m, old, new, actor_id=1)
    db.commit()
    return m


def test_no_history_means_todays_fee_for_every_month(db):
    m = db.get(Member, 10)
    assert fh.fee_for(db, m, "2024-09") == 300 and fh.fee_for(db, m, "2027-01") == 300
    assert fh.history(db, m) == [{"amount": 300.0, "effective_from": "2025-03", "source": "start",
                                  "changed_by": None, "note": None, "created_at": None}]


def test_change_starts_next_month(db, staff_viewer):
    m = _change(db, 500)
    assert [(r.effective_from, r.amount, r.source) for r in db.query(MemberFee).order_by(MemberFee.id)] == [
        ("2025-03", 300, "start"), ("2026-02", 500, "admin")]
    assert m.monthly_amount == 300                  # this month keeps today's fee
    assert fh.fee_for(db, m, "2026-01") == 300      # this month: the old fee
    assert fh.fee_for(db, m, "2026-02") == 500      # from next month: the new fee
    assert fh.fee_for(db, m, "2024-08") == 300      # before the start: the first fee
    assert fh.upcoming(db, m) == {"amount": 500, "effective_from": "2026-02"}
    assert fh.history(db, m)[-1]["changed_by"] == "admin (AD1)"


def test_waiting_change_starts_by_itself_next_month(db):
    m = _change(db, 500)
    assert fh.apply_due_changes(db) == 0            # still January
    db.month["now"] = "2026-02"
    assert fh.apply_due_changes(db) == 1
    db.refresh(m)
    assert m.monthly_amount == 500 and fh.upcoming(db, m) is None
    assert fh.apply_due_changes(db) == 0            # nothing more to do


def test_changing_again_in_the_same_month_replaces_or_cancels(db):
    _change(db, 500)
    m = _change(db, 450)
    assert fh.fee_for(db, m, "2026-02") == 450 and [h["amount"] for h in fh.history(db, m)] == [300, 450]
    m = _change(db, 300)                            # back to today's fee: no change waits any more
    assert fh.fee_for(db, m, "2026-02") == 300 and fh.upcoming(db, m) is None


def test_unpaid_months_follow_their_own_months_fee(db):
    def unpaid(month):
        c = Challan(member_id=10, type=ChallanType.MONTHLY, month=month, amount=300, status=ChallanStatus.GENERATED,
                    entry_source="self", created_by_user_id=2)
        db.add(c)
        return c
    old, current, ahead = unpaid("2025-11"), unpaid("2026-01"), unpaid("2026-03")
    paid = Challan(member_id=10, type=ChallanType.MONTHLY, month="2026-02", amount=300, status=ChallanStatus.APPROVED)
    db.add(paid)
    db.commit()
    m = _change(db, 500)
    sync_unpaid_monthly_amounts(db, m)
    db.commit()
    assert (old.amount, current.amount, ahead.amount, paid.amount) == (300, 300, 500, 300)


def test_fee_book_for_reports_and_varies(db):
    m = _change(db, 500)
    book = fh.FeeBook(db, [m])
    assert [book.fee(m, mo) for mo in ("2025-08", "2026-01", "2026-02", "2026-07")] == [300, 300, 500, 500]
    assert book.varies(10, "2025-08", "2026-07") is True
    assert book.varies(10, "2026-02", "2026-07") is False


def test_new_payments_use_the_months_fee(db):
    from app.services.bulk_rules import monthly_amount_for

    m = _change(db, 500)
    assert monthly_amount_for(m, None, "self", "2026-01", db) == 300
    assert monthly_amount_for(m, None, "self", "2026-03", db) == 500
    assert monthly_amount_for(m, 999, "admin", "2025-12", db) == 999   # an admin's own amount


def test_statement_shows_each_months_fee(db, monkeypatch):
    from app.services import report_service

    monkeypatch.setattr(report_service, "today_business", lambda: datetime(2026, 1, 20).date())
    _change(db, 500)
    rows = {r["month"]: r["amount"] for r in report_service.member_statement(db, 10, "2025-11", "2026-03")["months"]}
    assert rows == {"2025-11": 300, "2025-12": 300, "2026-01": 300, "2026-02": 500, "2026-03": 500}
