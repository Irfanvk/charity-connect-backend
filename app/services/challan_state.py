"""What a challan's status really means.

The 2026-04 import created a "pending" challan for every month a member had
NOT paid yet, with no proof attached. In the app "pending" otherwise means
"submitted, waiting for an admin". So a pending challan only counts as a real
submission when something was handed in: a proof, a bulk payment (proof on the
group), or a payment an admin recorded. Everything else is "not paid yet".
"""
from __future__ import annotations

from sqlalchemy import and_, func, not_, or_
from sqlalchemy.orm import Session

from app.models.models import Challan, ChallanStatus, ChallanType


def submitted_clause():
    """SQL: the challan represents an actual payment handed in (or decided)."""
    return or_(
        Challan.status.in_([ChallanStatus.APPROVED, ChallanStatus.REJECTED]),
        Challan.proof_path.isnot(None),
        Challan.proof_uploaded_at.isnot(None),
        Challan.bulk_group_id.isnot(None),
        func.coalesce(Challan.entry_source, "") == "admin",
    )


def unpaid_monthly_clause():
    """SQL: monthly challans with nothing submitted (generated, or imported 'pending')."""
    return and_(
        Challan.type == ChallanType.MONTHLY,
        Challan.status.in_([ChallanStatus.GENERATED, ChallanStatus.PENDING]),
        not_(submitted_clause()),
    )


def is_submitted(challan: Challan) -> bool:
    status = getattr(challan.status, "value", challan.status)
    return bool(
        status in ("approved", "rejected")
        or challan.proof_path
        or challan.proof_uploaded_at
        or challan.bulk_group_id
        or (challan.entry_source or "") == "admin"
    )


def sync_unpaid_monthly_amounts(db: Session, member) -> int:
    """Unpaid monthly challans always show the member's current monthly fee.

    Paid, submitted or decided challans keep the amount actually paid.
    Returns how many challans changed. The caller commits.
    """
    fee = float(member.monthly_amount or 0)
    if fee <= 0:
        return 0
    rows = (
        db.query(Challan)
        .filter(Challan.member_id == member.id, unpaid_monthly_clause(), Challan.amount != fee)
        .all()
    )
    for challan in rows:
        challan.amount = fee
    return len(rows)
