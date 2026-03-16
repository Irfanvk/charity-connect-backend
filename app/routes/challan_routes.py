from fastapi import HTTPException
from app.models.models import ChallanStatus
from fastapi import APIRouter, Depends, status as http_status, UploadFile, File, Query
from sqlalchemy.orm import Session
from app.database import get_db, SessionLocal
from app.schemas import ChallanCreate, ChallanResponse, ChallanApprove, ChallanReject, ChallanUpdate, ChallanHistoryImportSummary, ChallanSummaryResponse, ChallanListResponse, ImportJobCreateResponse, ImportJobStatusResponse
from app.services import ChallanService, MemberService
from app.services.import_job_service import ImportJobService
from app.utils import get_current_user, get_current_admin, get_current_superadmin
from typing import List, Optional

router = APIRouter(prefix="/challans", tags=["Challans"])


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

    return ChallanService.import_challan_history_file(
        db=db,
        file_bytes=content,
        filename=file.filename or "challan_history.csv",
    )


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

    return ChallanService.create_challan(db, member.id, challan_data)


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

    content = file.file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")

    return ChallanService.upload_proof(db, challan_id, content, file.filename)


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

    return ChallanService.update_challan(db, challan_id, update_data)


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

    if challan.status != ChallanStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Challan already processed")

    admin_id = approve_data.approved_by_admin_id or current_user.get("user_id")
    return ChallanService.approve_challan(db, challan_id, admin_id)


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

    if challan.status != ChallanStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Challan already processed")

    return ChallanService.reject_challan(db, challan_id, reject_data)