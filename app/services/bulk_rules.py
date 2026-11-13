"""Rules shared by every way of creating or reviewing monthly payments.

- A member always pays their own monthly fee. Only an admin entering a
  payment for someone else may use a different amount.
- A month can be paid (or waiting for review) only once.
- Internal errors are logged, never shown to the user.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Challan, ChallanStatus, ChallanType, Member

logger = logging.getLogger(__name__)

GENERIC_ERROR = "Something went wrong and nothing was changed. Please try again."


def monthly_amount_for(member: Member, requested: Optional[float], entry_source: Optional[str]) -> float:
    """The per-month amount to store for a new monthly payment."""
    fee = float(member.monthly_amount or 0)
    if entry_source == "admin":
        amount = float(requested) if requested is not None and float(requested) > 0 else fee
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Enter an amount greater than 0.")
        return amount
    if fee <= 0:
        raise HTTPException(
            status_code=400,
            detail="Your monthly amount is not set yet. Please ask the admins to set it.",
        )
    return fee


def taken_months(
    db: Session,
    member_id: int,
    months: Iterable[str],
    exclude_ids: Iterable[int] = (),
) -> list[str]:
    """Months that already have a payment that is approved, or generated/pending (not rejected)."""
    months = list(months)
    if not months:
        return []
    query = db.query(Challan.month).filter(
        Challan.member_id == member_id,
        Challan.type == ChallanType.MONTHLY,
        Challan.month.in_(months),
        Challan.status != ChallanStatus.REJECTED,
    )
    exclude_ids = [int(i) for i in exclude_ids]
    if exclude_ids:
        query = query.filter(Challan.id.notin_(exclude_ids))
    return sorted({row[0] for row in query.all() if row[0]})


def internal_error(exc: Exception, what: str) -> HTTPException:
    logger.exception("%s failed", what, exc_info=exc)
    return HTTPException(status_code=500, detail=GENERIC_ERROR)
