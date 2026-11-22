"""Receipts for approved payments, and the public page that confirms a receipt is genuine."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import BulkChallanGroup, Challan, Member
from app.services import receipt_service
from app.utils.auth import get_current_staff, get_current_user, is_staff

router = APIRouter(prefix="/receipts", tags=["Receipts"])


@router.get("")
def list_receipts(
    search: Optional[str] = Query(default=None, max_length=100),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    kind: str = Query(default="all", pattern="^(all|monthly|campaign)$"),
    method: Optional[str] = Query(default=None, max_length=30),
    checked_by: Optional[str] = Query(default=None, max_length=20),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    _admin: dict = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """Admins: every receipt (approved payment) with search and filters, newest first."""
    return receipt_service.list_receipts(db, search=search, date_from=date_from, date_to=date_to, kind=kind,
                                         method=method, checked_by=checked_by, skip=skip, limit=limit)


def _may_see(db: Session, current_user: dict, member_id: int) -> None:
    if is_staff(current_user):
        return
    own = db.query(Member.id).filter(Member.user_id == current_user.get("user_id")).scalar()
    if own != member_id:
        raise HTTPException(status_code=403, detail="Not allowed to see this receipt")


def _ready(data: dict) -> dict:
    if not data["valid"]:
        raise HTTPException(status_code=409, detail="The receipt is ready once the payment is approved.")
    return data


@router.get("/challan/{challan_id}")
def challan_receipt(challan_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    challan = db.query(Challan).filter(Challan.id == challan_id).first()
    if challan is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    _may_see(db, current_user, challan.member_id)
    return _ready(receipt_service.for_challan(db, challan))


@router.get("/bulk/{bulk_group_id}")
def bulk_receipt(bulk_group_id: str, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    group = db.query(BulkChallanGroup).filter(BulkChallanGroup.bulk_group_id == bulk_group_id).first()
    if group is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    _may_see(db, current_user, group.member_id)
    return _ready(receipt_service.for_group(db, group))


@router.get("/verify/{token}")
def verify_receipt(token: str, db: Session = Depends(get_db)):
    """Public: is this receipt genuine? Shows only what is printed on it, with a shortened name."""
    return receipt_service.public_view(db, token)
