import json
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import AuditLog, Member, Notification, Request, User
from app.schemas import MemberUpdate, RequestCreate, RequestUpdate
from app.services.member_service import MemberService


class RequestService:
    PROFILE_UPDATE_SUBJECT = "member_profile_update"
    PROFILE_UPDATE_PREFIX = "PROFILE_UPDATE_PAYLOAD::"
    CRITICAL_PROFILE_FIELDS = {"email", "phone", "full_name", "username", "father_name"}

    @staticmethod
    def _validate_request_type(request_type: str) -> str:
        allowed = {"approval", "question", "complaint", "suggestion", "payment_change", "other"}
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
        allowed = {"pending", "in_progress", "resolved", "approved", "rejected"}
        value = (status_value or "pending").strip().lower()
        if value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status. Allowed: {', '.join(sorted(allowed))}",
            )
        return value

    @staticmethod
    def _normalize_value(value):
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed if trimmed != "" else None
        return value

    @staticmethod
    def _member_snapshot(member: Member) -> dict:
        user = member.user
        snapshot = {
            "member_id": member.member_code,
            "member_code": member.member_code,
            "full_name": user.username if user else None,
            "phone": user.phone if user else None,
            "email": user.email if user else None,
            "monthly_amount": member.monthly_amount,
            "address": member.address,
            "status": member.status,
            "join_date": member.join_date,
        }
        return {k: RequestService._normalize_value(v) for k, v in snapshot.items()}

    @staticmethod
    def _extract_changed_fields(member: Member, update_payload: dict) -> dict:
        current = RequestService._member_snapshot(member)
        changed: dict = {}

        for key, raw_value in update_payload.items():
            if key not in current:
                continue

            new_value = RequestService._normalize_value(raw_value)
            old_value = RequestService._normalize_value(current.get(key))

            if isinstance(old_value, datetime) and isinstance(new_value, datetime):
                if old_value.replace(microsecond=0) != new_value.replace(microsecond=0):
                    changed[key] = raw_value
                continue

            if old_value != new_value:
                changed[key] = raw_value

        return changed

    @staticmethod
    def _build_profile_update_message(member_id: int, changed_fields: dict) -> str:
        payload = {
            "member_id": member_id,
            "changed_fields": changed_fields,
            "submitted_at": datetime.utcnow().isoformat(),
        }
        return f"{RequestService.PROFILE_UPDATE_PREFIX}{json.dumps(payload, default=str)}"

    @staticmethod
    def _parse_profile_update_message(message: str) -> dict | None:
        if not message or not message.startswith(RequestService.PROFILE_UPDATE_PREFIX):
            return None

        raw = message[len(RequestService.PROFILE_UPDATE_PREFIX):]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _get_member_for_requester(db: Session, user_id: int) -> Member:
        member = db.query(Member).filter(Member.user_id == user_id).first()
        if not member:
            raise HTTPException(status_code=404, detail="Member profile not found")
        return member

    @staticmethod
    def _profile_payload_view(request_item: Request) -> dict:
        data = RequestService._parse_profile_update_message(request_item.message)
        if not data:
            return {
                "is_profile_update": False,
                "profile_update_member_id": None,
                "profile_update_changed_fields": None,
                "profile_update_submitted_at": None,
            }

        changed_fields = data.get("changed_fields") if isinstance(data.get("changed_fields"), dict) else {}
        return {
            "is_profile_update": True,
            "profile_update_member_id": data.get("member_id"),
            "profile_update_changed_fields": changed_fields,
            "profile_update_submitted_at": data.get("submitted_at"),
        }

    @staticmethod
    def _create_profile_update_audit_log(
        db: Session,
        request_item: Request,
        actor_user_id: int,
        action: str,
    ):
        payload = RequestService._parse_profile_update_message(request_item.message) or {}
        changed_fields = payload.get("changed_fields") if isinstance(payload.get("changed_fields"), dict) else {}

        old_values = {
            "request_status": "pending",
            "request_type": request_item.request_type,
        }
        new_values = {
            "request_status": action,
            "request_type": request_item.request_type,
            "member_id": payload.get("member_id"),
            "changed_field_keys": sorted(changed_fields.keys()),
        }

        db.add(
            AuditLog(
                user_id=actor_user_id,
                action=f"profile_update_request_{action}",
                entity_type="Request",
                entity_id=request_item.id,
                old_values=json.dumps(old_values),
                new_values=json.dumps(new_values),
            )
        )

    @staticmethod
    def _notify_request_owner(db: Session, request_item: Request, status_value: str, admin_response: str | None):
        title = "Request update"
        message = f"Your request #{request_item.id} is now {status_value}."
        if admin_response:
            message = f"{message} Admin note: {admin_response}"

        db.add(
            Notification(
                user_id=request_item.created_by_user_id,
                title=title,
                message=message,
            )
        )

    @staticmethod
    def create_profile_update_request(db: Session, user_id: int, payload: MemberUpdate) -> Request:
        member = RequestService._get_member_for_requester(db, user_id)
        updates = payload.dict(exclude_unset=True)

        if not updates:
            raise HTTPException(status_code=400, detail="No profile fields provided for update")

        changed_fields = RequestService._extract_changed_fields(member, updates)
        if not changed_fields:
            raise HTTPException(status_code=400, detail="No profile changes detected")

        subject = f"{RequestService.PROFILE_UPDATE_SUBJECT}:{member.id}"
        message = RequestService._build_profile_update_message(member.id, changed_fields)

        request_item = Request(
            created_by_user_id=user_id,
            request_type="approval",
            subject=subject,
            message=message,
            priority="medium",
            status="pending",
        )
        db.add(request_item)
        db.commit()
        db.refresh(request_item)
        return request_item

    @staticmethod
    def _apply_profile_update_on_approval(
        db: Session,
        request_item: Request,
        approver_role: str,
    ):
        data = RequestService._parse_profile_update_message(request_item.message)
        if not data:
            raise HTTPException(status_code=400, detail="Invalid profile update payload in request")

        member_id = data.get("member_id")
        changed_fields = data.get("changed_fields") or {}
        if not member_id or not isinstance(changed_fields, dict):
            raise HTTPException(status_code=400, detail="Malformed profile update request payload")

        if approver_role != "superadmin":
            blocked_fields = [f for f in changed_fields.keys() if f in RequestService.CRITICAL_PROFILE_FIELDS]
            if blocked_fields:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "Only superadmin can approve updates for critical fields: "
                        + ", ".join(sorted(blocked_fields))
                    ),
                )

        member = MemberService.get_member(db, int(member_id))
        user = db.query(User).filter(User.id == member.user_id).first()

        new_code = MemberService.normalize_member_code(
            changed_fields.get("member_code") or changed_fields.get("member_id")
        )
        if new_code and new_code != member.member_code:
            duplicate_code = db.query(Member).filter(Member.member_code == new_code, Member.id != member.id).first()
            if duplicate_code:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Member code already in use",
                )
            member.member_code = new_code

        if "full_name" in changed_fields and user:
            full_name = RequestService._normalize_value(changed_fields.get("full_name"))
            if full_name:
                user.username = full_name

        if "email" in changed_fields and user:
            new_email = MemberService.normalize_contact(changed_fields.get("email"))
            if new_email and new_email != user.email:
                duplicate_email = db.query(User).filter(User.email == new_email, User.id != user.id).first()
                if duplicate_email:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Email already in use",
                    )
            user.email = new_email

        if "phone" in changed_fields and user:
            new_phone = MemberService.normalize_contact(changed_fields.get("phone"))
            if new_phone and new_phone != user.phone:
                duplicate_phone = db.query(User).filter(User.phone == new_phone, User.id != user.id).first()
                if duplicate_phone:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Phone already in use",
                    )
            user.phone = new_phone

        for key in ("monthly_amount", "address", "status", "join_date"):
            if key in changed_fields:
                setattr(member, key, changed_fields[key])

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
    def update_request(db: Session, request_id: int, payload: RequestUpdate, current_user: dict) -> Request:
        request_item = RequestService.get_request(db, request_id)
        previous_status = request_item.status

        updates = payload.dict(exclude_unset=True)
        if "status" in updates and updates["status"] is not None:
            updates["status"] = RequestService._validate_status(updates["status"])

        next_status = updates.get("status")
        is_profile_update = request_item.subject.startswith(f"{RequestService.PROFILE_UPDATE_SUBJECT}:")

        if next_status == "approved" and is_profile_update:
            RequestService._apply_profile_update_on_approval(
                db,
                request_item=request_item,
                approver_role=current_user.get("role", ""),
            )

        if next_status in {"approved", "rejected", "resolved"}:
            updates.setdefault("resolved_by", str(current_user.get("user_id")))
            updates.setdefault("resolved_at", datetime.utcnow())

        for key, value in updates.items():
            setattr(request_item, key, value)

        if next_status in {"approved", "rejected", "resolved"}:
            RequestService._notify_request_owner(
                db,
                request_item=request_item,
                status_value=next_status,
                admin_response=updates.get("admin_response") or request_item.admin_response,
            )

        if is_profile_update and previous_status != next_status and next_status in {"approved", "rejected"}:
            RequestService._create_profile_update_audit_log(
                db,
                request_item=request_item,
                actor_user_id=int(current_user.get("user_id")),
                action=next_status,
            )

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
            profile_payload = RequestService._profile_payload_view(item)
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
                "is_profile_update": profile_payload["is_profile_update"],
                "profile_update_member_id": profile_payload["profile_update_member_id"],
                "profile_update_changed_fields": profile_payload["profile_update_changed_fields"],
                "profile_update_submitted_at": profile_payload["profile_update_submitted_at"],
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            serialized.append(row)

        return serialized
