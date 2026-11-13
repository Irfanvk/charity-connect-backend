"""Where "Auto" payable months start: the member's join month, or Aug 2024 when unknown."""
from datetime import datetime

import pytest

from tests.test_separation_of_duties import db, world  # noqa: F401
from app.services import challan_service as cs
from app.services.challan_service import ChallanService


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(cs, "today_business", lambda: datetime(2026, 11, 13).date())
    monkeypatch.setattr(cs, "get_setting", lambda db, key: 3)


def _first_month(db, member, join_date):
    member.join_date = join_date
    db.commit()
    return ChallanService.get_payable_months(db, member.id)["all_months"][0]


def _member(world):
    return next(iter(world["members"].values()))


def test_starts_from_join_month(db, world):
    assert _first_month(db, _member(world), datetime(2025, 3, 10)) == "2025-03"


def test_join_before_platform_start_uses_aug_2024(db, world):
    assert _first_month(db, _member(world), datetime(2023, 1, 1)) == "2024-08"


def test_no_join_date_uses_aug_2024(db, world):
    assert _first_month(db, _member(world), None) == "2024-08"


def test_join_this_month_starts_this_month(db, world):
    assert _first_month(db, _member(world), datetime(2026, 11, 2)) == "2026-11"
