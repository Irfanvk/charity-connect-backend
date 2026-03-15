from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import json
from datetime import datetime, timedelta
from pathlib import Path

from app.database import get_db
from app.schemas.schemas import (
    BulkChallanListResponse,
    BulkChallanListItem,
    BulkChallanApprove,
    BulkChallanApproveResponse,
    BulkChallanReject,
    BulkChallanRejectResponse,
    BulkChallanDetails,
    BulkChallanLinkedChallan,
    SystemWipeRequest,
    SystemWipeResponse,
)
from app.models.models import (
    BulkChallanGroup,
    Challan,
    ChallanStatus,
    Member,
    User,
    AuditLog,
    Invite,
    Campaign,
    Notification,
    Request,
)
from app.utils.auth import get_current_user, get_current_superadmin, verify_password


router = APIRouter(prefix="/admin", tags=["admin"])


def _is_admin_role(current_user: dict) -> bool:
    role = str(current_user.get("role", "")).lower()
    return role in ["admin", "superadmin"]


def _build_proof_url(proof_file_id: str | None) -> str | None:
    if not proof_file_id:
        return None
    cleaned = str(proof_file_id).strip()
    if not cleaned:
        return None
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    if cleaned.startswith("/"):
        return cleaned
    if cleaned.startswith("uploads/"):
        return f"/{cleaned}"
    return f"/uploads/proofs/{cleaned}"


