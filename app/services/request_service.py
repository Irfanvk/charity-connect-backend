import json
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AuditLog, Member, MemberRequest, RequestStatus, RequestType, User, Notification
from app.services.notification_service import NotificationService
from app.utils.file_handler import (
    delete_file,
    discard_pending_avatar,
    is_pending_avatar_url,
    promote_pending_avatar,
)
from app.utils.permissions import assert_not_own_user


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
            # The Python enum values are upper-case but the API contract (and every
            # frontend comparison) uses lower-case: pending | approved | rejected.
            "status": RequestService._status_value(item),
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
    def _status_value(item: MemberRequest) -> str:
        raw = item.status.value if hasattr(item.status, "value") else str(item.status)
        return str(raw).lower()

    @staticmethod
    def _avatar_url_in(item: MemberRequest):
        """Return (has_avatar_key, avatar_url) for a profile-update request."""
        try:
            changes = json.loads(item.requested_changes or "{}")
        except (TypeError, ValueError):
            return False, None
        if isinstance(changes, dict) and "avatar_url" in changes:
            return True, changes.get("avatar_url")
        return False, None

    @staticmethod
    def _notify_member(db: Session, user_id: int, title: str, message: str, request_id: int | None = None):
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            category="requests",
            link_url=f"/Requests?request={request_id}" if request_id else "/Requests",
            entity_type="member_request" if request_id else None,
            entity_id=request_id,
        )
        db.add(notification)
        return notification

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
            if isinstance(changes, dict) and changes:
                labels = []
                for key in changes.keys():
                    if key == "full_name":
                        labels.append("full name")
                    elif key == "avatar_url":
                        labels.append("profile photo")
                    else:
                        labels.append(key.replace("_", " "))
                fields = ", ".join(labels)
            else:
                fields = "profile fields"
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

    # -------------------------------------------------------------------------
    # Helper: safely coerce a string to a RequestStatus enum
    # Accepts both "pending" and "PENDING" from query params / frontend calls.
    # Raises HTTP 400 for unrecognised values instead of letting it crash at DB.
    # -------------------------------------------------------------------------
    @staticmethod
    def _parse_status(value: str) -> RequestStatus:
        try:
            return RequestStatus(value.strip().upper())
        except ValueError:
            valid = [e.value.lower() for e in RequestStatus]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{value}'. Valid values: {valid}",
            )
    # -------------------------------------------------------------------------
    # Helper: safely coerce a string to a RequestType enum (same logic).
    # -------------------------------------------------------------------------
    @staticmethod
    def _parse_request_type(value: str) -> RequestType:
        try:
            return RequestType(value.lower())
        except ValueError:
            valid = [e.value for e in RequestType]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid request_type '{value}'. Valid values: {valid}",
            )

    @staticmethod
    def _upsert_pending_avatar_request(
        db: Session,
        user_id: int,
        member: Member,
        changes: dict,
        subject: str | None,
        message: str,
    ) -> dict | None:
        """
        Keep at most ONE pending profile-photo request per member.

        If the member already has a pending request that changes avatar_url, it is
        updated in place with the newest photo (the superseded temporary upload is
        deleted) and its serialized form is returned. Returns None when there is no
        pending photo request, so the caller creates a new one.
        """
        new_avatar_url = changes.get("avatar_url")
        if new_avatar_url and not is_pending_avatar_url(new_avatar_url):
            raise HTTPException(
                status_code=400,
                detail="Profile photo must be uploaded through /files/upload/avatar",
            )

        # Serialize concurrent submissions (double clicks, retries) per member.
        db.query(Member).filter(Member.id == member.id).with_for_update().first()

        pending = (
            db.query(MemberRequest)
            .filter(
                MemberRequest.user_id == user_id,
                MemberRequest.request_type == RequestType.PROFILE_UPDATE,
                MemberRequest.status == RequestStatus.PENDING,
            )
            .order_by(MemberRequest.created_at.desc())
            .all()
        )
        target = next((r for r in pending if RequestService._avatar_url_in(r)[0]), None)
        if target is None:
            return None

        _, previous_avatar_url = RequestService._avatar_url_in(target)
        merged = json.loads(target.requested_changes or "{}")
        merged.update(changes)
        target.requested_changes = json.dumps(merged)
        target.subject = (subject or "").strip() or target.subject
        target.message = (message or "").strip() or target.message
        target.updated_at = datetime.utcnow()
        db.add(target)
        db.commit()
        db.refresh(target)

        if previous_avatar_url and previous_avatar_url != new_avatar_url:
            discard_pending_avatar(previous_avatar_url)

        return RequestService._serialize(db, target)

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
            changes = dict(requested_changes or {})
            if "avatar_url" in changes:
                existing = RequestService._upsert_pending_avatar_request(
                    db, user_id=user_id, member=member, changes=changes,
                    subject=subject, message=message,
                )
                if existing is not None:
                    return existing
            req_changes = json.dumps(changes)

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

        request_label = request_type.value.replace("_", " ")
        admins = db.query(User).filter(
            User.is_active == True,
            User.role.in_(["admin", "superadmin"]),
        ).all()
        admin_notifications = []
        for admin in admins:
            notification = Notification(
                user_id=admin.id,
                title="New Member Request",
                message=f"A member submitted a {request_label} request: {item.subject or 'No subject'}.",
                target_role=admin.role,
                category="admin_requests",
                link_url=f"/admin/requests?request={item.id}",
                entity_type="member_request",
                entity_id=item.id,
            )
            db.add(notification)
            admin_notifications.append(notification)

        db.commit()
        for admin_notification in admin_notifications:
            db.refresh(admin_notification)
            NotificationService.dispatch_notification(db, admin_notification)

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

        # Coerce to enum so PostgreSQL receives the exact enum value.
        if status_filter:
            query = query.filter(MemberRequest.status == RequestService._parse_status(status_filter))
        if request_type:
            query = query.filter(MemberRequest.request_type == RequestService._parse_request_type(request_type))

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

        if RequestService._status_value(item) != "pending":
            raise HTTPException(status_code=400, detail="Only pending requests can be cancelled")

        _, pending_avatar_url = RequestService._avatar_url_in(item)
        db.delete(item)
        db.commit()
        discard_pending_avatar(pending_avatar_url)

    @staticmethod
    def _apply_approval_changes(db: Session, item: MemberRequest) -> list[str]:
        """Apply the request's changes. Returns file URLs to delete after commit."""
        cleanup_urls: list[str] = []
        member = db.query(Member).filter(Member.id == item.member_id).first()
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")

        request_type = item.request_type.value if hasattr(item.request_type, "value") else str(item.request_type)

        if request_type == RequestType.MONTHLY_AMOUNT_CHANGE.value:
            if item.requested_amount is None:
                raise HTTPException(status_code=400, detail="requested_amount is required")
            member.monthly_amount = float(item.requested_amount)
            db.add(member)
            # Months not paid yet follow the new fee; paid ones keep what was paid.
            from app.services.challan_state import sync_unpaid_monthly_amounts
            sync_unpaid_monthly_amounts(db, member)
            return cleanup_urls

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
                user.full_name = changes.get("full_name")
            if user and "avatar_url" in changes:
                previous_avatar_url = user.avatar_url
                next_avatar_url = changes.get("avatar_url")
                if next_avatar_url:
                    # Move the temporary upload into permanent storage.
                    try:
                        next_avatar_url = promote_pending_avatar(next_avatar_url)
                    except RuntimeError as exc:
                        raise HTTPException(status_code=502, detail=str(exc)) from exc
                    changes["avatar_url"] = next_avatar_url
                    item.requested_changes = json.dumps(changes)
                user.avatar_url = next_avatar_url

                # Replaced/removed avatar is deleted only once the approval is committed.
                if previous_avatar_url and previous_avatar_url != next_avatar_url:
                    cleanup_urls.append(previous_avatar_url)

            if user and "email" in changes:
                new_email = str(changes.get("email") or "").strip().lower()
                if new_email:
                    taken = db.query(User).filter(
                        func.lower(User.email) == new_email, User.id != user.id
                    ).first()
                    if taken:
                        raise HTTPException(
                            status_code=409,
                            detail="This email is already used by another account. Reject the request with a reason.",
                        )
                    user.email = new_email

            if user and "username" in changes:
                new_username = str(changes.get("username") or "").strip()
                if new_username:
                    # Only apply if the username is still available
                    taken = db.query(User).filter(
                        User.username == new_username, User.id != user.id
                    ).first()
                    if not taken:
                        user.username = new_username

            db.add(member)
            if user:
                db.add(user)

        return cleanup_urls

    @staticmethod
    def approve_request(db: Session, current_admin: dict, request_id: int, admin_notes: str | None = None) -> dict:
        role = str(current_admin.get("role", "")).lower()
        if role not in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Admin access required")

        item = db.query(MemberRequest).filter(MemberRequest.id == request_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Request not found")

        if RequestService._status_value(item) != "pending":
            raise HTTPException(status_code=400, detail="Only pending requests can be approved")

        assert_not_own_user(current_admin, item.user_id, "approve")
        cleanup_urls = RequestService._apply_approval_changes(db, item)

        item.status = RequestStatus.APPROVED
        item.admin_id = int(current_admin.get("user_id"))
        item.admin_notes = (admin_notes or "").strip() or None
        item.rejection_reason = None
        item.resolved_at = datetime.utcnow()
        db.add(item)

        created_notification = RequestService._notify_member(
            db,
            user_id=item.user_id,
            title="Request Approved",
            message=RequestService._approval_message(item),
            request_id=item.id,
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
        for url in cleanup_urls:
            delete_file(url)  # best effort
        db.refresh(item)
        db.refresh(created_notification)
        NotificationService.dispatch_notification(db, created_notification)
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

        if RequestService._status_value(item) != "pending":
            raise HTTPException(status_code=400, detail="Only pending requests can be rejected")

        assert_not_own_user(current_admin, item.user_id, "reject")
        reason = (rejection_reason or "").strip()
        if not reason:
            raise HTTPException(status_code=422, detail="rejection_reason is required")

        item.status = RequestStatus.REJECTED
        item.admin_id = int(current_admin.get("user_id"))
        item.admin_notes = (admin_notes or "").strip() or None
        item.rejection_reason = reason
        item.resolved_at = datetime.utcnow()
        db.add(item)

        created_notification = RequestService._notify_member(
            db,
            user_id=item.user_id,
            title="Request Update",
            message=RequestService._rejection_message(item),
            request_id=item.id,
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
        _, pending_avatar_url = RequestService._avatar_url_in(item)
        discard_pending_avatar(pending_avatar_url)
        db.refresh(item)
        db.refresh(created_notification)
        NotificationService.dispatch_notification(db, created_notification)
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

        # Coerce to enum so PostgreSQL receives the exact enum value.
        if status_filter:
            query = query.filter(MemberRequest.status == RequestService._parse_status(status_filter))
        if request_type:
            query = query.filter(MemberRequest.request_type == RequestService._parse_request_type(request_type))
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