"""Payment proofs: private storage, names after the payment, reuse warnings, short-lived links."""
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import BulkChallanGroup, Challan, ChallanStatus, ChallanType, Member, ProofFile, User, UserRole
from app.services import proof_service
from app.utils import file_handler as fh


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, username="admin", password_hash="x", role=UserRole.ADMIN),
        User(id=2, username="amina", password_hash="x", role=UserRole.MEMBER),
        User(id=3, username="basil", password_hash="x", role=UserRole.MEMBER),
        Member(id=10, user_id=2, member_code="MEM-0001", monthly_amount=500),
        Member(id=11, user_id=3, member_code="MEM-0002", monthly_amount=500),
    ])
    session.commit()
    saved = []

    def fake_save(content, subfolder, filename, tags=None, name_hint=None, private=False):
        saved.append({"name_hint": name_hint, "private": private, "subfolder": subfolder})
        return f"https://res.cloudinary.com/demo/image/private/v1/cc/{subfolder}/{name_hint}-{len(saved)}.png"

    monkeypatch.setattr(proof_service, "save_file", fake_save)
    session.saved = saved
    yield session
    session.close()


def _challan(db, member_id, month, **over):
    data = dict(member_id=member_id, type=ChallanType.MONTHLY, month=month, amount=500,
                status=ChallanStatus.GENERATED, entry_source="self", created_by_user_id=2,
                created_at=datetime(2026, 11, 1))
    data.update(over)
    c = Challan(**data)
    db.add(c)
    db.commit()
    return c


def test_names_and_privacy(db):
    assert proof_service.member_hint(db, 2).startswith("MEM-0001-")
    ref, sha = proof_service.store_proof(db, b"image", "a.png", user_id=2, name_hint="PG-2627-0001")
    assert db.saved[-1] == {"name_hint": "PG-2627-0001", "private": True, "subfolder": "proofs"}
    assert db.query(ProofFile).filter_by(ref=ref).one().sha256 == sha == fh.file_sha256(b"image")
    assert fh.safe_name("PG 2627/0001") == "PG-2627-0001"


def test_same_file_on_another_payment_is_flagged(db):
    first = _challan(db, 10, "2026-09", challan_no="PG-2627-0001")
    second = _challan(db, 11, "2026-09", challan_no="PG-2627-0002")
    sha = fh.file_sha256(b"same screenshot")
    proof_service.mark_challan(db, first, sha)
    db.commit()
    assert first.proof_duplicate_of is None
    proof_service.mark_challan(db, second, sha)
    assert second.proof_duplicate_of.startswith("Same proof file as PG-2627-0001 (MEM-0001, Sep 2026)")
    # a rejected payment's proof does not count
    first.status = ChallanStatus.REJECTED
    db.commit()
    proof_service.mark_challan(db, second, sha)
    assert second.proof_duplicate_of is None


def test_bulk_payment_fingerprint_from_earlier_upload(db, monkeypatch):
    monkeypatch.setattr(proof_service, "rename_file", lambda url, hint: url.replace("MEM", hint))
    old = _challan(db, 10, "2026-07", challan_no="PG-2627-0001")
    ref, sha = proof_service.store_proof(db, b"transfer", "t.png", user_id=2, name_hint="MEM-0001-20261120")
    proof_service.mark_challan(db, old, sha)
    rows = [_challan(db, 10, "2026-08"), _challan(db, 10, "2026-09")]
    group = BulkChallanGroup(bulk_group_id="BCH-0001", challan_no="PG-2627-0005", member_id=10,
                             amount_per_month=500, total_amount=1000, proof_file_id=ref, status="pending_approval",
                             months_list="[]", challan_ids_list="[]", created_by_user_id=2)
    db.add(group)
    db.flush()
    proof_service.mark_group(db, group, rows, ref)
    assert group.proof_sha256 == sha and "PG-2627-0001" in group.proof_duplicate_of
    assert all(r.proof_duplicate_of == group.proof_duplicate_of for r in rows)
    assert group.proof_file_id.startswith("https://") and "PG-2627-0005" in group.proof_file_id  # renamed
    assert db.query(ProofFile).filter_by(ref=group.proof_file_id).count() == 1


def test_links_parse_and_public_files_are_unchanged():
    public = "https://res.cloudinary.com/x/image/upload/v1/cc/proofs/abc.png"
    assert fh.signed_url(public) == public
    assert fh.is_private_file("https://res.cloudinary.com/x/image/private/v1/cc/proofs/PG-2627-0001-ab.png")
    assert fh.cloudinary_parts("https://res.cloudinary.com/x/raw/private/v1/cc/proofs/a.pdf")["public_id"] == "cc/proofs/a.pdf"
    assert fh.cloudinary_parts("uploads/proofs/x.png") is None


def test_proof_link_only_for_admins_and_the_owner(db):
    from app.routes.file_routes import proof_link

    c = _challan(db, 10, "2026-09", proof_path="uploads/proofs/x.png")
    assert proof_link(challan_id=c.id, current_user={"user_id": 2, "role": "member"}, db=db)["url"] == "/uploads/proofs/x.png"
    assert proof_link(challan_id=c.id, current_user={"user_id": 1, "role": "admin"}, db=db)["url"]
    with pytest.raises(HTTPException) as exc:
        proof_link(challan_id=c.id, current_user={"user_id": 3, "role": "member"}, db=db)
    assert exc.value.status_code == 403
    empty = _challan(db, 10, "2026-10")
    with pytest.raises(HTTPException) as exc:
        proof_link(challan_id=empty.id, current_user={"user_id": 2, "role": "member"}, db=db)
    assert exc.value.status_code == 404
