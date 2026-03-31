from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db, SessionLocal
from app.schemas import CampaignCreate, CampaignResponse, CampaignUpdate, CampaignPaymentImportSummary, ImportJobCreateResponse, ImportJobStatusResponse
from app.services import CampaignService
from app.services.import_job_service import ImportJobService
from app.utils import get_current_user, get_current_admin, get_current_superadmin, log_audit
from typing import List

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


@router.post("/import/payments", response_model=CampaignPaymentImportSummary, status_code=status.HTTP_201_CREATED)
def import_campaign_payments(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_superadmin),
    db: Session = Depends(get_db),
):
    """
    Import campaign payment history from CSV/XLSX (Superadmin only).

    Supported columns include:
    - username/member_code/si_no (member match)
    - amount
    - status
    - payment_method
    - suggested_campaign_name/campaign_name
    """
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    result = CampaignService.import_campaign_payments_file(
        db=db,
        file_bytes=content,
        filename=file.filename or "campaign_payments.csv",
        imported_by_user_id=current_user.get("user_id"),
    )
    log_audit(
        db,
        user_id=current_user.get("user_id"),
        action="campaign_payments_import",
        entity_type="Campaign",
        new_values={"filename": file.filename, "challans_created": result.challans_created, "campaigns_created": result.campaigns_created},
        auto_commit=True,
    )
    return result


@router.post("/import/payments/jobs", response_model=ImportJobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def import_campaign_payments_async(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_superadmin),
):
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    filename = file.filename or "campaign_payments.csv"
    job_id = ImportJobService.create_job(job_type="campaign_payments_import", filename=filename)
    imported_by_user_id = current_user.get("user_id")

    def _runner():
        db_bg = SessionLocal()
        try:
            summary = CampaignService.import_campaign_payments_file(
                db=db_bg,
                file_bytes=content,
                filename=filename,
                imported_by_user_id=imported_by_user_id,
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
    return ImportJobCreateResponse(job_id=job_id, status="queued", message="Campaign payments import job queued")


@router.get("/import/payments/jobs/{job_id}", response_model=ImportJobStatusResponse)
def get_campaign_import_job_status(
    job_id: str,
    _current_user: dict = Depends(get_current_superadmin),
):
    job = ImportJobService.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return ImportJobStatusResponse(**job)


@router.post("/", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
def create_campaign(
    campaign_data: CampaignCreate,
    current_admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Create new campaign (Admin only).
    """
    try:
        campaign = CampaignService.create_campaign(db, campaign_data, current_admin["user_id"])
        log_audit(
            db,
            user_id=current_admin["user_id"],
            action="campaign_create",
            entity_type="Campaign",
            entity_id=campaign.id,
            new_values={"title": campaign_data.title, "target_mode": str(campaign_data.target_mode)},
            auto_commit=True,
        )
        return campaign
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create campaign")


@router.get("/", response_model=List[CampaignResponse])
def get_all_campaigns(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    active_only: bool = False,
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    _: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        campaigns = CampaignService.get_all_campaigns(db, skip, limit, active_only)
        return campaigns
    except Exception as e:
        import traceback
        traceback.print_exc()  # ✅ prints full error to terminal
        raise HTTPException(status_code=500, detail=str(e))  # ✅ shows error in browser too
    
    
@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(
    campaign_id: int,
    _: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get campaign details by ID.
    """
    campaign = CampaignService.get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Campaign {campaign_id} not found")
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignResponse)
@router.put("/{campaign_id}", response_model=CampaignResponse)
def update_campaign(
    campaign_id: int,
    update_data: CampaignUpdate,
    _: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Update a campaign (Admin only).
    
    Supports both PUT and PATCH methods for compatibility.
    PATCH is canonical for partial updates, but PUT is also accepted.
    """
    campaign = CampaignService.get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Campaign {campaign_id} not found")
    try:
        updated = CampaignService.update_campaign(db, campaign_id, update_data)
        log_audit(
            db,
            user_id=_.get("user_id"),
            action="campaign_update",
            entity_type="Campaign",
            entity_id=campaign_id,
            new_values=update_data.model_dump(exclude_unset=True),
            auto_commit=True,
        )
        return updated
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update campaign")


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    campaign_id: int,
    _: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Delete a campaign (Admin only).
    """
    campaign = CampaignService.get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Campaign {campaign_id} not found")
    try:
        CampaignService.delete_campaign(db, campaign_id)
        log_audit(
            db,
            user_id=_.get("user_id"),
            action="campaign_delete",
            entity_type="Campaign",
            entity_id=campaign_id,
            old_values={"title": campaign.title},
            auto_commit=True,
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete campaign")