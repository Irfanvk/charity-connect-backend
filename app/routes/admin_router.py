from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json
from datetime import datetime

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
)
from app.models.models import (
    BulkChallanGroup,
    Challan,
    ChallanStatus,
    Member,
    User,
    AuditLog,
    UserRole,
)
from app.utils.auth import get_current_user


router = APIRouter(prefix="/admin", tags=["admin"])


# GET PENDING BULK OPERATIONS (ADMIN ONLY)
@router.get("/bulk-pending-review", response_model=BulkChallanListResponse)
def get_pending_bulk_operations(
    days: int = 7,
    sort_by: str = "created_at",
    order: str = "desc",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all pending bulk challan operations for admin review.
    
    Admin only endpoint.
    Query Parameters:
    - days: Filter operations created in the last N days (default: 7)
    - sort_by: Sort by 'created_at', 'member_name', or 'total_amount' (default: created_at)
    - order: Sort order 'asc' or 'desc' (default: desc)
    """
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPERADMIN]:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Query pending bulk groups
    query = db.query(BulkChallanGroup).filter(
        BulkChallanGroup.status == "pending_approval"
    )
    
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
    
    bulk_groups = query.all()
    
    items = []
    for group in bulk_groups:
        member = db.query(Member).filter(Member.id == group.member_id).first()
        user = db.query(User).filter(User.id == member.user_id).first() if member else None
        created_by = db.query(User).filter(User.id == group.created_by_user_id).first()
        
        months = json.loads(group.months_list) if group.months_list else []
        proof_url = f"http://localhost:8000/uploads/proofs/{group.proof_file_id}.jpg"  # Construct URL
        
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
        pending=len(bulk_groups),
        bulk_operations=items
    )


# GET BULK OPERATION DETAILS (ADMIN ONLY)
@router.get("/bulk/{bulk_group_id}", response_model=BulkChallanDetails)
def get_bulk_challan_details(
    bulk_group_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get detailed information about a specific bulk operation.
    
    Admin only endpoint.
    """
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPERADMIN]:
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
    
    # Get linked challans
    linked_challans = []
    for challan_id in challan_ids:
        challan = db.query(Challan).filter(Challan.id == challan_id).first()
        if challan:
            linked_challans.append(BulkChallanLinkedChallan(
                challan_id=challan.id,
                month=challan.month,
                amount=challan.amount,
                status=challan.status,
                created_at=challan.created_at,
            ))
    
    proof_url = f"http://localhost:8000/uploads/proofs/{bulk_group.proof_file_id}.jpg"
    
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
    current_user: User = Depends(get_current_user),
):
    """
    Approve all challans in a bulk group in a single action.
    
    Admin only endpoint.
    """
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPERADMIN]:
        raise HTTPException(status_code=403, detail="Admin access required")
    
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
                challan.approved_by_admin_id = current_user.id
                challan.approved_at = datetime.utcnow()
        
        # Update bulk group
        bulk_group.status = "approved"
        bulk_group.approved_by_admin_id = current_user.id
        bulk_group.approved_at = datetime.utcnow()
        bulk_group.admin_notes = request.admin_notes
        
        db.commit()
        
        # Create audit log
        months = json.loads(bulk_group.months_list) if bulk_group.months_list else []
        audit_log = AuditLog(
            user_id=current_user.id,
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
        
        return BulkChallanApproveResponse(
            bulk_group_id=bulk_group.bulk_group_id,
            status="approved",
            approved_challans=len(challan_ids),
            challan_ids=challan_ids,
            months_approved=months,
            total_amount_approved=bulk_group.total_amount,
            approved_by=current_user.email,
            approved_at=datetime.utcnow(),
            admin_notes=request.admin_notes,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# REJECT BULK CHALLANS (ADMIN ONLY)
@router.patch("/bulk/{bulk_group_id}/reject", response_model=BulkChallanRejectResponse)
def reject_bulk_challans(
    bulk_group_id: str,
    request: BulkChallanReject,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Reject all challans in a bulk group and delete associated records.
    
    Admin only endpoint.
    """
    
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPERADMIN]:
        raise HTTPException(status_code=403, detail="Admin access required")
    
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
        
        db.commit()
        
        # Create audit log
        months = json.loads(bulk_group.months_list) if bulk_group.months_list else []
        audit_log = AuditLog(
            user_id=current_user.id,
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
        
        return BulkChallanRejectResponse(
            bulk_group_id=bulk_group.bulk_group_id,
            status="rejected",
            rejected_challans=len(challan_ids),
            challan_ids=challan_ids,
            rejected_at=datetime.utcnow(),
            reason=request.reason,
            rejected_by=current_user.email,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
