from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import RequestCreate, RequestResponse, RequestUpdate
from app.services.request_service import RequestService
from app.utils import get_current_admin, get_current_user


router = APIRouter(prefix="/requests", tags=["Requests"])


@router.get("/", response_model=List[RequestResponse])
def get_requests(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = RequestService.list_requests(
        db,
        current_user=current_user,
        skip=skip,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return RequestService.serialize_with_creator(items, db)


@router.post("/", response_model=RequestResponse, status_code=201)
def create_request(
    payload: RequestCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = RequestService.create_request(db, current_user["user_id"], payload)
    return RequestService.serialize_with_creator([item], db)[0]


@router.get("/{request_id}", response_model=RequestResponse)
def get_request(
    request_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = RequestService.get_request(db, request_id)
    if current_user.get("role") not in ["admin", "superadmin"] and item.created_by_user_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="You are not allowed to access this request")

    return RequestService.serialize_with_creator([item], db)[0]


@router.put("/{request_id}", response_model=RequestResponse)
def update_request(
    request_id: int,
    payload: RequestUpdate,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    item = RequestService.update_request(db, request_id, payload)
    return RequestService.serialize_with_creator([item], db)[0]
