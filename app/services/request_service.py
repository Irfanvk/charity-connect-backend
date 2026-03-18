import json
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AuditLog, Member, MemberRequest, RequestStatus, RequestType, User, Notification


class RequestService:
    @staticmethod
    def _member_for_user(db: Session, user_id: int) -> Member:
        member = db.query(Member).filter(Member.user_id == user_id).first()
        if not member:
            raise HTTPException(status_code=404, detail="Member profile not found")
        return member

    @staticmethod
    def _serialize(db: Session, item: MemberRequest) -> dict:
        member = db.query(Member).filter(Member.id == item.member_id).first()
        member_name = None
        member_code = None
        if member:
            member_code = member.member_code
            if member.user_id:
                user = db.query(User).filter(User.id == member.user_id).first()
                member_name = user.username if user else None

        return {
            "id": item.id,
            "member_id": item.member_id,
            "user_id": item.user_id,
            "request_type": item.request_type.value if hasattr(item.request_type, "value") else str(item.request_type),
            "status": item.status.value if hasattr(item.status, "value") else str(item.status),
            "subject": item.subject,
            "message": item.message,
            "requested_amount": item.requested_amount,
            "current_amount": item.current_amount,
            "requested_changes": item.requested_changes,
            "admin_notes": item.admin_notes,
            "rejection_reason": item.rejection_reason,
            "admin_id": item.admin_id,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "resolved_at": item.resolved_at,
            "member_name": member_name,
            "member_code": member_code,
        }

    @staticmethod
    def _notify_member(db: Session, user_id: int, title: str, message: str):
        db.add(
            Notification(
                user_id=user_id,
                title=title,
                message=message,
            )
        )

    @staticmethod
    def _approval_message(item: MemberRequest) -> str:
        request_type = item.request_type.value if hasattr(item.request_type, "value") else str(item.request_type)

        if request_type == RequestType.MONTHLY_AMOUNT_CHANGE.value:
            amount = float(item.requested_amount or 0)
            return (
                f"Your request to change your monthly contribution to "
                f"Rs {amount:,.0f} has been approved. "
                f"Your new monthly amount is now active."
            )

        if request_type == RequestType.PROFILE_UPDATE.value:
            changes = json.loads(item.requested_changes or "{}")
            fields = ", ".join(changes.keys()) if isinstance(changes, dict) and changes else "profile fields"
            return (
                f"Your profile update request ({fields}) has been approved "
                f"and your profile has been updated."
            )

        suffix = f" Admin note: {item.admin_notes}" if item.admin_notes else ""
        return f"Your {request_type.replace('_', ' ')} request has been approved.{suffix}"

    @staticmethod
    def _rejection_message(item: MemberRequest) -> str:
        request_type = item.request_type.value if hasattr(item.request_type, "value") else str(item.request_type)
        reason = item.rejection_reason or "No reason provided"
        return f"Your {request_type.replace('_', ' ')} request has not been approved. Reason: {reason}"

    @staticmethod
    def create_request(
        db: Session,
        current_user: dict,
        request_type: RequestType,
        subject: str | None,
        message: str,
        requested_amount: float | None,
        requested_changes: dict | None,
    ) -> dict:
        user_id = int(current_user.get("user_id"))
        member = RequestService._member_for_user(db, user_id)

        req_changes = None
        if request_type == RequestType.PROFILE_UPDATE:
            req_changes = json.dumps(requested_changes or {})

        current_amount = member.monthly_amount if request_type == RequestType.MONTHLY_AMOUNT_CHANGE else None

        item = MemberRequest(
            member_id=member.id,
            user_id=user_id,
            request_type=request_type,
            status=RequestStatus.PENDING,
            subject=(subject or "").strip() or None,
            message=(message or "").strip(),
            requested_amount=requested_amount,
            current_amount=current_amount,
            requested_changes=req_changes,
        )

        db.add(item)
        db.commit()
        db.refresh(item)
        return RequestService._serialize(db, item)

    @staticmethod
    def list_requests(
        db: Session,
        current_user: dict,
        skip: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        request_type: str | None = None,
    ) -> list[dict]:
        role = str(current_user.get("role", "")).lower()
        query = db.query(MemberRequest)

        if role not in ["admin", "superadmin"]:
            query = query.filter(MemberRequest.user_id == int(current_user.get("user_id")))

        if status_filter:
            query = query.filter(MemberRequest.status == status_filter)
        if request_type:
            query = query.filter(MemberRequest.request_type == request_type)

        items = query.order_by(MemberRequest.created_at.desc()).offset(skip).limit(limit).all()
        return [RequestService._serialize(db, item) for item in items]

    @staticmethod
    def get_request(db: Session, current_user: dict, request_id: int) -> dict:
        item = db.query(MemberRequest).filter(MemberRequest.id == request_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Request not found")

        role = str(current_user.get("role", "")).lower()
        if role not in ["admin", "superadmin"] and item.user_id != int(current_user.get("user_id")):
            raise HTTPException(status_code=403, detail="You are not allowed to access this request")

        return RequestService._serialize(db, item)

    @staticmethod
    def delete_request(db: Session, current_user: dict, request_id: int):
        item = db.query(MemberRequest).filter(MemberRequest.id == request_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Request not found")

        if item.user_id != int(current_user.get("user_id")):
            raise HTTPException(status_code=403, detail="You are not allowed to cancel this request")

        if (item.status.value if hasattr(item.status, "value") else str(item.status)) != RequestStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Only pending requests can be cancelled")

        db.delete(item)
        db.commit()

    @staticmethod
    def _apply_approval_changes(db: Session, item: MemberRequest):
        member = db.query(Member).filter(Member.id == item.member_id).first()
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")

        request_type = item.request_type.value if hasattr(item.request_type, "value") else str(item.request_type)

        if request_type == RequestType.MONTHLY_AMOUNT_CHANGE.value:
            if item.requested_amount is None:
                raise HTTPException(status_code=400, detail="requested_amount is required")
            member.monthly_amount = float(item.requested_amount)
            db.add(member)
            return

        if request_type == RequestType.PROFILE_UPDATE.value:
            changes = json.loads(item.requested_changes or "{}")
            if not isinstance(changes, dict):
                raise HTTPException(status_code=400, detail="Invalid requested_changes payload")

            user = db.query(User).filter(User.id == member.user_id).first()
            if "address" in changes:
                member.address = changes.get("address")
            if "notes" in changes:
                member.notes = changes.get("notes")
            if user and "phone" in changes:
                user.phone = changes.get("phone")
            if user and "full_name" in changes:
                user.username = changes.get("full_name")

            db.add(member)
            if user:
                db.add(user)

    @staticmethod
    def approve_request(db: Session, current_admin: dict, request_id: int, admin_notes: str | None = None) -> dict:
        role = str(current_admin.get("role", "")).lower()
        if role not in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Admin access required")

        item = db.query(MemberRequest).filter(MemberRequest.id == request_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Request not found")

        if (item.status.value if hasattr(item.status, "value") else str(item.status)) != RequestStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Only pending requests can be approved")

        RequestService._apply_approval_changes(db, item)

        item.status = RequestStatus.APPROVED
        item.admin_id = int(current_admin.get("user_id"))
        item.admin_notes = (admin_notes or "").strip() or None
        item.rejection_reason = None
        item.resolved_at = datetime.utcnow()
        db.add(item)

        RequestService._notify_member(
            db,
            user_id=item.user_id,
            title="Request Approved",
            message=RequestService._approval_message(item),
        )

        db.add(
            AuditLog(
                user_id=int(current_admin.get("user_id")),
                action="request_approved",
                entity_type="MemberRequest",
                entity_id=item.id,
                new_values=json.dumps({"status": "approved", "admin_notes": item.admin_notes}),
            )
        )

        db.commit()
        db.refresh(item)
        return RequestService._serialize(db, item)

    @staticmethod
    def reject_request(
        db: Session,
        current_admin: dict,
        request_id: int,
        rejection_reason: str,
        admin_notes: str | None = None,
    ) -> dict:
        role = str(current_admin.get("role", "")).lower()
        if role not in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Admin access required")

        item = db.query(MemberRequest).filter(MemberRequest.id == request_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Request not found")

        if (item.status.value if hasattr(item.status, "value") else str(item.status)) != RequestStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="Only pending requests can be rejected")

        reason = (rejection_reason or "").strip()
        if not reason:
            raise HTTPException(status_code=422, detail="rejection_reason is required")

        item.status = RequestStatus.REJECTED
        item.admin_id = int(current_admin.get("user_id"))
        item.admin_notes = (admin_notes or "").strip() or None
        item.rejection_reason = reason
        item.resolved_at = datetime.utcnow()
        db.add(item)

        RequestService._notify_member(
            db,
            user_id=item.user_id,
            title="Request Update",
            message=RequestService._rejection_message(item),
        )

        db.add(
            AuditLog(
                user_id=int(current_admin.get("user_id")),
                action="request_rejected",
                entity_type="MemberRequest",
                entity_id=item.id,
                new_values=json.dumps({"status": "rejected", "reason": reason}),
            )
        )

        db.commit()
        db.refresh(item)
        return RequestService._serialize(db, item)

    @staticmethod
    def admin_list_requests(
        db: Session,
        status_filter: str | None,
        request_type: str | None,
        member_id: int | None,
        skip: int,
        limit: int,
    ) -> dict:
        query = db.query(MemberRequest)

        if status_filter:
            query = query.filter(MemberRequest.status == status_filter)
        if request_type:
            query = query.filter(MemberRequest.request_type == request_type)
        if member_id:
            query = query.filter(MemberRequest.member_id == member_id)

        total = query.with_entities(func.count(MemberRequest.id)).scalar() or 0
        items = query.order_by(MemberRequest.created_at.desc()).offset(skip).limit(limit).all()

        return {
            "items": [RequestService._serialize(db, item) for item in items],
            "total": int(total),
            "skip": int(skip),
            "limit": int(limit),
        }
