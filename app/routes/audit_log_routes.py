from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AuditLog
from app.schemas import AuditLogResponse, AuditLogCreate
from app.utils import get_current_admin
from typing import List, Optional

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@router.get("/", response_model=List[AuditLogResponse])
def get_audit_logs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    user_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    action: Optional[str] = None,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Get audit logs with optional filtering (Admin only).
    """
    query = db.query(AuditLog)

    normalized_user_id = (user_id or "").strip().lower()
    if normalized_user_id and normalized_user_id not in ["all", "null", "undefined"]:
        if not normalized_user_id.isdigit():
            raise HTTPException(status_code=400, detail="user_id must be an integer or empty")
        query = query.filter(AuditLog.user_id == int(normalized_user_id))
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if action:
        query = query.filter(AuditLog.action == action)

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
        user_id=payload.user_id,
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
