from fastapi import HTTPException
from app.models.models import ChallanStatus
from fastapi import APIRouter, Depends, status as http_status, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from app.database import get_db, SessionLocal
from app.schemas import ChallanCreate, ChallanResponse, ChallanApprove, ChallanReject, ChallanRevert, ChallanUpdate, ChallanHistoryImportSummary, ChallanSummaryResponse, ChallanListResponse, OutstandingReceivablesResponse, ChallanPayableMonthsResponse, ImportJobCreateResponse, ImportJobStatusResponse, CollectionStatsResponse, MultiChallanCreate
from app.services import ChallanService, MemberService
from app.services.notification_service import NotificationService
from app.services.import_job_service import ImportJobService
from app.utils import get_current_user, get_current_admin, get_current_superadmin, log_audit
from app.utils.permissions import assert_not_self, assert_different_actor, assert_can_verify_entry, is_own_member_record, require_reason
from app.services.settings_service import get_setting
from typing import List, Optional
from app.services import admin_payment_service

router = APIRouter(prefix="/challans", tags=["Challans"])


def _assert_creator_for_pending_admin_entry(current_user: dict, challan, action: str) -> None:
    """Only the admin who entered a still-pending admin-recorded payment may edit or delete it."""
    if getattr(challan, "entry_source", None) != "admin":
        return
    if str(getattr(challan.status, "value", challan.status)).lower() not in ("pending", "generated"):
        return
    if challan.created_by_user_id != current_user.get("user_id"):
        raise HTTPException(
            status_code=403,
            detail=f"Only the admin who recorded this payment can {action} it while it is pending.",
        )


def _is_admin(current_user: dict) -> bool:
    return current_user.get("role") in ["admin", "superadmin"]


