import csv
import io

from fastapi import APIRouter, Depends, status, Query, HTTPException, Response
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import AuditLog
from app.schemas import AuditLogResponse, AuditLogCreate
from app.services import audit_feed_service
from app.utils import get_current_admin
from typing import List, Optional
from datetime import datetime, timedelta

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])
EXPORT_MAX_ROWS = 5000


def _parse_date_boundary(value: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    """Parse a 'YYYY-MM-DD' query param into a datetime boundary."""
    if not value:
        return None
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date '{value}'. Expected format YYYY-MM-DD.")
    return parsed + timedelta(days=1) - timedelta(microseconds=1) if end_of_day else parsed


def _feed_filters(user_id, role, area, action, start_date, end_date, search) -> dict:
    return {
        "user_id": user_id, "role": role or None, "area": area or None, "action": action or None,
        "start_date": start_date or None, "end_date": end_date or None, "search": search or None,
    }


@router.get("/feed")
def get_audit_feed(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=audit_feed_service.MAX_LIMIT),
    user_id: Optional[int] = None,
    role: Optional[str] = Query(default=None, description="admin | superadmin | member | system"),
    area: Optional[str] = Query(default=None, description="members | payments | bulk | requests | campaigns | funds | notifications | settings | other"),
    action: Optional[str] = None,
    start_date: Optional[str] = Query(default=None, description="Inclusive start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(default=None, description="Inclusive end date (YYYY-MM-DD)"),
    search: Optional[str] = None,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Audit Logs page: newest first, with readable names and a list of changes (Admin only)."""
    filters = _feed_filters(user_id, role, area, action, start_date, end_date, search)
    return audit_feed_service.feed(db, skip=skip, limit=limit, **filters)


@router.get("/filters")
def get_audit_filter_options(
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Who has entries, every recorded action and the areas, for the filter lists (Admin only)."""
    return audit_feed_service.filter_options(db)


@router.get("/export")
def export_audit_feed(
    user_id: Optional[int] = None,
    role: Optional[str] = None,
    area: Optional[str] = None,
    action: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """CSV of every entry matching the filters, newest first (max 5000 rows; Admin only)."""
    filters = _feed_filters(user_id, role, area, action, start_date, end_date, search)
    items = []
    while len(items) < EXPORT_MAX_ROWS:
        page = audit_feed_service.feed(db, skip=len(items), limit=audit_feed_service.MAX_LIMIT, **filters)
        items += page["items"]
        if not page["has_more"]:
            break
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["When (India time)", "Who", "Role", "Action", "Area", "Item", "Changes"])
    writer.writerows(audit_feed_service.as_csv_rows(items[:EXPORT_MAX_ROWS]))
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-logs.csv"'},
    )


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
