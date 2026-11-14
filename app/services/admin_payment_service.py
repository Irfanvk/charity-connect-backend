"""Admin-recorded payments (maker-checker): an admin enters a payment for a member, a different admin verifies it."""
import json
import re
import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models import BulkChallanGroup, Campaign, Challan, Member, User
from app.models.models import ChallanStatus, ChallanType, UserRole
from app.services.challan_service import ChallanService
from app.services.challan_state import is_submitted
from app.services.settings_service import get_setting
from app.utils.file_handler import save_file, validate_file
from app.utils.payment_methods import (
    NOTES_REQUIRED_METHODS,
    REFERENCE_REQUIRED_METHODS,
    validate_payment_method,
)
from app.utils.permissions import assert_not_self
from app.utils.timezone import today_business

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PROOF_REFERENCE_PREFIXES = ("uploads/", "/uploads/", "https://")


def _group_months(db: Session, member_id: int, challans: list[Challan], *, per_month: float,
                  proof_path: Optional[str], notes: Optional[str], actor_id: int) -> BulkChallanGroup:
    """Several months recorded in one entry become one bulk payment, so another admin
    approves (or rejects) them in one step, like a multi-month payment with one proof."""
    db.flush()
    group = BulkChallanGroup(
        bulk_group_id=f"tmp-{uuid.uuid4()}",
        member_id=member_id,
        amount_per_month=per_month,
        total_amount=round(sum(float(c.amount or 0) for c in challans), 2),
        proof_file_id=proof_path or f"no-proof:{uuid.uuid4()}",
        status="pending_approval",
        months_list=json.dumps(sorted(c.month for c in challans)),
        challan_ids_list=json.dumps([c.id for c in challans]),
        created_by_user_id=actor_id,
        notes=notes,
        created_at=datetime.utcnow(),
    )
    db.add(group)
    db.flush()
    group.bulk_group_id = f"BCH-{group.id:04d}"
    db.flush()
    for challan in challans:
        challan.bulk_group_id = group.bulk_group_id
    return group