@router.post("/system/wipe", response_model=SystemWipeResponse)
def wipe_system_data(
    payload: SystemWipeRequest,
    current_user: dict = Depends(get_current_superadmin),
    db: Session = Depends(get_db),
):
    """
    Superadmin-only destructive wipe.

    Deletes all operational data and storage files, while preserving:
    - superadmin users always
    - admin users optionally (keep_admins=true)
    """
    _ = current_user

    if (payload.confirm_text or "").strip().upper() != "WIPE":
        raise HTTPException(status_code=400, detail="Invalid confirmation text. Type WIPE to proceed.")

    purpose = (payload.purpose or "").strip()
    if not purpose:
        raise HTTPException(status_code=400, detail="Purpose is required before wipe.")

    if len(payload.password_attempts or []) != 3:
        raise HTTPException(status_code=400, detail="Exactly 3 password entries are required.")

    actor = db.query(User).filter(User.id == current_user.get("user_id")).first()
    if not actor:
        raise HTTPException(status_code=404, detail="Acting superadmin not found.")

    for attempt in payload.password_attempts:
        raw_attempt = str(attempt or "").strip()
        if not raw_attempt:
            raise HTTPException(status_code=400, detail="All password confirmation fields are required.")
        if not verify_password(raw_attempt, actor.password_hash):
            raise HTTPException(status_code=403, detail="Password verification failed.")

    keep_roles = ["superadmin"]
    if payload.keep_admins:
        keep_roles.append("admin")

    try:
        # Counts before deletion for response
        members_deleted = db.query(Member).count()
        challans_deleted = db.query(Challan).count()
        campaigns_deleted = db.query(Campaign).count()
        invites_deleted = db.query(Invite).count()
        notifications_deleted = db.query(Notification).count()
        requests_deleted = db.query(Request).count()
        audit_logs_deleted = db.query(AuditLog).count()
        bulk_groups_deleted = db.query(BulkChallanGroup).count()
        users_deleted = db.query(User).filter(~User.role.in_(keep_roles)).count()

        # Delete in FK-safe order
        db.query(Challan).delete(synchronize_session=False)
        db.query(BulkChallanGroup).delete(synchronize_session=False)
        db.query(Member).delete(synchronize_session=False)
        db.query(Invite).delete(synchronize_session=False)
        db.query(Notification).delete(synchronize_session=False)
        db.query(Request).delete(synchronize_session=False)
        db.query(Campaign).delete(synchronize_session=False)
        db.query(AuditLog).delete(synchronize_session=False)

        # Preserve only superadmin (+ admins if requested)
        db.query(User).filter(~User.role.in_(keep_roles)).delete(synchronize_session=False)
        db.commit()

        # Re-create one audit record after wipe for traceability
        deleted_at = datetime.utcnow().isoformat()

        wipe_audit = AuditLog(
            user_id=current_user.get("user_id"),
            action="system_wipe",
            entity_type="System",
            entity_id=0,
            new_values=json.dumps(
                {
                    "purpose": purpose,
                    "deleted_at": deleted_at,
                    # Store only user_id + role — no username/email in audit log
                    # to avoid embedding PII inside JSON blobs that may be
                    # exported or inspected outside a proper access-controlled view.
                    "performed_by": {
                        "user_id": actor.id,
                        "role": str(actor.role),
                    },
                    "keep_admins": payload.keep_admins,
                    "wipe_files": payload.wipe_files,
                    "users_deleted": users_deleted,
                    "members_deleted": members_deleted,
                    "challans_deleted": challans_deleted,
                    "campaigns_deleted": campaigns_deleted,
                }
            ),
        )
        db.add(wipe_audit)
        db.commit()

        files_deleted = 0
        if payload.wipe_files:
            uploads_dir = Path(__file__).resolve().parent.parent / "uploads"
            if uploads_dir.exists():
                for file_path in uploads_dir.rglob("*"):
                    if file_path.is_file():
                        file_path.unlink(missing_ok=True)
                        files_deleted += 1

        kept_superadmins = db.query(User).filter(User.role == "superadmin").count()
        kept_admins = db.query(User).filter(User.role == "admin").count()

        return SystemWipeResponse(
            users_deleted=users_deleted,
            members_deleted=members_deleted,
            challans_deleted=challans_deleted,
            campaigns_deleted=campaigns_deleted,
            invites_deleted=invites_deleted,
            notifications_deleted=notifications_deleted,
            requests_deleted=requests_deleted,
            audit_logs_deleted=audit_logs_deleted,
            bulk_groups_deleted=bulk_groups_deleted,
            files_deleted=files_deleted,
            kept_superadmins=kept_superadmins,
            kept_admins=kept_admins,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Wipe operation failed: {e}") from e


# GET PENDING BULK OPERATIONS (ADMIN ONLY)
@router.get("/bulk-pending-review", response_model=BulkChallanListResponse)
def get_pending_bulk_operations(
    days: int = Query(default=7, ge=1, le=365),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    sort_by: str = "created_at",
    order: str = "desc",
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Get all pending bulk challan operations for admin review.
    
    Admin only endpoint.
    Query Parameters:
    - days: Filter operations created in the last N days (default: 7)
    - sort_by: Sort by 'created_at', 'member_name', or 'total_amount' (default: created_at)
    - order: Sort order 'asc' or 'desc' (default: desc)
    """
    
    if not _is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Query pending bulk groups
    cutoff = datetime.utcnow() - timedelta(days=days)
    base_query = db.query(BulkChallanGroup).filter(
        BulkChallanGroup.status == "pending_approval",
        BulkChallanGroup.created_at >= cutoff,
    )
    query = base_query
    
    # Apply sorting
    if sort_by == "member_name":
        query = query.join(Member).join(User, Member.user_id == User.id)
        if order == "asc":
            query = query.order_by(User.username.asc())
        else:
            query = query.order_by(User.username.desc())
    elif sort_by == "total_amount":
        if order == "asc":
            query = query.order_by(BulkChallanGroup.total_amount.asc())
        else:
            query = query.order_by(BulkChallanGroup.total_amount.desc())
    else:  # created_at
        if order == "asc":
            query = query.order_by(BulkChallanGroup.created_at.asc())
        else:
            query = query.order_by(BulkChallanGroup.created_at.desc())
    
    total_pending = base_query.count()

    bulk_groups = query.offset(skip).limit(limit).all()

    member_ids = {group.member_id for group in bulk_groups}
    creator_ids = {group.created_by_user_id for group in bulk_groups}

    members = (
        db.query(Member)
        .filter(Member.id.in_(member_ids))
        .all()
        if member_ids
        else []
    )
    members_by_id = {member.id: member for member in members}

    user_ids = {member.user_id for member in members}
    user_ids.update(creator_ids)
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    users_by_id = {user.id: user for user in users}
    
    items = []
    for group in bulk_groups:
        member = members_by_id.get(group.member_id)
        user = users_by_id.get(member.user_id) if member else None
        created_by = users_by_id.get(group.created_by_user_id)
        
        months = json.loads(group.months_list) if group.months_list else []
        proof_url = _build_proof_url(group.proof_file_id)
        
        item = BulkChallanListItem(
            bulk_group_id=group.bulk_group_id,
            member_id=group.member_id,
            member_name=user.username if user else None,
            member_email=user.email if user else None,
            months=months,
            months_count=len(months),
            total_amount=group.total_amount,
            amount_per_month=group.amount_per_month,
            proof_file_id=group.proof_file_id,
            proof_url=proof_url,
            status=group.status,
            created_at=group.created_at,
            created_by_email=created_by.email if created_by else None,
            notes=group.notes,
        )
        items.append(item)
    
    return BulkChallanListResponse(
        pending=total_pending,
        bulk_operations=items
    )


# GET BULK OPERATION DETAILS (ADMIN ONLY)
@router.get("/bulk/{bulk_group_id}", response_model=BulkChallanDetails)
def get_bulk_challan_details(
    bulk_group_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Get detailed information about a specific bulk operation.
    
    Admin only endpoint.
    """
    
    if not _is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    bulk_group = db.query(BulkChallanGroup).filter(
        BulkChallanGroup.bulk_group_id == bulk_group_id
    ).first()
    
    if not bulk_group:
        raise HTTPException(status_code=404, detail="Bulk operation not found")
    
    member = db.query(Member).filter(Member.id == bulk_group.member_id).first()
    user = db.query(User).filter(User.id == member.user_id).first() if member else None
    created_by = db.query(User).filter(User.id == bulk_group.created_by_user_id).first()
    approved_by = db.query(User).filter(User.id == bulk_group.approved_by_admin_id).first() if bulk_group.approved_by_admin_id else None
    
    months = json.loads(bulk_group.months_list) if bulk_group.months_list else []
    challan_ids = json.loads(bulk_group.challan_ids_list) if bulk_group.challan_ids_list else []
    
    # Get linked challans using a single query
    linked_challans = []
    linked = db.query(Challan).filter(Challan.id.in_(challan_ids)).all() if challan_ids else []
    linked_by_id = {challan.id: challan for challan in linked}
    for challan_id in challan_ids:
        challan = linked_by_id.get(challan_id)
        if challan is not None:
            linked_challans.append(BulkChallanLinkedChallan(
                challan_id=challan.id,
                month=challan.month,
                amount=challan.amount,
                status=challan.status,
                created_at=challan.created_at,
            ))
    
    proof_url = _build_proof_url(bulk_group.proof_file_id)
    
    return BulkChallanDetails(
        bulk_group_id=bulk_group.bulk_group_id,
        member_id=bulk_group.member_id,
        member_name=user.username if user else None,
        member_email=user.email if user else None,
        months=months,
        total_amount=bulk_group.total_amount,
        amount_per_month=bulk_group.amount_per_month,
        proof_file_id=bulk_group.proof_file_id,
        proof_url=proof_url,
        status=bulk_group.status,
        created_at=bulk_group.created_at,
        created_by_email=created_by.email if created_by else None,
        approved_at=bulk_group.approved_at,
        approved_by=approved_by.email if approved_by else None,
        admin_notes=bulk_group.admin_notes,
        notes=bulk_group.notes,
        linked_challans=linked_challans,
    )


# APPROVE BULK CHALLANS (ADMIN ONLY)
@router.patch("/bulk/{bulk_group_id}/approve", response_model=BulkChallanApproveResponse)
def approve_bulk_challans(
    bulk_group_id: str,
    request: BulkChallanApprove,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Approve all challans in a bulk group in a single action.
    
    Admin only endpoint.
    """
    
    if not _is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    admin_user_id = current_user.get("user_id")
    admin_user = db.query(User).filter(User.id == admin_user_id).first()
    
    if not request.approved:
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["body", "approved"], "msg": "Must be true to approve", "type": "value_error"}]
        )
    
    bulk_group = db.query(BulkChallanGroup).filter(
        BulkChallanGroup.bulk_group_id == bulk_group_id
    ).first()
    
    if not bulk_group:
        raise HTTPException(status_code=404, detail="Bulk operation not found")
    
    if bulk_group.status == "approved":
        raise HTTPException(status_code=400, detail="Bulk operation already approved")
    
    if bulk_group.status == "rejected":
        raise HTTPException(status_code=400, detail="Cannot approve rejected bulk operation")
    
    try:
        # Update all linked challans
        challan_ids = json.loads(bulk_group.challan_ids_list) if bulk_group.challan_ids_list else []
        
        for challan_id in challan_ids:
            challan = db.query(Challan).filter(Challan.id == challan_id).first()
            if challan:
                challan.status = ChallanStatus.APPROVED
                challan.approved_by_admin_id = admin_user_id
                challan.approved_at = datetime.utcnow()
        
        # Update bulk group
        bulk_group.status = "approved"
        bulk_group.approved_by_admin_id = admin_user_id
        bulk_group.approved_at = datetime.utcnow()
        bulk_group.admin_notes = request.admin_notes
        
        months = json.loads(bulk_group.months_list) if bulk_group.months_list else []
        
        # Create audit log
        audit_log = AuditLog(
            user_id=admin_user_id,
            action="bulk_approve",
            entity_type="BulkChallanGroup",
            entity_id=bulk_group.id,
            new_values=json.dumps({
                "status": "approved",
                "months": months,
                "total_amount": bulk_group.total_amount,
                "admin_notes": request.admin_notes
            })
        )
        db.add(audit_log)
        db.commit()
        db.refresh(bulk_group)
        
        return BulkChallanApproveResponse(
            bulk_group_id=bulk_group.bulk_group_id,
            status="approved",
            approved_challans=len(challan_ids),
            challan_ids=challan_ids,
            months_approved=months,
            total_amount_approved=bulk_group.total_amount,
            approved_by=admin_user.email if admin_user else None,
            approved_at=bulk_group.approved_at,
            admin_notes=request.admin_notes,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e


# REJECT BULK CHALLANS (ADMIN ONLY)
@router.patch("/bulk/{bulk_group_id}/reject", response_model=BulkChallanRejectResponse)
def reject_bulk_challans(
    bulk_group_id: str,
    request: BulkChallanReject,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Reject all challans in a bulk group and delete associated records.
    
    Admin only endpoint.
    """
    
    if not _is_admin_role(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    admin_user_id = current_user.get("user_id")
    admin_user = db.query(User).filter(User.id == admin_user_id).first()
    
    if not request.reason:
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["body", "reason"], "msg": "Rejection reason required", "type": "value_error"}]
        )
    
    if request.action not in ["delete"]:
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["body", "action"], "msg": "Invalid action. Must be 'delete'", "type": "value_error"}]
        )
    
    bulk_group = db.query(BulkChallanGroup).filter(
        BulkChallanGroup.bulk_group_id == bulk_group_id
    ).first()
    
    if not bulk_group:
        raise HTTPException(status_code=404, detail="Bulk operation not found")
    
    if bulk_group.status == "approved":
        raise HTTPException(status_code=400, detail="Cannot reject approved bulk operation")
    
    try:
        # Delete all linked challans if action is "delete"
        challan_ids = json.loads(bulk_group.challan_ids_list) if bulk_group.challan_ids_list else []
        
        if request.action == "delete":
            for challan_id in challan_ids:
                challan = db.query(Challan).filter(Challan.id == challan_id).first()
                if challan:
                    db.delete(challan)
        
        # Update bulk group
        bulk_group.status = "rejected"
        bulk_group.rejection_reason = request.reason
        bulk_group.rejected_at = datetime.utcnow()
        
        months = json.loads(bulk_group.months_list) if bulk_group.months_list else []
        
        # Create audit log
        audit_log = AuditLog(
            user_id=admin_user_id,
            action="bulk_reject",
            entity_type="BulkChallanGroup",
            entity_id=bulk_group.id,
            new_values=json.dumps({
                "status": "rejected",
                "reason": request.reason,
                "months": months
            })
        )
        db.add(audit_log)
        db.commit()
        db.refresh(bulk_group)
        
        return BulkChallanRejectResponse(
            bulk_group_id=bulk_group.bulk_group_id,
            status="rejected",
            rejected_challans=len(challan_ids),
            challan_ids=challan_ids,
            rejected_at=bulk_group.rejected_at,
            reason=request.reason,
            rejected_by=admin_user.email if admin_user else None,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e
