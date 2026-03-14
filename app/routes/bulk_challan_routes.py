from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import uuid
import json
from datetime import datetime

from app.database import get_db
from app.schemas.schemas import (
    BulkChallanCreate,
    BulkChallanResponse,
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
        member = db.query(Member).filter(Member.user_id == current_user.id).first()
        if not member:
            raise HTTPException(status_code=404, detail="Member record not found")

        if request.member_id and request.member_id != member.id:
            raise HTTPException(
                status_code=403,
                detail="Members can only create bulk challans for themselves"
            )
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

    existing_monthly = (
        db.query(Challan.month)
        .filter(
            Challan.member_id == member_id,
            Challan.type == ChallanType.MONTHLY,
            Challan.month.in_(list(months_set)),
            Challan.status != ChallanStatus.REJECTED,
        )
        .all()
    )
    if existing_monthly:
        duplicated_months = sorted({row[0] for row in existing_monthly if row[0]})
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Challan already exists for one or more months",
                "duplicate_months": duplicated_months,
            },
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
        db.refresh(bulk_group)
        
        return BulkChallanResponse(
            bulk_group_id=bulk_group_id,
            member_id=member_id,
            created_challans=len(challan_ids),
            challan_ids=challan_ids,
            months=request.months,
            total_amount=total_amount,
            proof_file_id=request.proof_file_id,
            status="pending_approval",
            created_at=bulk_group.created_at,
            notes=request.notes,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e
