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
)
from app.utils import get_current_admin
from app.utils.audit import log_audit

router = APIRouter(prefix="/fund-utilizations", tags=["Fund Utilizations"])


def _to_response(fu: FundUtilization) -> FundUtilizationResponse:
    registered_by_name = None
    if fu.registered_by:
        registered_by_name = (
            fu.registered_by.full_name
            or fu.registered_by.username
        )
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
        created_at=fu.created_at,
        updated_at=fu.updated_at,
    )


@router.get("/summary", response_model=FundUtilizationSummary)
def get_fund_utilization_summary(
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Get summary: total collected vs total utilized and available balance (Admin only)."""
    total_collected = db.query(func.coalesce(func.sum(Challan.amount), 0)).filter(
        Challan.status == "approved"
    ).scalar() or 0.0

    total_utilized = db.query(func.coalesce(func.sum(FundUtilization.amount), 0)).scalar() or 0.0
    utilization_count = db.query(func.count(FundUtilization.id)).scalar() or 0

    return FundUtilizationSummary(
        total_collected=float(total_collected),
        total_utilized=float(total_utilized),
        available_balance=float(total_collected) - float(total_utilized),
        utilization_count=int(utilization_count),
    )


@router.get("/", response_model=List[FundUtilizationResponse])
def list_fund_utilizations(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    category: Optional[str] = None,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """List all fund utilization records (Admin only)."""
    query = db.query(FundUtilization)
    if category:
        query = query.filter(FundUtilization.category == category)
    records = query.order_by(FundUtilization.date.desc()).offset(skip).limit(limit).all()
    return [_to_response(r) for r in records]


@router.get("/{fund_utilization_id}", response_model=FundUtilizationResponse)
def get_fund_utilization(
    fund_utilization_id: int,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Get a single fund utilization record by ID (Admin only)."""
    record = db.query(FundUtilization).filter(FundUtilization.id == fund_utilization_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Fund utilization record not found")
    return _to_response(record)


@router.post("/", response_model=FundUtilizationResponse, status_code=status.HTTP_201_CREATED)
def create_fund_utilization(
    payload: FundUtilizationCreate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Register a new fund utilization entry (Admin only)."""

    # 🔴 ADD THIS BLOCK
    total_collected = db.query(func.coalesce(func.sum(Challan.amount), 0))\
        .filter(Challan.status == "approved").scalar() or 0

    total_utilized = db.query(func.coalesce(func.sum(FundUtilization.amount), 0)).scalar() or 0

    available_balance = float(total_collected) - float(total_utilized)

    if payload.amount > available_balance:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient funds. Available balance is ₹{available_balance}"
        )
    # 🔴 END BLOCK

    # Existing code
    record = FundUtilization(
        title=payload.title,
        description=payload.description,
        amount=payload.amount,
        category=payload.category,
        recipient=payload.recipient,
        date=payload.date or datetime.utcnow(),
        registered_by_admin_id=current_user["user_id"],
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    return _to_response(record)


@router.put("/{fund_utilization_id}", response_model=FundUtilizationResponse)
def update_fund_utilization(
    fund_utilization_id: int,
    payload: FundUtilizationUpdate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Update a fund utilization entry (Admin only)."""
    record = db.query(FundUtilization).filter(FundUtilization.id == fund_utilization_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Fund utilization record not found")

    old_values = {
        "title": record.title,
        "amount": record.amount,
        "category": record.category,
        "recipient": record.recipient,
        "date": record.date.isoformat() if record.date else None,
        "description": record.description,
    }

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(record, field, value)

    db.commit()
    db.refresh(record)

    log_audit(
        db,
        user_id=current_user["user_id"],
        action="fund_utilization_update",
        entity_type="FundUtilization",
        entity_id=record.id,
        old_values=old_values,
        new_values=update_data,
        auto_commit=True,
    )

    return _to_response(record)


@router.delete("/{fund_utilization_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fund_utilization(
    fund_utilization_id: int,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Delete a fund utilization entry (Admin only)."""
    record = db.query(FundUtilization).filter(FundUtilization.id == fund_utilization_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Fund utilization record not found")

    old_values = {
        "title": record.title,
        "amount": record.amount,
        "category": record.category,
        "recipient": record.recipient,
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
