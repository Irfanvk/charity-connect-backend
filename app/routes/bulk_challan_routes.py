from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import uuid
import json
from datetime import datetime
from typing import List

from app.database import get_db
from app.schemas.schemas import (
    BulkChallanCreate,
    BulkChallanResponse,
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
    ChallanType,
    ChallanStatus,
    Member,
    User,
    AuditLog,
    UserRole,
)
from app.utils.auth import get_current_user


router = APIRouter(prefix="/challans", tags=["bulk-challans"])


# BULK CREATE CHALLAN
@router.post("/bulk-create", response_model=BulkChallanResponse, status_code=201)
def bulk_create_challans(
    request: BulkChallanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create multiple challans for different months linked to single proof.
    
    - Members: Create only for self
    - Admins: Can create for any active member
    """
    
    # Validate months list
    if not request.months or len(request.months) == 0:
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["body", "months"], "msg": "Months list cannot be empty", "type": "value_error"}]
        )
    
    # Validate amount
    if request.amount_per_month <= 0:
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["body", "amount_per_month"], "msg": "Amount must be greater than 0", "type": "value_error"}]
        )
    
    # Validate months format and check for duplicates
    months_set = set()
    for month in request.months:
        if not month or len(month) != 7 or month[4] != "-":
            raise HTTPException(
                status_code=422,
                detail=[{"loc": ["body", "months"], "msg": f"Invalid month format: {month}. Use YYYY-MM", "type": "value_error"}]
            )
        if month in months_set:
            raise HTTPException(
                status_code=422,
                detail=[{"loc": ["body", "months"], "msg": f"Duplicate month: {month}", "type": "value_error"}]
            )
        months_set.add(month)
    
    # Determine member_id
    if current_user.role == UserRole.MEMBER:
        # Member can only create for self
        if request.member_id and request.member_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Members can only create bulk challans for themselves"
            )
        member = db.query(Member).filter(Member.user_id == current_user.id).first()
        if not member:
            raise HTTPException(status_code=404, detail="Member record not found")
        member_id = member.id
    else:
        # Admin/Superadmin can create for any member
        if not request.member_id:
            raise HTTPException(
                status_code=422,
                detail=[{"loc": ["body", "member_id"], "msg": "member_id required for admin", "type": "value_error"}]
            )
        member = db.query(Member).filter(Member.id == request.member_id).first()
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        member_id = request.member_id
    
    # Check member is active
    if member.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Cannot create bulk challan for inactive member"
        )
    
    # Verify proof file exists (basic check - in production, verify with file service)
    if not request.proof_file_id:
        raise HTTPException(
            status_code=422,
            detail=[{"loc": ["body", "proof_file_id"], "msg": "Proof file ID required", "type": "value_error"}]
        )
    
    # Generate bulk group ID
    bulk_group_id = f"bulk-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8]}"
    
    # Create individual challans
    challan_ids = []
    total_amount = request.amount_per_month * len(request.months)
    
    try:
        for month in request.months:
            challan = Challan(
                member_id=member_id,
                type=ChallanType.MONTHLY,
                month=month,
                amount=request.amount_per_month,
                status=ChallanStatus.PENDING,
                bulk_group_id=bulk_group_id,
                proof_path=None,  # Will be set when proof is provided
                created_at=datetime.utcnow(),
            )
            db.add(challan)
            db.flush()  # Get the ID
            challan_ids.append(challan.id)
        
        # Create bulk group record
        bulk_group = BulkChallanGroup(
            bulk_group_id=bulk_group_id,
            member_id=member_id,
            amount_per_month=request.amount_per_month,
            total_amount=total_amount,
            proof_file_id=request.proof_file_id,
            status="pending_approval",
            months_list=json.dumps(request.months),
            challan_ids_list=json.dumps(challan_ids),
            created_by_user_id=current_user.id,
            notes=request.notes,
            created_at=datetime.utcnow(),
        )
        db.add(bulk_group)
        db.commit()
        
        # Create audit log
        audit_log = AuditLog(
            user_id=current_user.id,
            action="bulk_create",
            entity_type="BulkChallanGroup",
            entity_id=bulk_group.id,
            new_values=json.dumps({
                "bulk_group_id": bulk_group_id,
                "months": request.months,
                "total_amount": total_amount,
                "challan_ids": challan_ids
            })
        )
        db.add(audit_log)
        db.commit()
        
        return BulkChallanResponse(
            bulk_group_id=bulk_group_id,
            member_id=member_id,
            created_challans=len(challan_ids),
            challan_ids=challan_ids,
            months=request.months,
            total_amount=total_amount,
            proof_file_id=request.proof_file_id,
            status="pending_approval",
            created_at=datetime.utcnow(),
            notes=request.notes,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# GET PENDING BULK OPERATIONS (ADMIN ONLY)
@router.get("/admin/bulk-pending-review", response_model=BulkChallanListResponse)
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
@router.get("/admin/bulk/{bulk_group_id}", response_model=BulkChallanDetails)
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
@router.patch("/admin/bulk/{bulk_group_id}/approve", response_model=BulkChallanApproveResponse)
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
@router.patch("/admin/bulk/{bulk_group_id}/reject", response_model=BulkChallanRejectResponse)
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
