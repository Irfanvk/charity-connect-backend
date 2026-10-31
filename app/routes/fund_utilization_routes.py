from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models import FundUtilization, Challan, User
from app.schemas import (
    FundUtilizationCreate,
    FundUtilizationUpdate,
    FundUtilizationResponse,
    FundUtilizationSummary,
    FundUtilizationReasonAction,
)
from app.services.notification_service import NotificationService
from app.utils import get_current_admin, get_current_user
from app.utils.audit import log_audit
from app.utils.permissions import assert_different_actor, assert_not_own_user, require_reason

router = APIRouter(prefix="/fund-utilizations", tags=["Fund Utilizations"])

CREATOR_ONLY_DETAIL = "Only the admin who registered this entry can {action} it while it is pending."


def _to_response(fu: FundUtilization) -> FundUtilizationResponse:
    registered_by_name = None
    if fu.registered_by:
        registered_by_name = (
            fu.registered_by.full_name
            or fu.registered_by.username
        )
    approved_by_name = fu.approved_by.full_name or fu.approved_by.username if fu.approved_by else None
    reversed_by_name = fu.reversed_by.full_name or fu.reversed_by.username if fu.reversed_by else None
    return FundUtilizationResponse(
        id=fu.id,
        title=fu.title,
        description=fu.description,
        amount=fu.amount,
        category=fu.category,
        recipient=fu.recipient,
        date=fu.date,
        registered_by_admin_id=fu.registered_by_admin_id,
        registered_by_name=registered_by_name,
        status=fu.status or "pending",
        approved_by_admin_id=fu.approved_by_admin_id,
        approved_by_name=approved_by_name,
        approved_at=fu.approved_at,
        rejection_reason=fu.rejection_reason,
        reversed_at=fu.reversed_at,
        reversed_by_admin_id=fu.reversed_by_admin_id,
        reversed_by_name=reversed_by_name,
        reversal_reason=fu.reversal_reason,
        created_at=fu.created_at,
        updated_at=fu.updated_at,
    )


def _approved_totals(db: Session) -> tuple[float, float]:
    total_collected = db.query(func.coalesce(func.sum(Challan.amount), 0)).filter(
        Challan.status == "approved"
    ).scalar() or 0.0
    approved_utilized = db.query(func.coalesce(func.sum(FundUtilization.amount), 0)).filter(
        FundUtilization.status == "approved"
    ).scalar() or 0.0
    return float(total_collected), float(approved_utilized)


def _get_record(db: Session, fund_utilization_id: int) -> FundUtilization:
    record = db.query(FundUtilization).filter(FundUtilization.id == fund_utilization_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Fund utilization record not found")
    return record


def _check_available(db: Session, amount: float) -> None:
    total_collected, approved_utilized = _approved_totals(db)
    available_balance = total_collected - approved_utilized
    if amount > available_balance:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient funds. Available balance is ₹{available_balance}"
        )