def _clean(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip()
    return cleaned or None


def parse_months(raw: Optional[list[str]]) -> list[str]:
    """Accept repeated or comma-separated month values."""
    months: list[str] = []
    for item in raw or []:
        for part in str(item).split(","):
            part = part.strip()
            if part:
                months.append(part)
    return months


def parse_received_on(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.strptime(str(value or "").strip()[:10], "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="received_on must be a valid date (YYYY-MM-DD)") from exc
    if parsed > today_business():
        raise HTTPException(status_code=400, detail="received_on cannot be in the future (IST)")
    return parsed


def resolve_collector(db: Session, current_user: dict, collected_by_user_id: Optional[int]) -> int:
    collector_id = collected_by_user_id or current_user.get("user_id")
    collector = db.query(User).filter(User.id == collector_id).first()
    if (
        collector is None
        or not collector.is_active
        or collector.role not in (UserRole.ADMIN, UserRole.SUPERADMIN)
    ):
        raise HTTPException(status_code=400, detail="Cash must be collected by an active admin or superadmin")
    return collector.id


def find_duplicate_reference(db: Session, transaction_ref: str) -> Optional[Challan]:
    from sqlalchemy import func

    return (
        db.query(Challan)
        .filter(
            func.lower(Challan.transaction_ref) == transaction_ref.lower(),
            Challan.status != ChallanStatus.REJECTED,
        )
        .first()
    )


def _store_proof(db: Session, proof_file: Optional[UploadFile], proof_file_id: Optional[str]) -> Optional[str]:
    if proof_file is not None and proof_file.filename:
        content = proof_file.file.read()
        validate_file(content, proof_file.filename, max_size_mb=get_setting(db, "proof_max_upload_mb"))
        return save_file(content, "proofs", proof_file.filename)
    reference = _clean(proof_file_id)
    if reference:
        if not reference.startswith(PROOF_REFERENCE_PREFIXES) or ".." in reference:
            raise HTTPException(status_code=400, detail="proof_file_id must be a file uploaded through the platform")
        return reference
    return None


def record_payment(
    db: Session,
    current_user: dict,
    *,
    member_id: int,
    challan_type: str,
    months: list[str],
    campaign_id: Optional[int],
    amount_per_month: Optional[float],
    amount: Optional[float],
    payment_method: Optional[str],
    transaction_ref: Optional[str],
    received_on,
    collected_by_user_id: Optional[int],
    entry_notes: Optional[str],
    proof_file: Optional[UploadFile] = None,
    proof_file_id: Optional[str] = None,
) -> list[Challan]:
    actor_id = current_user.get("user_id")
    assert_not_self(db, current_user, member_id, "record")

    member = db.query(Member).filter(Member.id == member_id).first()
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.status != "active":
        raise HTTPException(status_code=400, detail="Cannot record a payment for an inactive member")

    kind = (challan_type or "").strip().lower()
    if kind not in ("monthly", "campaign"):
        raise HTTPException(status_code=400, detail="type must be 'monthly' or 'campaign'")

    method = validate_payment_method(payment_method)
    reference = _clean(transaction_ref)
    notes = _clean(entry_notes)
    received = parse_received_on(received_on) if received_on else None
    if received is None:
        raise HTTPException(status_code=400, detail="received_on is required")

    if method in REFERENCE_REQUIRED_METHODS and not reference:
        raise HTTPException(status_code=400, detail="transaction_ref is required for bank transfer, UPI and cheque payments")
    if method in NOTES_REQUIRED_METHODS and not notes:
        raise HTTPException(status_code=400, detail="entry_notes is required for cash and other payments")
    if reference and method != "cash":
        existing = find_duplicate_reference(db, reference)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"This transaction reference is already used by challan #{existing.id}",
            )

    collector_id = resolve_collector(db, current_user, collected_by_user_id) if method == "cash" else None

    campaign = None
    if kind == "monthly":
        unique_months = list(dict.fromkeys(months))
        if not unique_months:
            raise HTTPException(status_code=422, detail="At least one month must be selected")
        if len(unique_months) != len(months):
            raise HTTPException(status_code=400, detail="Duplicate months selected")
        if any(not MONTH_RE.match(m) for m in unique_months):
            raise HTTPException(status_code=422, detail="Months must use the YYYY-MM format")
        # Admins recording money already received: no limit on months in one entry
        # (members' own payments keep the "max months per payment" setting).
        for m in unique_months:
            ChallanService._ensure_month_not_before_platform(m)

        payable = ChallanService.get_payable_months(db, member_id, include_upcoming=True,
                                                    include_unpaid_placeholders=True)
        invalid = [m for m in unique_months if m not in set(payable["all_months"])]
        if invalid:
            raise HTTPException(status_code=422, detail=f"The following months are not available for this member: {invalid}")
        open_rows = (
            db.query(Challan)
            .filter(
                Challan.member_id == member_id,
                Challan.type == ChallanType.MONTHLY,
                Challan.month.in_(unique_months),
                Challan.status.in_([ChallanStatus.GENERATED, ChallanStatus.PENDING]),
            )
            .all()
        )
        # A "not paid yet" row (generated, or imported pending with nothing handed in) is filled in
        # by this entry; a row with something handed in is a real clash.
        placeholders = {c.month: c for c in open_rows if not is_submitted(c)}
        clash = [c for c in open_rows if is_submitted(c)]
        if clash:
            raise HTTPException(status_code=400, detail=f"Challans already exist for months: {sorted(c.month for c in clash)}")

        standard = float(member.monthly_amount or 0)
        per_month = float(amount_per_month) if amount_per_month is not None else standard
        if per_month <= 0:
            raise HTTPException(status_code=400, detail="amount_per_month must be greater than 0")
        if per_month != standard and not notes:
            raise HTTPException(status_code=400, detail="entry_notes is required when the amount differs from the member's monthly amount")
        targets = [(m, per_month) for m in unique_months]
    else:
        if not campaign_id:
            raise HTTPException(status_code=400, detail="campaign_id is required for campaign payments")
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if campaign.status != "active":
            raise HTTPException(status_code=400, detail="Cannot record a payment for an inactive campaign")
        if amount is None or float(amount) <= 0:
            raise HTTPException(status_code=400, detail="amount must be greater than 0")
        if float(amount) < float(campaign.min_amount or 0):
            raise HTTPException(status_code=400, detail=f"Minimum donation for this campaign is ₹{campaign.min_amount}")
        targets = [(None, float(amount))]

    proof_path = _store_proof(db, proof_file, proof_file_id)

    created: list[Challan] = []
    fill = placeholders if kind == "monthly" else {}
    for month, value in targets:
        fields = dict(
            amount=value,
            payment_method=method,
            status=ChallanStatus.PENDING,
            proof_path=proof_path,
            proof_uploaded_at=datetime.utcnow() if proof_path else None,
            entry_source="admin",
            created_by_user_id=actor_id,
            transaction_ref=reference,
            received_on=received,
            collected_by_user_id=collector_id,
            entry_notes=notes,
        )
        challan = fill.get(month)
        if challan is not None:
            for key, val in fields.items():
                setattr(challan, key, val)
        else:
            challan = Challan(
                member_id=member_id,
                type=ChallanType.MONTHLY if kind == "monthly" else ChallanType.CAMPAIGN,
                month=month,
                campaign_id=campaign.id if campaign else None,
                **fields,
            )
            db.add(challan)
        created.append(challan)
    if kind == "monthly" and len(created) > 1:
        _group_months(db, member_id, created, per_month=targets[0][1], proof_path=proof_path,
                      notes=notes, actor_id=actor_id)
    db.commit()
    for challan in created:
        db.refresh(challan)
        db.refresh(challan, ["member"])
        challan.member_name = member.full_name
    return created
