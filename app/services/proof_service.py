"""Payment proofs: stored privately, named after the payment, and checked for reuse.

- New proofs go to private storage, named by the payment number (PG-2627-0042-xxxx) or,
  when the payment does not exist yet, by the member ID (renamed once the number is known).
  They open only through short-lived links (file_handler.signed_url).
- Every proof's fingerprint (SHA-256 of the file) is kept. When the same file was already
  used for another payment, the new payment gets a note ("Same proof as PG-2627-0003 ...")
  that admins see before approving.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.models import BulkChallanGroup, Challan, ChallanStatus, Member, ProofFile
from app.utils.file_handler import file_sha256, rename_file, save_file

logger = logging.getLogger(__name__)


def member_hint(db: Session, user_id: int | None) -> str | None:
    """MEM-0012-20261120 for a member's own upload (the payment number is not known yet)."""
    if user_id is None:
        return None
    code = db.query(Member.member_code).filter(Member.user_id == user_id).scalar()
    day = datetime.utcnow().strftime("%Y%m%d")
    return f"{code}-{day}" if code else f"user{user_id}-{day}"


def store_proof(db: Session, content: bytes, filename: str, *, user_id: int | None,
                name_hint: str | None) -> tuple[str, str]:
    """Save privately and remember the fingerprint. Returns (stored URL, sha256). Caller commits."""
    sha = file_sha256(content)
    ref = save_file(content, "proofs", filename, name_hint=name_hint, private=True)
    db.add(ProofFile(ref=ref, sha256=sha, user_id=user_id))
    db.flush()
    return ref, sha


def sha_for_ref(db: Session, ref: str | None) -> str | None:
    if not ref:
        return None
    return db.query(ProofFile.sha256).filter(ProofFile.ref == ref).scalar()


def _describe(c: Challan) -> str:
    who = c.member.member_code if c.member is not None else f"member {c.member_id}"
    if c.month:
        try:
            what = datetime.strptime(c.month, "%Y-%m").strftime("%b %Y")
        except ValueError:
            what = c.month
    else:
        what = c.campaign.title if c.campaign is not None else "donation"
    return f"{c.challan_no or f'CH-{c.id}'} ({who}, {what})"


def duplicate_note(db: Session, sha: str | None, *, exclude_challan_ids=(), exclude_group_id: str | None = None,
                   ref: str | None = None) -> str | None:
    """'Same proof file as ...' when another (not rejected) payment used this file, else None."""
    if not sha:
        return None
    exclude = {int(i) for i in exclude_challan_ids if i is not None}
    rows = (
        db.query(Challan)
        .filter(Challan.proof_sha256 == sha, Challan.status != ChallanStatus.REJECTED)
        .order_by(Challan.id.asc())
        .limit(20)
        .all()
    )
    others = [c for c in rows if c.id not in exclude and (exclude_group_id is None or c.bulk_group_id != exclude_group_id)]
    groups = (
        db.query(BulkChallanGroup)
        .filter(BulkChallanGroup.proof_sha256 == sha, BulkChallanGroup.status != "rejected")
        .all()
    )
    other_groups = [g for g in groups if g.bulk_group_id != exclude_group_id]
    # Rows of another bulk payment are listed once, as that payment.
    other_group_ids = {g.bulk_group_id for g in other_groups}
    others = [c for c in others if c.bulk_group_id not in other_group_ids]
    parts = [_describe(c) for c in others[:3]]
    parts += [f"{g.challan_no or g.bulk_group_id} (bulk payment)" for g in other_groups[:2]]
    if not parts:
        return None
    return ("Same proof file as " + "; ".join(parts))[:250]


def mark_challan(db: Session, challan: Challan, sha: str | None, ref: str | None = None) -> None:
    challan.proof_sha256 = sha
    challan.proof_duplicate_of = duplicate_note(db, sha, exclude_challan_ids=[challan.id],
                                                exclude_group_id=challan.bulk_group_id, ref=ref)


def mark_group(db: Session, group: BulkChallanGroup, challans, ref: str | None) -> None:
    """Fingerprint a bulk payment from its (already uploaded) proof, and name the file after it."""
    sha = sha_for_ref(db, ref)
    note = duplicate_note(db, sha, exclude_challan_ids=[c.id for c in challans],
                          exclude_group_id=group.bulk_group_id, ref=ref)
    group.proof_sha256 = sha
    group.proof_duplicate_of = note
    for c in challans:
        c.proof_sha256 = sha
        c.proof_duplicate_of = note
    if ref and group.challan_no:
        new_ref = rename_file(ref, group.challan_no)
        if new_ref and new_ref != ref:
            group.proof_file_id = new_ref
            for c in challans:
                if c.proof_path == ref:
                    c.proof_path = new_ref
            row = db.query(ProofFile).filter(ProofFile.ref == ref).first()
            if row is not None:
                row.ref = new_ref
