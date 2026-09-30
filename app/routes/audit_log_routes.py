from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import AuditLog
from app.schemas import AuditLogResponse, AuditLogCreate
from app.utils import get_current_admin
from typing import List, Optional
from datetime import datetime, timedelta

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


def _parse_date_boundary(value: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    """Parse a 'YYYY-MM-DD' query param into a datetime boundary."""
    if not value:
        return None
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date '{value}'. Expected format YYYY-MM-DD.")
    return parsed + timedelta(days=1) - timedelta(microseconds=1) if end_of_day else parsed


@router.get("/", response_model=List[AuditLogResponse])
def get_audit_logs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    user_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    action: Optional[str] = None,
    start_date: Optional[str] = Query(default=None, description="Inclusive start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(default=None, description="Inclusive end date (YYYY-MM-DD)"),
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Get audit logs with optional filtering (Admin only).
    """
    query = db.query(AuditLog).options(joinedload(AuditLog.user))

    normalized_user_id = (user_id or "").strip().lower()
    if normalized_user_id and normalized_user_id not in ["all", "null", "undefined"]:
        if not normalized_user_id.isdigit():
            raise HTTPException(status_code=400, detail="user_id must be an integer or empty")
        query = query.filter(AuditLog.user_id == int(normalized_user_id))
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if action:
        query = query.filter(AuditLog.action == action)

    start_boundary = _parse_date_boundary(start_date)
    if start_boundary:
        query = query.filter(AuditLog.created_at >= start_boundary)

    end_boundary = _parse_date_boundary(end_date, end_of_day=True)
    if end_boundary:
        query = query.filter(AuditLog.created_at <= end_boundary)

    return query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()


@router.post("/", response_model=AuditLogResponse, status_code=status.HTTP_201_CREATED)
def create_audit_log(
    payload: AuditLogCreate,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Create audit log entry (Admin only).
    """
    log = AuditLog(
        user_id=payload.user_id if payload.user_id is not None else _current_user.get("user_id"),
        action=payload.action,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        old_values=payload.old_values,
        new_values=payload.new_values,
        ip_address=payload.ip_address,
    )

    db.add(log)
    db.commit()
    db.refresh(log)
    return log
