"""Pay several open months together with one proof.

A member picks months that are still "to pay" in My payments: months they started without
proof (one by one, or together with "one proof for all, upload later"), or the "not paid
yet" rows from the 2026-04 import. One proof covers them all: they become one bulk payment
(BCH-xxxx) with one payment number, reviewed and approved by an admin in one step, exactly
like a multi-month payment made with one proof from the start.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import AuditLog, BulkChallanGroup, Challan, ChallanStatus, ChallanType, Member
from app.services.challan_numbers import next_number
from app.services.challan_state import is_submitted, sync_unpaid_monthly_amounts
from app.services.challan_service import clean_note

MAX_MONTHS = 36


def pay_together(db: Session, current_user: dict, challan_ids: list[int], proof_file_id: str,
                 notes: str | None = None) -> dict:
    user_id = int(current_user.get("user_id"))
    member = db.query(Member).filter(Member.user_id == user_id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="No member record found for your account.")

    ids = sorted({int(i) for i in challan_ids or []})
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Pick at least two months to pay together.")
    if len(ids) > MAX_MONTHS:
        raise HTTPException(status_code=400, detail=f"Pay at most {MAX_MONTHS} months together.")
    proof = (proof_file_id or "").strip()
    if not proof or proof.startswith("no-proof:"):
        raise HTTPException(status_code=400, detail="Please attach the payment screenshot or receipt.")

    sync_unpaid_monthly_amounts(db, member)
    rows = db.query(Challan).filter(Challan.id.in_(ids)).with_for_update().all()
    if len(rows) != len(ids):
        raise HTTPException(status_code=404, detail="Some of these payments no longer exist. Please refresh.")
    for c in rows:
        status = getattr(c.status, "value", c.status)
        if c.member_id != member.id:
            raise HTTPException(status_code=403, detail="You can only pay your own months.")
        if c.type != ChallanType.MONTHLY:
            raise HTTPException(status_code=400, detail="Only monthly payments can be paid together.")
        if status not in ("generated", "pending") or is_submitted(c):
            raise HTTPException(status_code=409, detail="One of these months was already paid or sent. Please refresh.")
    months = sorted(c.month for c in rows)
    if len(set(months)) != len(months):
        raise HTTPException(status_code=400, detail="Each month can be selected only once.")

    numbers = {c.challan_no for c in rows}
    payment_no = numbers.pop() if len(numbers) == 1 and None not in numbers else next_number(db)
    total = round(sum(float(c.amount or 0) for c in rows), 2)
    now = datetime.utcnow()
    group = BulkChallanGroup(
        bulk_group_id=f"tmp-{uuid.uuid4()}",
        challan_no=payment_no,
        member_id=member.id,
        amount_per_month=float(member.monthly_amount or rows[0].amount or 0),
        total_amount=total,
        proof_file_id=proof,
        status="pending_approval",
        months_list=json.dumps(months),
        challan_ids_list=json.dumps([c.id for c in sorted(rows, key=lambda r: r.month)]),
        created_by_user_id=user_id,
        notes=clean_note(notes),
        created_at=now,
    )
    db.add(group)
    db.flush()
    group.bulk_group_id = f"BCH-{group.id:04d}"
    for c in rows:
        c.bulk_group_id = group.bulk_group_id
        c.challan_no = payment_no
        c.status = ChallanStatus.PENDING
        if notes:
            c.entry_notes = clean_note(notes)
    from app.services import proof_service

    proof_service.mark_group(db, group, rows, proof)
    proof = group.proof_file_id
    db.add(AuditLog(
        user_id=user_id, action="bulk_pay_together", entity_type="BulkChallanGroup", entity_id=group.id,
        new_values=json.dumps({"bulk_group_id": group.bulk_group_id, "challan_no": payment_no,
                               "months": months, "total_amount": total, "challan_ids": ids}),
    ))
    db.commit()
    db.refresh(group)

    from app.services.notification_service import NotificationService

    NotificationService.notify_admins_proof_uploaded(
        db, member, months, user_id, bulk_group_id=group.bulk_group_id, bulk_id=group.id,
        warning=group.proof_duplicate_of,
    )
    return {
        "bulk_group_id": group.bulk_group_id,
        "challan_no": payment_no,
        "member_id": member.id,
        "created_challans": len(rows),
        "challan_ids": ids,
        "months": months,
        "total_amount": total,
        "proof_file_id": proof,
        "status": "pending_approval",
        "created_at": group.created_at,
        "notes": group.notes,
    }
