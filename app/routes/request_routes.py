from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    MemberRequestAdminAction,
    MemberRequestCreate,
    MemberRequestListResponse,
    MemberRequestResponse,
)
from app.services.request_service import RequestService
from app.utils import get_current_admin, get_current_user

router = APIRouter(tags=["Requests"])


@router.post("/requests/", response_model=MemberRequestResponse, status_code=201)
def create_request(
    payload: MemberRequestCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return RequestService.create_request(
        db=db,
        current_user=current_user,
        request_type=payload.request_type,
        subject=payload.subject,
        message=payload.message,
        requested_amount=payload.requested_amount,
        requested_changes=payload.requested_changes,
    )


@router.get("/requests/", response_model=list[MemberRequestResponse])
def list_requests(
    status: str | None = Query(default=None),
    request_type: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return RequestService.list_requests(
        db,
        current_user=current_user,
        skip=skip,
        limit=limit,
        status_filter=status,
        request_type=request_type,
    )


@router.get("/requests/{request_id}", response_model=MemberRequestResponse)
def get_request(
    request_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return RequestService.get_request(db, current_user=current_user, request_id=request_id)


@router.delete("/requests/{request_id}", status_code=204)
def cancel_request(
    request_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    RequestService.delete_request(db, current_user=current_user, request_id=request_id)


@router.patch("/requests/{request_id}/approve", response_model=MemberRequestResponse)
def approve_request(
    request_id: int,
    payload: MemberRequestAdminAction,
    current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return RequestService.approve_request(
        db,
        current_admin=current_admin,
        request_id=request_id,
        admin_notes=payload.admin_notes,
    )


@router.patch("/requests/{request_id}/reject", response_model=MemberRequestResponse)
def reject_request(
    request_id: int,
    payload: MemberRequestAdminAction,
    current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return RequestService.reject_request(
        db,
        current_admin=current_admin,
        request_id=request_id,
        rejection_reason=payload.rejection_reason or "",
        admin_notes=payload.admin_notes,
    )


@router.get("/admin/requests/", response_model=MemberRequestListResponse)
def admin_requests(
    status: str | None = Query(default=None),
    request_type: str | None = Query(default=None),
    member_id: int | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return RequestService.admin_list_requests(
        db=db,
        status_filter=status,
        request_type=request_type,
        member_id=member_id,
        skip=skip,
        limit=limit,
    )
