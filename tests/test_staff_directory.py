"""Who is who: staff see the committee with codes; members cannot."""
import pytest
from fastapi import HTTPException

import app.services  # noqa: F401  (load order)
from app.models.models import Member, User, UserRole
from app.utils.auth import get_current_staff
from tests.test_separation_of_duties import _ctx, _user, admin_router, db, stub_dispatch, world  # noqa: F401


def test_staff_directory_lists_codes(db, world):
    ex = _user(db, "exec1", UserRole.EXECUTIVE)
    db.add(Member(user_id=ex.id, member_code="MEM-0007", full_name="Exec Person"))
    old = _user(db, "gone", UserRole.ADMIN)
    old.is_active = False
    db.commit()
    out = admin_router.staff_directory(_ctx(world["admin1"]), db)
    by_name = {r["name"]: r for r in out["items"]}
    assert "Gone" not in by_name  # inactive people are left out
    assert by_name["Exec Person"]["code"] == "E7" and by_name["Exec Person"]["role"] == "executive"
    assert by_name["Admin1"]["is_you"] is True
    assert [r["role"] for r in out["items"]][0] == "superadmin"
    assert all(r["role"] != "member" for r in out["items"])


def test_members_cannot_open_it():
    with pytest.raises(HTTPException) as e:
        get_current_staff({"user_id": 1, "role": "member"})
    assert e.value.status_code == 403
