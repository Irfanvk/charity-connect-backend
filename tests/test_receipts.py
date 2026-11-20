"""Checking a payment against the bank when approving, and the receipt that follows."""
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import BulkChallanGroup, Challan, ChallanStatus, ChallanType, Member, User, UserRole
from app.routes import receipt_routes
from app.services import receipt_service as rs
from app.services import verification_service as vs
from app.services.verification_service import Verification


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, username="admin1", full_name="Admin One", password_hash="x", role=UserRole.ADMIN),
        User(id=2, username="amina", full_name="Amina Kutty", password_hash="x", role=UserRole.MEMBER),
        User(id=3, username="basil", password_hash="x", role=UserRole.MEMBER),
        Member(id=10, user_id=2, member_code="MEM-0001", full_name="Amina Kutty", monthly_amount=500),
        Member(id=11, user_id=3, member_code="MEM-0002", monthly_amount=500),
    ])
    session.commit()
    yield session
    session.close()


def _challan(db, member_id=10, month="2026-09", **over):
    data = dict(member_id=member_id, type=ChallanType.MONTHLY, month=month, amount=500,
                status=ChallanStatus.PENDING, entry_source="self", proof_path="uploads/proofs/p.png",
                challan_no="PG-2627-0001", created_at=datetime(2026, 11, 1))
    data.update(over)
    c = Challan(**data)
    db.add(c)
    db.commit()
    return c


def test_verification_is_saved(db):
    c = _challan(db)
    vs.apply(db, Verification(received_on=date(2026, 11, 2), transaction_ref=" UTR123 ", received_amount=500,
                              payment_method="UPI", bank_record_file_id="https://res.cloudinary.com/x/image/private/v1/a.png"), [c])
    assert (c.received_on, c.transaction_ref, c.received_amount, c.payment_method) == (date(2026, 11, 2), "UTR123", 500, "upi")
    assert c.bank_record_path.endswith("a.png")


def test_reused_reference_needs_confirmation(db):
    _challan(db, transaction_ref="UTR123", status=ChallanStatus.APPROVED)
    c = _challan(db, member_id=11, month="2026-10", challan_no="PG-2627-0002")
    with pytest.raises(HTTPException) as exc:
        vs.apply(db, Verification(transaction_ref="utr123"), [c])
    assert exc.value.status_code == 409 and "PG-2627-0001" in exc.value.detail["message"]
    vs.apply(db, Verification(transaction_ref="utr123", confirm_duplicate_ref=True), [c])
    assert c.transaction_ref == "utr123"


@pytest.mark.parametrize("fields", [
    {"received_amount": 400},                                  # different amount, no note
    {"received_on": date(2999, 1, 1)},                         # future date
    {"bank_record_file_id": "file:///etc/passwd"},             # not an uploaded file
])
def test_verification_refusals(db, fields):
    c = _challan(db)
    with pytest.raises(HTTPException) as exc:
        vs.apply(db, Verification(**fields), [c])
    assert exc.value.status_code == 400


def test_different_amount_with_note_is_fine(db):
    c = _challan(db)
    vs.apply(db, Verification(received_amount=450, verification_note="Bank charge of 50 deducted"), [c])
    assert c.received_amount == 450 and c.verification_note.startswith("Bank charge")


def test_receipt_for_single_and_bulk_payment(db):
    c = _challan(db, status=ChallanStatus.APPROVED, approved_by_admin_id=1, approved_at=datetime(2026, 11, 3, 5, 0),
                 received_on=date(2026, 11, 2), transaction_ref="UTR9")
    r = rs.for_challan(db, c)
    assert r["number"] == "PG-2627-0001" and r["valid"] and r["approved_by"] == "AD1"  # a code, never the name
    assert r["months"] == ["2026-09"] and r["received_on"] == "2026-11-02" and r["verify_url"].endswith(r["token"])

    group = BulkChallanGroup(bulk_group_id="BCH-0001", challan_no="PG-2627-0005", member_id=10, amount_per_month=500,
                             total_amount=1000, proof_file_id="uploads/p.png", status="approved",
                             months_list='["2026-10","2026-11"]', challan_ids_list="[]", created_by_user_id=2,
                             approved_at=datetime(2026, 11, 4))
    db.add(group)
    db.commit()
    rows = [_challan(db, month=m, bulk_group_id="BCH-0001", challan_no="PG-2627-0005", status=ChallanStatus.APPROVED)
            for m in ("2026-10", "2026-11")]
    br = rs.for_challan(db, rows[0])        # a month of a bulk payment gives the whole payment's receipt
    assert br["number"] == "PG-2627-0005" and br["months"] == ["2026-10", "2026-11"] and br["amount"] == 1000


def test_public_page_is_signed_and_shortens_the_name(db):
    c = _challan(db, status=ChallanStatus.APPROVED, approved_at=datetime(2026, 11, 3))
    token = rs.token_for("c", c.id)
    view = rs.public_view(db, token)
    assert view["valid"] and view["member_name"] == "Amina K." and "transaction_ref" not in view
    for bad in (f"c{c.id}-0000000000", f"c{c.id + 1}-{token.split('-', 1)[1]}", "nonsense"):
        with pytest.raises(HTTPException):
            rs.public_view(db, bad)
    c.status = ChallanStatus.PENDING          # reverted: the link now says it is not valid
    db.commit()
    assert rs.public_view(db, token)["valid"] is False


