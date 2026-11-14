"""Admins see "not paid yet" months as payable; members' lists are unchanged."""
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import Challan, ChallanStatus, ChallanType, Member, User, UserRole
from app.services import challan_service
from app.services.challan_service import ChallanService


def test_placeholders_payable_only_when_asked(monkeypatch):
    monkeypatch.setattr(challan_service, "today_business", lambda: date(2026, 11, 15))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    u = User(username="m", password_hash="x", role=UserRole.MEMBER, is_active=True)
    db.add(u)
    db.flush()
    m = Member(user_id=u.id, member_code="MEM-1", monthly_amount=1000, join_date=datetime(2026, 8, 1))
    db.add(m)
    db.flush()
    db.add_all([
        Challan(member_id=m.id, type=ChallanType.MONTHLY, month="2026-08", amount=1000, status=ChallanStatus.APPROVED),
        Challan(member_id=m.id, type=ChallanType.MONTHLY, month="2026-09", amount=1000, status=ChallanStatus.PENDING,
                entry_source="import"),  # not paid yet
        Challan(member_id=m.id, type=ChallanType.MONTHLY, month="2026-10", amount=1000, status=ChallanStatus.PENDING,
                proof_path="/p.jpg"),  # waiting for approval
    ])
    db.commit()
    member_view = ChallanService.get_payable_months(db, m.id)
    assert member_view["pending_months"] == [] and member_view["current_month_payable"] is True
    admin_view = ChallanService.get_payable_months(db, m.id, include_unpaid_placeholders=True)
    assert admin_view["pending_months"] == ["2026-09"]
    assert "2026-10" not in admin_view["all_months"] and "2026-08" not in admin_view["all_months"]
    db.close()
