"""What the approving admin checked against the bank, saved with the payment.

On approval an admin can record: the date the money reached the bank, the bank / UPI / UTR
reference, the amount actually received, how it was paid, a note, and a bank record file
(a screenshot or PDF of the statement line). Rules:
- A reference already used by another (not rejected) payment is refused unless the admin
  confirms it (e.g. one transfer that really covered two people).
- An amount that differs from the amount due needs a note.
Everything is optional for older app versions; the approve screen asks for it.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import BulkChallanGroup, Challan, ChallanStatus
from app.utils.payment_methods import normalize_payment_method

REFERENCE_PREFIXES = ("uploads/", "/uploads/", "https://")


class Verification(BaseModel):
    received_on: Optional[date] = None
    transaction_ref: Optional[str] = Field(default=None, max_length=100)
    received_amount: Optional[float] = Field(default=None, ge=0)
    payment_method: Optional[str] = Field(default=None, max_length=50)
    verification_note: Optional[str] = Field(default=None, max_length=300)
    bank_record_file_id: Optional[str] = Field(default=None, max_length=500)
    confirm_duplicate_ref: bool = False

    def is_empty(self) -> bool:
        return not any([self.received_on, self.transaction_ref, self.received_amount is not None,
                        self.payment_method, self.verification_note, self.bank_record_file_id])


def _clean(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip()
    return cleaned or None


def reference_used_by(db: Session, ref: str, *, exclude_ids: Iterable[int] = (),
                      exclude_group_id: Optional[str] = None) -> Optional[str]:
    """The payment number that already used this bank reference, if any."""
    exclude = {int(i) for i in exclude_ids}
    rows = (
        db.query(Challan)
        .filter(func.lower(Challan.transaction_ref) == ref.lower(), Challan.status != ChallanStatus.REJECTED)
        .limit(10)
        .all()
    )
    for c in rows:
        if c.id in exclude or (exclude_group_id and c.bulk_group_id == exclude_group_id):
            continue
        who = c.member.member_code if c.member is not None else ""
        return f"{c.challan_no or c.bulk_group_id or f'CH-{c.id}'} ({who})".strip()
    group = (
        db.query(BulkChallanGroup)
        .filter(func.lower(BulkChallanGroup.transaction_ref) == ref.lower(), BulkChallanGroup.status != "rejected")
        .first()
    )
    if group is not None and group.bulk_group_id != exclude_group_id:
        return group.challan_no or group.bulk_group_id
    return None


def apply(db: Session, verification: Optional[Verification], challans: list[Challan],
          group: Optional[BulkChallanGroup] = None) -> None:
    """Check and save what the admin verified on the payment's challans (and bulk group). No commit."""
    if verification is None or verification.is_empty():
        return
    ref = _clean(verification.transaction_ref)
    if ref and not verification.confirm_duplicate_ref:
        used = reference_used_by(db, ref, exclude_ids=[c.id for c in challans],
                                 exclude_group_id=group.bulk_group_id if group is not None else None)
        if used:
            raise HTTPException(status_code=409, detail={
                "message": f"This bank reference was already used for {used}. Check it, or confirm to approve anyway.",
                "duplicate_of": used,
            })
    expected = float(group.total_amount) if group is not None else sum(float(c.amount or 0) for c in challans)
    note = _clean(verification.verification_note)
    received = verification.received_amount
    if received is not None and abs(float(received) - expected) > 0.5 and not note:
        raise HTTPException(
            status_code=400,
            detail=f"The amount received (₹{received:,.0f}) is not the amount due (₹{expected:,.0f}). Add a note explaining why.",
        )
    if verification.received_on and verification.received_on > date.today():
        raise HTTPException(status_code=400, detail="The date received cannot be in the future.")
    record = _clean(verification.bank_record_file_id)
    if record and (not record.startswith(REFERENCE_PREFIXES) or ".." in record):
        raise HTTPException(status_code=400, detail="The bank record must be a file uploaded through the app.")
    method = normalize_payment_method(verification.payment_method)

    targets = list(challans) + ([group] if group is not None else [])
    for target in targets:
        if verification.received_on:
            target.received_on = verification.received_on
        if ref:
            target.transaction_ref = ref
        if method:
            target.payment_method = method
        if note:
            target.verification_note = note
        if record:
            target.bank_record_path = record
    if received is not None:
        if group is not None:
            group.received_amount = float(received)
        elif len(challans) == 1:
            challans[0].received_amount = float(received)
