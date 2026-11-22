"""Reports for admins and superadmins (see app/services/report_service.py)."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import report_service
from app.utils import get_current_staff, get_current_user

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/member-statement/{member_id}")
def member_statement(
    member_id: int,
    from_month: Optional[str] = Query(default=None, description="yyyy-MM; default: join month"),
    to_month: Optional[str] = Query(default=None, description="yyyy-MM; default: this month"),
    _admin: dict = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """Every month for one member (paid, waiting, not paid), totals due, and donations."""
    return report_service.member_statement(db, member_id, from_month, to_month)


@router.get("/my-statement")
def my_statement(
    year: Optional[int] = Query(default=None, ge=2024, le=2100, description="Year (January to December); default: this year"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Your own statement (members, and admins who are members): one year month by month,
    the years there are, and every payment you made with its receipt."""
    return report_service.my_statement(db, current_user["user_id"], year)


@router.get("/dues")
def dues(
    country: Optional[str] = Query(default=None, description="ISO code, or none = not entered"),
    min_months: int = Query(default=1, ge=1, le=240),
    search: Optional[str] = None,
    status: str = Query(default="active", description="active | inactive | all"),
    sort: str = Query(default="amount_desc", description="amount_desc | months_desc | name | code"),
    _admin: dict = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """Members with months not paid, most owed first."""
    return report_service.dues(db, country=country, min_months=min_months, search=search, status=status, sort=sort)


@router.get("/payments")
def payments(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=report_service.MAX_PAGE),
    sort: str = Query(default="month_desc"),
    type: Optional[str] = Query(default=None, description="monthly | campaign"),
    state: Optional[str] = Query(default=None, description="paid | waiting | not_paid | rejected"),
    month_from: Optional[str] = Query(default=None, description="yyyy-MM"),
    month_to: Optional[str] = Query(default=None, description="yyyy-MM"),
    campaign_id: Optional[int] = None,
    country: Optional[str] = None,
    member_id: Optional[int] = None,
    search: Optional[str] = None,
    method: Optional[str] = None,
    _admin: dict = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """Every payment record with filters, totals per state over all matches, and pages."""
    return report_service.payments(
        db, skip=skip, limit=limit, sort=sort, type=type, state=state, month_from=month_from,
        month_to=month_to, campaign_id=campaign_id, country=country, member_id=member_id,
        search=search, method=method,
    )


@router.get("/year-grid")
def year_grid(
    year: int,
    status: str = Query(default="active"),
    country: Optional[str] = None,
    _admin: dict = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """One row per member, one cell per month of the year: paid / waiting / not paid."""
    return report_service.year_grid(db, year, status=status, country=country)


@router.get("/paid-list")
def paid_list(
    year: int = Query(..., description="The year, January to December, e.g. 2025"),
    _admin: dict = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """The yearly paid list (Jan-Dec): month marks per member and campaign amounts in that year."""
    return report_service.paid_list(db, year)