@router.get("/summary", response_model=ChallanSummaryResponse)
def get_challan_summary(
    month: Optional[str] = Query(default=None),
    member_id: Optional[int] = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get aggregate challan metrics for dashboard cards."""
    summary_member_id = member_id
    if not _is_admin(current_user):
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        summary_member_id = member.id

    return ChallanService.get_challan_summary(db, month=month, member_id=summary_member_id)


@router.get("/outstanding", response_model=OutstandingReceivablesResponse)
def get_outstanding_receivables(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return aggregate unpaid challans with a paginated drill-down list."""
    member_id = None
    if not _is_admin(current_user):
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        member_id = member.id

    return ChallanService.get_outstanding_receivables(
        db, skip=skip, limit=limit, member_id=member_id
    )


@router.get("/collection-stats", response_model=CollectionStatsResponse)
def get_collection_stats(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Aggregated collection amounts by period: today, this week, this month, this year, all-time.
    Members are scoped to their own challans; admins see org-wide totals.
    """
    stats_member_id = None
    if not _is_admin(current_user):
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        stats_member_id = member.id

    return ChallanService.get_collection_stats(db, member_id=stats_member_id)


@router.get("/community-stats", response_model=CollectionStatsResponse)
def get_community_collection_stats(
    _current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Org-wide collection totals by period for the community/transparency page.
    Accessible to all authenticated users.
    """
    return ChallanService.get_collection_stats(db, member_id=None)


@router.post("/import/history", response_model=ChallanHistoryImportSummary, status_code=http_status.HTTP_201_CREATED)
def import_challan_history(
    file: UploadFile = File(...),
    _current_user: dict = Depends(get_current_superadmin),
    db: Session = Depends(get_db),
):
    """
    Import historical monthly challans from CSV/XLSX (Superadmin only).

    Supported columns include:
    - username/member_code/si_no (member match)
    - month/period
    - amount
    - status
    - payment_method
    """
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    result = ChallanService.import_challan_history_file(
        db=db,
        file_bytes=content,
        filename=file.filename or "challan_history.csv",
    )
    log_audit(
        db,
        user_id=_current_user.get("user_id"),
        action="challan_history_import",
        entity_type="Challan",
        new_values={"filename": file.filename, "challans_created": result.challans_created, "rows_skipped": result.rows_skipped},
        auto_commit=True,
    )
    return result


@router.post("/import/history/jobs", response_model=ImportJobCreateResponse, status_code=http_status.HTTP_202_ACCEPTED)
def import_challan_history_async(
    file: UploadFile = File(...),
    _current_user: dict = Depends(get_current_superadmin),
):
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    filename = file.filename or "challan_history.csv"
    job_id = ImportJobService.create_job(job_type="challan_history_import", filename=filename)

    def _runner():
        db_bg = SessionLocal()
        try:
            summary = ChallanService.import_challan_history_file(
                db=db_bg,
                file_bytes=content,
                filename=filename,
                progress_callback=lambda progress, _total, message: ImportJobService.update_progress(
                    job_id,
                    progress=progress,
                    message=message,
                ),
            )
            if hasattr(summary, "model_dump"):
                return summary.model_dump()
            return summary.dict()
        finally:
            db_bg.close()

    ImportJobService.run_in_thread(job_id=job_id, runner=_runner)
    return ImportJobCreateResponse(job_id=job_id, status="queued", message="Challan history import job queued")


@router.get("/import/history/jobs/{job_id}", response_model=ImportJobStatusResponse)
def get_challan_import_job_status(
    job_id: str,
    _current_user: dict = Depends(get_current_superadmin),
):
    job = ImportJobService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return ImportJobStatusResponse(**job)


# ------------------------------------------------------------------
# CREATE CHALLAN (MEMBER)
# ------------------------------------------------------------------
@router.post("/", response_model=ChallanResponse, status_code=http_status.HTTP_201_CREATED)
def create_challan(
    challan_data: ChallanCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new challan.
    - Member: can create only for self
    - Admin/Superadmin: can create for any member via member_id
    """
    if _is_admin(current_user):
        if challan_data.member_id is None:
            raise HTTPException(status_code=400, detail="member_id is required for admin challan creation")

        member = MemberService.get_member(db, challan_data.member_id)
    else:
        try:
            member = MemberService.get_member_for_user(db, current_user["user_id"])
        except HTTPException as exc:
            raise HTTPException(
                status_code=404,
                detail="No member record found for your account. Please contact admin."
            ) from exc

        if challan_data.member_id is not None and challan_data.member_id != member.id:
            raise HTTPException(status_code=403, detail="Not authorized to create challan for another member")

    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if member.status != "active":
        raise HTTPException(status_code=400, detail="Cannot create challan for inactive member")

    entry_source = "admin" if _is_admin(current_user) and not is_own_member_record(db, current_user, member.id) else "self"
    challan = ChallanService.create_challan(
        db,
        member.id,
        challan_data,
        created_by_user_id=current_user.get("user_id"),
        entry_source=entry_source,
    )
    if _is_admin(current_user):
        log_audit(
            db,
            user_id=current_user.get("user_id"),
            action="challan_create",
            entity_type="Challan",
            entity_id=challan.id,
            new_values={"member_id": member.id, "type": str(challan_data.type), "amount": challan_data.amount},
            auto_commit=True,
        )
    return challan


@router.post("/multi", response_model=dict, status_code=http_status.HTTP_201_CREATED)
def create_multi_challans(
    challan_data: MultiChallanCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create multiple challans with option to use individual or bulk proof.
    
    Request body:
    {
        "months": ["2026-01", "2026-02", "2026-03"],
        "amount": 500,
        "type": "monthly",  # optional, default: "monthly"
        "proof_type": "bulk",  # "individual" or "bulk"
        "campaign_id": null,  # optional, for campaign challans
        "payment_method": "upi",  # optional
        "member_id": null,  # optional for members (auto-filled), required for admins
        "notes": "Payment proof description"  # optional, for bulk
    }
    
    Response for bulk:
    {
        "workflow": "bulk",
        "message": "Ready to create 6 linked challans with shared proof",
        "member_id": 123,
        "months": [...],
        "total_amount": 3000,
        "next_step": "POST /challans/bulk-create with proof file"
    }
    
    Response for individual:
    {
        "workflow": "individual",
        "message": "Successfully created 6 individual challans",
        "created_count": 6,
        "challan_ids": [1, 2, 3, 4, 5, 6],
        "total_amount": 3000,
        "next_step": "Upload proof files for each challan"
    }
    """
    
    # Determine target member
    if _is_admin(current_user):
        if challan_data.member_id is None:
            raise HTTPException(status_code=400, detail="member_id is required for admin")
        
        member = MemberService.get_member(db, challan_data.member_id)
        target_member_id = challan_data.member_id
    else:
        try:
            member = MemberService.get_member_for_user(db, current_user["user_id"])
            target_member_id = member.id
        except HTTPException as exc:
            raise HTTPException(
                status_code=404,
                detail="No member record found for your account. Please contact admin."
            ) from exc
        
        if challan_data.member_id is not None and challan_data.member_id != member.id:
            raise HTTPException(status_code=403, detail="Not authorized to create challans for another member")
    
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    
    if member.status != "active":
        raise HTTPException(status_code=400, detail="Cannot create challans for inactive member")
    
    # Create multi-challans with routing
    result = ChallanService.create_multi_challans(
        db=db,
        member_id=target_member_id,
        months=challan_data.months,
        amount=challan_data.amount,
        proof_type=challan_data.proof_type,
        challan_type=challan_data.type,
        campaign_id=challan_data.campaign_id,
        payment_method=challan_data.payment_method,
        notes=challan_data.notes,
        created_by_user_id=current_user.get("user_id"),
        entry_source="admin" if _is_admin(current_user) and not is_own_member_record(db, current_user, target_member_id) else "self",
    )
    
    # Log audit
    if _is_admin(current_user):
        log_audit(
            db,
            user_id=current_user.get("user_id"),
            action="multi_challan_create",
            entity_type="Challan",
            entity_id=target_member_id,
            new_values={
                "months": challan_data.months,
                "proof_type": challan_data.proof_type,
                "total_amount": result.get("total_amount"),
            },
            auto_commit=True,
        )
    
    return result


@router.post("/admin-record", response_model=List[ChallanResponse], status_code=http_status.HTTP_201_CREATED)
def admin_record_payment(
    member_id: int = Form(...),
    type: str = Form("monthly"),
    months: List[str] = Form(default=[]),
    campaign_id: Optional[int] = Form(default=None),
    amount_per_month: Optional[float] = Form(default=None),
    amount: Optional[float] = Form(default=None),
    payment_method: Optional[str] = Form(default=None),
    transaction_ref: Optional[str] = Form(default=None),
    received_on: Optional[str] = Form(default=None),
    collected_by_user_id: Optional[int] = Form(default=None),
    entry_notes: Optional[str] = Form(default=None),
    proof_file_id: Optional[str] = Form(default=None),
    proof_file: Optional[UploadFile] = File(default=None),
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Admin/superadmin records a payment for a member; it stays PENDING until a different admin verifies it."""
    created = admin_payment_service.record_payment(
        db,
        current_user,
        member_id=member_id,
        challan_type=type,
        months=admin_payment_service.parse_months(months),
        campaign_id=campaign_id,
        amount_per_month=amount_per_month,
        amount=amount,
        payment_method=payment_method,
        transaction_ref=transaction_ref,
        received_on=received_on,
        collected_by_user_id=collected_by_user_id,
        entry_notes=entry_notes,
        proof_file=proof_file,
        proof_file_id=proof_file_id,
    )
    first = created[0]
    log_audit(
        db,
        user_id=current_user.get("user_id"),
        action="challan_admin_record",
        entity_type="Challan",
        entity_id=first.id,
        new_values={
            "challan_ids": [c.id for c in created],
            "member_id": member_id,
            "type": type,
            "months": [c.month for c in created if c.month],
            "total_amount": sum(float(c.amount) for c in created),
            "payment_method": first.payment_method,
            "transaction_ref": first.transaction_ref,
            "received_on": str(first.received_on),
            "collected_by_user_id": first.collected_by_user_id,
            "status": "pending",
            "actor_role": current_user.get("role"),
        },
        auto_commit=True,
    )
    NotificationService.notify_admin_recorded_payment(
        db, created, current_user.get("user_id"), current_user.get("username")
    )
    return created


@router.get("/payable-months", response_model=ChallanPayableMonthsResponse)
def get_payable_months(
    member_id: Optional[int] = Query(default=None),
    include_upcoming: bool = Query(default=False),
    upcoming_count: Optional[int] = Query(default=None, ge=0, le=12),
    from_month: Optional[str] = Query(default=None, description="Start month override yyyy-MM"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return pending/current payable months and optional upcoming payable months."""
    target_member_id = member_id

    if _is_admin(current_user):
        if target_member_id is None:
            raise HTTPException(status_code=400, detail="member_id is required for admin")
    else:
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        target_member_id = member.id

    return ChallanService.get_payable_months(
        db,
        member_id=target_member_id,
        include_upcoming=include_upcoming,
        upcoming_count=upcoming_count,
        from_month=from_month,
    )


# ------------------------------------------------------------------
# UPLOAD PAYMENT PROOF (MEMBER – OWN CHALLAN ONLY)
# ------------------------------------------------------------------
@router.post("/{challan_id}/upload-proof", response_model=ChallanResponse)
def upload_proof(
    challan_id: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload payment proof for a challan.
    - Member: owner only
    - Admin/Superadmin: any member challan
    """
    challan = ChallanService.get_challan(db, challan_id)

    if not _is_admin(current_user):
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if challan.member_id != member.id:
            raise HTTPException(status_code=403, detail="Not authorized to upload proof")

    allowed_types = ["image/jpeg", "image/png", "application/pdf"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type")

    max_mb = get_setting(db, "proof_max_upload_mb")
    content = file.file.read()
    if len(content) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (max {max_mb}MB)")

    result = ChallanService.upload_proof(db, challan_id, content, file.filename)
    NotificationService.notify_admins_proof_uploaded(
        db,
        challan.member,
        [result.month] if result.month else [],
        current_user["user_id"],
        challan_id=challan_id,
    )
    return result


# ------------------------------------------------------------------
# GET CHALLANS (ADMIN: ALL WITH FILTERS, MEMBER: OWN WITH FILTERS)
# ------------------------------------------------------------------
@router.get("/", response_model=ChallanListResponse)
def get_challans(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    # ── existing ────────────────────────────────────────────────────
    # FastAPI reads ?status=approved from the URL into this param.
    # Named "status" (not "status_filter") to match what the frontend sends.
    status: Optional[str] = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    # ── new filter params sent by the frontend ───────────────────────
    search: Optional[str] = Query(default=None),      # ?search=john
    member_id: Optional[int] = Query(default=None),   # ?member_id=5  (non-admin scoping)
    created_by: Optional[str] = Query(default=None),  # ?created_by=user@email.com
    has_proof: Optional[bool] = Query(default=None),  # ?has_proof=true
    # ────────────────────────────────────────────────────────────────
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get challans with server-side filtering.
    - Admin/Superadmin: all challans, all filters available
    - Member: only their own challans (member_id / created_by ignored —
      always scoped to the logged-in member)
    """
    if _is_admin(current_user):
        # Admin path — all filters are honoured
        return ChallanService.get_all_challans(
            db,
            skip=skip,
            limit=limit,
            status_filter=status,
            sort_by=sort_by,
            sort_order=sort_order,
            search=search,
            member_id=member_id,
            created_by=created_by,
            has_proof=has_proof,
        )
    else:
        # Member path — always scope to this member, still honour
        # status / search / has_proof filters from the frontend
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")

        return ChallanService.get_all_challans(
            db,
            skip=skip,
            limit=limit,
            status_filter=status,
            sort_by=sort_by,
            sort_order=sort_order,
            search=search,
            member_id=member.id,   # always override with the real member id
            created_by=None,       # member_id is definitive, no need for email fallback
            has_proof=has_proof,
        )


# ------------------------------------------------------------------
# GET MEMBER CHALLANS (ADMIN OR SELF)
# ------------------------------------------------------------------
@router.get("/member/{member_id}", response_model=List[ChallanResponse])
def get_member_challans(
    member_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get challans for a specific member (admin or self).
    """
    if not _is_admin(current_user):
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if member.id != member_id:
            raise HTTPException(status_code=403, detail="Access denied")

    return ChallanService.get_member_challans(
        db, member_id, skip, limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )


# ------------------------------------------------------------------
# GET SINGLE CHALLAN (ADMIN OR OWNER)
# ------------------------------------------------------------------
@router.get("/{challan_id}", response_model=ChallanResponse)
def get_challan(
    challan_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get challan details (admin or owner).
    """
    challan = ChallanService.get_challan(db, challan_id)

    if not _is_admin(current_user):
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if member is None:
            raise HTTPException(status_code=404, detail="Member not found")
        if challan.member_id != member.id:
            raise HTTPException(status_code=403, detail="Access denied")

    return challan


# ------------------------------------------------------------------
# UPDATE CHALLAN (ADMIN OR OWNER)
# ------------------------------------------------------------------
@router.put("/{challan_id}", response_model=ChallanResponse)
@router.patch("/{challan_id}", response_model=ChallanResponse)
def update_challan(
    challan_id: int,
    update_data: ChallanUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update challan (admin or owner)."""
    challan = ChallanService.get_challan(db, challan_id)

    if not _is_admin(current_user):
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if challan.member_id != member.id:
            raise HTTPException(status_code=403, detail="Not authorized to update this challan")

    # Members may only update non-sensitive fields (payment_method).
    # Amount, month, and campaign_id changes are admin-only.
    if not _is_admin(current_user):
        admin_only_fields = {"amount", "month", "campaign_id"}
        requested_fields = set(update_data.dict(exclude_unset=True).keys())
        forbidden = requested_fields & admin_only_fields
        if forbidden:
            raise HTTPException(
                status_code=403,
                detail=f"Members cannot update: {', '.join(sorted(forbidden))}",
            )

    _assert_creator_for_pending_admin_entry(current_user, challan, "edit")
    old_status = challan.status
    changes = update_data.dict(exclude_unset=True)
    if _is_admin(current_user) and {"amount", "month", "campaign_id"} & set(changes):
        assert_not_self(db, current_user, challan.member_id, "edit")
    result = ChallanService.update_challan(db, challan_id, update_data)
    if _is_admin(current_user):
        log_audit(
            db,
            user_id=current_user.get("user_id"),
            action="challan_update",
            entity_type="Challan",
            entity_id=challan_id,
            old_values={"status": old_status},
            new_values={"status": old_status, **changes},
            auto_commit=True,
        )
    return result


# ------------------------------------------------------------------
# APPROVE CHALLAN (ADMIN ONLY)
# ------------------------------------------------------------------
@router.patch("/{challan_id}/approve", response_model=ChallanResponse)
def approve_challan(
    challan_id: int,
    approve_data: ChallanApprove,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    challan = ChallanService.get_challan(db, challan_id)
    assert_not_self(db, current_user, challan.member_id, "approve")
    assert_can_verify_entry(current_user, challan)

    if challan.status != ChallanStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Challan already processed")

    admin_id = current_user.get("user_id")
    result = ChallanService.approve_challan(db, challan_id, admin_id)
    log_audit(
        db,
        user_id=admin_id,
        action="challan_approve",
        entity_type="Challan",
        entity_id=challan_id,
        old_values={"status": "pending"},
        new_values={"status": "approved", "member_id": challan.member_id, "amount": float(challan.amount)},
        auto_commit=True,
    )
    NotificationService.notify_challan_status_change(db, challan, "approved")
    NotificationService.send_payment_receipt_whatsapp(db, [challan])
    return result


# ------------------------------------------------------------------
# REJECT CHALLAN (ADMIN ONLY)
# ------------------------------------------------------------------
@router.patch("/{challan_id}/reject", response_model=ChallanResponse)
def reject_challan(
    reject_data: ChallanReject,
    challan_id: int,
    _current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    challan = ChallanService.get_challan(db, challan_id)
    assert_not_self(db, _current_user, challan.member_id, "reject")
    require_reason(reject_data.rejection_reason, "Rejection reason", db)
    if challan.status not in (ChallanStatus.PENDING.value, ChallanStatus.APPROVED.value):
        raise HTTPException(status_code=400, detail="Only pending or approved challans can be rejected")

    old_status = challan.status
    if old_status == ChallanStatus.APPROVED.value:
        assert_different_actor(_current_user.get("user_id"), challan.approved_by_admin_id, "Rejection")
    result = ChallanService.reject_challan(db, challan_id, reject_data, actor_id=_current_user.get("user_id"))
    log_audit(
        db,
        user_id=_current_user.get("user_id"),
        action="challan_reject",
        entity_type="Challan",
        entity_id=challan_id,
        old_values={"status": old_status},
        new_values={"status": "rejected", "reason": reject_data.rejection_reason, "member_id": challan.member_id},
        auto_commit=True,
    )
    NotificationService.notify_challan_status_change(
        db, challan, "rejected", reject_data.rejection_reason, _current_user.get("username")
    )
    return result


# ------------------------------------------------------------------
# REVERT CHALLAN TO PENDING (ADMIN ONLY)
# ------------------------------------------------------------------
@router.patch("/{challan_id}/revert", response_model=ChallanResponse)
def revert_challan(
    challan_id: int,
    revert_data: ChallanRevert,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    challan = ChallanService.get_challan(db, challan_id)
    assert_not_self(db, current_user, challan.member_id, "revert")
    require_reason(revert_data.reason, "Reason", db)
    if challan.status not in (ChallanStatus.APPROVED.value, ChallanStatus.REJECTED.value):
        raise HTTPException(status_code=400, detail="Only approved or rejected challans can be reverted")

    old_status = challan.status
    if old_status == ChallanStatus.APPROVED.value:
        assert_different_actor(current_user.get("user_id"), challan.approved_by_admin_id, "Reversal")
    result = ChallanService.revert_challan(
        db, challan_id, reason=revert_data.reason, actor_id=current_user.get("user_id")
    )
    log_audit(
        db,
        user_id=current_user.get("user_id"),
        action="challan_revert",
        entity_type="Challan",
        entity_id=challan_id,
        old_values={"status": old_status},
        new_values={"status": "pending", "reason": revert_data.reason},
        auto_commit=True,
    )
    NotificationService.notify_challan_status_change(db, challan, "reverted", revert_data.reason)
    return result


# ------------------------------------------------------------------
# DELETE CHALLAN (ADMIN OR OWNER, BEFORE APPROVAL)
# ------------------------------------------------------------------
@router.delete("/{challan_id}")
def delete_challan(
    challan_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete challan (admin or owner) before approval."""
    challan = ChallanService.get_challan(db, challan_id)

    if not _is_admin(current_user):
        member = MemberService.get_member_for_user(db, current_user["user_id"])
        if member is None or challan.member_id != member.id:
            raise HTTPException(status_code=403, detail="Not authorized to delete this challan")
    else:
        assert_not_self(db, current_user, challan.member_id, "delete")
        _assert_creator_for_pending_admin_entry(current_user, challan, "delete")

    deleted_snapshot = {
        "status": challan.status,
        "member_id": challan.member_id,
        "amount": float(challan.amount or 0),
        "month": challan.month,
    }
    result = ChallanService.delete_challan(db, challan_id)

    if _is_admin(current_user):
        log_audit(
            db,
            user_id=current_user.get("user_id"),
            action="challan_delete",
            entity_type="Challan",
            entity_id=challan_id,
            old_values=deleted_snapshot,
            new_values={"deleted": True},
            auto_commit=True,
        )

    return result