def test_receipt_routes_only_for_owner_or_admin_and_after_approval(db):
    c = _challan(db)
    with pytest.raises(HTTPException) as exc:
        receipt_routes.challan_receipt(c.id, {"user_id": 2, "role": "member"}, db)
    assert exc.value.status_code == 409                    # not approved yet
    c.status = ChallanStatus.APPROVED
    db.commit()
    assert receipt_routes.challan_receipt(c.id, {"user_id": 2, "role": "member"}, db)["number"] == "PG-2627-0001"
    assert receipt_routes.challan_receipt(c.id, {"user_id": 1, "role": "admin"}, db)["valid"]
    with pytest.raises(HTTPException) as exc:
        receipt_routes.challan_receipt(c.id, {"user_id": 3, "role": "member"}, db)
    assert exc.value.status_code == 403


def test_receipt_shows_admin_code_not_name(db):
    from app.utils.admin_codes import code_from

    assert code_from("MEM-0012", 5) == "A12" and code_from(None, 3) == "AD3" and code_from("TEST-0001", 9) == "AD9"
    db.add(Member(id=12, user_id=1, member_code="MEM-0012", monthly_amount=500))
    db.commit()
    c = _challan(db, status=ChallanStatus.APPROVED, approved_by_admin_id=1, approved_at=datetime(2026, 11, 3))
    assert rs.for_challan(db, c)["approved_by"] == "A12"


def test_links_never_use_a_hosting_address(monkeypatch):
    from app.config import settings
    from app.utils.invite_share import _normalize_base_url

    monkeypatch.setattr(settings, "PUBLIC_SITE_URL", "https://poyyathabailgcc.com")
    for hosting in ("https://poyyathabailgcc.netlify.app", "http://localhost:5173", ""):
        monkeypatch.setattr(settings, "FRONTEND_BASE_URL", hosting)
        assert _normalize_base_url() == "https://poyyathabailgcc.com"
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://pay.example.org/")
    assert _normalize_base_url() == "https://pay.example.org"
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://poyyathabailgcc.netlify.app")
    assert rs.verify_url("c1-x") == "https://poyyathabailgcc.com/r/c1-x"


def test_receipts_list_search_and_filters(db):
    db.add(Member(id=12, user_id=1, member_code="MEM-0012", monthly_amount=500))
    _challan(db, status=ChallanStatus.APPROVED, approved_by_admin_id=1, received_on=date(2026, 11, 2),
             transaction_ref="UTR555", payment_method="upi", approved_at=datetime(2026, 11, 3))
    _challan(db, member_id=11, month="2026-10", challan_no="PG-2627-0002", status=ChallanStatus.APPROVED,
             received_on=date(2026, 10, 5), payment_method="cash", approved_at=datetime(2026, 10, 6))
    _challan(db, month="2026-12", challan_no="PG-2627-0003")              # pending: no receipt
    out = rs.list_receipts(db)
    assert out["total"] == 2 and out["total_amount"] == 1000 and out["items"][0]["number"] == "PG-2627-0001"
    assert out["items"][0]["checked_by"] == "A12" and out["checked_by_codes"] == ["A12"]
    assert [r["number"] for r in rs.list_receipts(db, search="utr555")["items"]] == ["PG-2627-0001"]
    assert [r["number"] for r in rs.list_receipts(db, method="cash")["items"]] == ["PG-2627-0002"]
    assert rs.list_receipts(db, date_from=date(2026, 11, 1))["total"] == 1
    assert rs.list_receipts(db, checked_by="a12")["total"] == 1


def test_my_statement_year_and_history(db, monkeypatch):
    from app.services import report_service

    monkeypatch.setattr(report_service, "today_business", lambda: date(2026, 11, 20))
    member = db.get(Member, 10)
    member.join_date = datetime(2026, 9, 1)
    db.commit()
    _challan(db, month="2026-09", status=ChallanStatus.APPROVED, approved_at=datetime(2026, 9, 20), created_by_user_id=2)
    _challan(db, month="2026-10", challan_no="PG-2627-0004", created_by_user_id=2)         # waiting (proof sent)
    _challan(db, month="2026-11", challan_no=None, proof_path=None, created_by_user_id=None)  # imported "not paid yet"
    out = report_service.my_statement(db, 2)
    assert out["label"] == "2026-2027" and out["years"] == [2026]
    states = {r["month"]: r["state"] for r in out["months"]}
    assert states["2026-09"] == "paid" and states["2026-10"] == "waiting" and states["2026-11"] == "not_paid"
    assert "2026-08" not in states                       # before joining
    numbers = [h["number"] for h in out["history"]]
    assert numbers == ["PG-2627-0004", "PG-2627-0001"]   # the imported row is not a payment
    assert out["history"][1]["receipt"] == {"challan_id": out["history"][1]["receipt"]["challan_id"]}
    with pytest.raises(HTTPException):
        report_service.my_statement(db, 1)               # admin1 has no member record here