@router.get("/summary", response_model=FundUtilizationSummary)
def get_fund_utilization_summary(
    _current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Summary: only approved entries reduce the balance; pending entries are reported separately."""
    total_collected, total_utilized = _approved_totals(db)
    utilization_count = db.query(func.count(FundUtilization.id)).filter(
        FundUtilization.status == "approved"
    ).scalar() or 0
    pending_total = db.query(func.coalesce(func.sum(FundUtilization.amount), 0)).filter(
        FundUtilization.status == "pending"
    ).scalar() or 0.0
    pending_count = db.query(func.count(FundUtilization.id)).filter(
        FundUtilization.status == "pending"
    ).scalar() or 0

    return FundUtilizationSummary(
        total_collected=total_collected,
        total_utilized=total_utilized,
        available_balance=total_collected - total_utilized,
        utilization_count=int(utilization_count),
        pending_utilized_total=float(pending_total),
        pending_count=int(pending_count),
    )


@router.get("/", response_model=List[FundUtilizationResponse])
def list_fund_utilizations(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    category: Optional[str] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    _current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all fund utilization records (all authenticated users)."""
    query = db.query(FundUtilization)
    if category:
        query = query.filter(FundUtilization.category == category)
    if status_filter:
        query = query.filter(FundUtilization.status == status_filter)
    records = query.order_by(FundUtilization.date.desc()).offset(skip).limit(limit).all()
    return [_to_response(r) for r in records]


@router.get("/{fund_utilization_id}", response_model=FundUtilizationResponse)
def get_fund_utilization(
    fund_utilization_id: int,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Get a single fund utilization record by ID (Admin only)."""
    return _to_response(_get_record(db, fund_utilization_id))


@router.post("/", response_model=FundUtilizationResponse, status_code=status.HTTP_201_CREATED)
def create_fund_utilization(
    payload: FundUtilizationCreate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Register a new fund utilization entry; another admin must approve it."""
    _check_available(db, payload.amount)

    record = FundUtilization(
        title=payload.title,
        description=payload.description,
        amount=payload.amount,
        category=payload.category,
        recipient=payload.recipient,
        date=payload.date or datetime.utcnow(),
        registered_by_admin_id=current_user["user_id"],
        status="pending",
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    log_audit(
        db,
        user_id=current_user["user_id"],
        action="fund_utilization_create",
        entity_type="FundUtilization",
        entity_id=record.id,
        new_values={"title": record.title, "amount": record.amount, "status": "pending"},
        auto_commit=True,
    )
    NotificationService.notify_fund_utilization_created(db, record)

    return _to_response(record)


@router.put("/{fund_utilization_id}", response_model=FundUtilizationResponse)
def update_fund_utilization(
    fund_utilization_id: int,
    payload: FundUtilizationUpdate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Update a pending fund utilization entry (creator only)."""
    record = _get_record(db, fund_utilization_id)
    if record.status == "approved":
        raise HTTPException(status_code=400, detail="Approved fund utilizations cannot be edited")
    if record.registered_by_admin_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail=CREATOR_ONLY_DETAIL.format(action="edit"))

    old_values = {
        "title": record.title,
        "amount": record.amount,
        "category": record.category,
        "recipient": record.recipient,
        "date": record.date.isoformat() if record.date else None,
        "description": record.description,
        "status": record.status,
    }

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(record, field, value)

    # Editing a rejected entry puts it back in the review queue.
    if record.status == "rejected":
        record.status = "pending"
        record.rejection_reason = None

    db.commit()
    db.refresh(record)

    log_audit(
        db,
        user_id=current_user["user_id"],
        action="fund_utilization_update",
        entity_type="FundUtilization",
        entity_id=record.id,
        old_values=old_values,
        new_values={**update_data, "status": record.status},
        auto_commit=True,
    )

    return _to_response(record)


@router.delete("/{fund_utilization_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fund_utilization(
    fund_utilization_id: int,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Delete a pending fund utilization entry (creator only)."""
    record = _get_record(db, fund_utilization_id)
    if record.status == "approved":
        raise HTTPException(status_code=400, detail="Approved fund utilizations cannot be deleted")
    if record.registered_by_admin_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail=CREATOR_ONLY_DETAIL.format(action="delete"))

    old_values = {
        "title": record.title,
        "amount": record.amount,
        "category": record.category,
        "recipient": record.recipient,
        "status": record.status,
    }

    db.delete(record)
    db.commit()

    log_audit(
        db,
        user_id=current_user["user_id"],
        action="fund_utilization_delete",
        entity_type="FundUtilization",
        entity_id=fund_utilization_id,
        old_values=old_values,
        auto_commit=True,
    )


@router.patch("/{fund_utilization_id}/approve", response_model=FundUtilizationResponse)
def approve_fund_utilization(
    fund_utilization_id: int,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Approve a pending entry. Anyone except the admin who registered it."""
    record = _get_record(db, fund_utilization_id)
    assert_not_own_user(current_user, record.registered_by_admin_id, "approve")
    if record.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending fund utilizations can be approved")
    _check_available(db, record.amount)

    record.status = "approved"
    record.approved_by_admin_id = current_user["user_id"]
    record.approved_at = datetime.utcnow()
    record.rejection_reason = None
    db.commit()
    db.refresh(record)

    log_audit(
        db,
        user_id=current_user["user_id"],
        action="fund_utilization_approve",
        entity_type="FundUtilization",
        entity_id=record.id,
        old_values={"status": "pending"},
        new_values={"status": "approved", "amount": record.amount},
        auto_commit=True,
    )
    NotificationService.notify_fund_utilization_status_change(db, record, "approved")
    return _to_response(record)


@router.patch("/{fund_utilization_id}/reject", response_model=FundUtilizationResponse)
def reject_fund_utilization(
    fund_utilization_id: int,
    payload: FundUtilizationReasonAction,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Reject a pending entry. Anyone except the admin who registered it."""
    record = _get_record(db, fund_utilization_id)
    assert_not_own_user(current_user, record.registered_by_admin_id, "reject")
    require_reason(payload.reason, "Rejection reason", db)
    if record.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending fund utilizations can be rejected")

    record.status = "rejected"
    record.rejection_reason = payload.reason
    db.commit()
    db.refresh(record)

    log_audit(
        db,
        user_id=current_user["user_id"],
        action="fund_utilization_reject",
        entity_type="FundUtilization",
        entity_id=record.id,
        old_values={"status": "pending"},
        new_values={"status": "rejected", "reason": payload.reason},
        auto_commit=True,
    )
    NotificationService.notify_fund_utilization_status_change(db, record, "rejected", payload.reason)
    return _to_response(record)


@router.patch("/{fund_utilization_id}/revert", response_model=FundUtilizationResponse)
def revert_fund_utilization(
    fund_utilization_id: int,
    payload: FundUtilizationReasonAction,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Move an approved entry back to pending. Must not be the admin who approved it."""
    record = _get_record(db, fund_utilization_id)
    if record.status != "approved":
        raise HTTPException(status_code=400, detail="Only approved fund utilizations can be reverted")
    require_reason(payload.reason, "Reason", db)
    assert_different_actor(current_user["user_id"], record.approved_by_admin_id, "Reversal")

    record.status = "pending"
    record.reversed_at = datetime.utcnow()
    record.reversed_by_admin_id = current_user["user_id"]
    record.reversal_reason = payload.reason
    record.approved_by_admin_id = None
    record.approved_at = None
    db.commit()
    db.refresh(record)

    log_audit(
        db,
        user_id=current_user["user_id"],
        action="fund_utilization_revert",
        entity_type="FundUtilization",
        entity_id=record.id,
        old_values={"status": "approved"},
        new_values={"status": "pending", "reason": payload.reason},
        auto_commit=True,
    )
    NotificationService.notify_fund_utilization_status_change(db, record, "reverted", payload.reason)
    return _to_response(record)
