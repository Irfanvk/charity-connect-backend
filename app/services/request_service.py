from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Request, User
from app.schemas import RequestCreate, RequestUpdate


class RequestService:
    @staticmethod
    def _validate_request_type(request_type: str) -> str:
        allowed = {"approval", "question", "complaint", "suggestion", "other"}
        value = (request_type or "question").strip().lower()
        if value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid request_type. Allowed: {', '.join(sorted(allowed))}",
            )
        return value

    @staticmethod
    def _validate_priority(priority: str) -> str:
        allowed = {"low", "medium", "high"}
        value = (priority or "medium").strip().lower()
        if value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid priority. Allowed: {', '.join(sorted(allowed))}",
            )
        return value

    @staticmethod
    def _validate_status(status_value: str) -> str:
        allowed = {"pending", "in_progress", "resolved", "rejected"}
        value = (status_value or "pending").strip().lower()
        if value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status. Allowed: {', '.join(sorted(allowed))}",
            )
        return value

    @staticmethod
    def create_request(db: Session, user_id: int, payload: RequestCreate) -> Request:
        request_item = Request(
            created_by_user_id=user_id,
            request_type=RequestService._validate_request_type(payload.request_type),
            subject=payload.subject.strip(),
            message=payload.message.strip(),
            priority=RequestService._validate_priority(payload.priority),
            status="pending",
        )
        db.add(request_item)
        db.commit()
        db.refresh(request_item)
        return request_item

    @staticmethod
    def get_request(db: Session, request_id: int) -> Request:
        request_item = db.query(Request).filter(Request.id == request_id).first()
        if not request_item:
            raise HTTPException(status_code=404, detail="Request not found")
        return request_item

    @staticmethod
    def list_requests(
        db: Session,
        current_user: dict,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        query = db.query(Request)

        if current_user.get("role") not in ["admin", "superadmin"]:
            query = query.filter(Request.created_by_user_id == current_user["user_id"])

        sort_column = Request.created_at if sort_by != "updated_at" else Request.updated_at
        query = query.order_by(sort_column.desc() if sort_order == "desc" else sort_column.asc())

        return query.offset(skip).limit(limit).all()

    @staticmethod
    def update_request(db: Session, request_id: int, payload: RequestUpdate) -> Request:
        request_item = RequestService.get_request(db, request_id)

        updates = payload.dict(exclude_unset=True)
        if "status" in updates and updates["status"] is not None:
            updates["status"] = RequestService._validate_status(updates["status"])

        for key, value in updates.items():
            setattr(request_item, key, value)

        db.commit()
        db.refresh(request_item)
        return request_item

    @staticmethod
    def serialize_with_creator(request_items, db: Session):
        if not request_items:
            return []

        user_ids = {item.created_by_user_id for item in request_items}
        users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
        users_by_id = {u.id: u for u in users}

        serialized = []
        for item in request_items:
            creator = users_by_id.get(item.created_by_user_id)
            row = {
                "id": item.id,
                "created_by_user_id": item.created_by_user_id,
                "created_by": creator.email if creator and creator.email else creator.username if creator else None,
                "request_type": item.request_type,
                "subject": item.subject,
                "message": item.message,
                "priority": item.priority,
                "status": item.status,
                "admin_response": item.admin_response,
                "resolved_by": item.resolved_by,
                "resolved_at": item.resolved_at,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            serialized.append(row)

        return serialized
