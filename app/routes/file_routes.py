from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.settings_service import get_setting
from app.utils.file_handler import validate_file, save_file, delete_file, save_pending_avatar
from app.utils.auth import get_current_user, get_current_superadmin

router = APIRouter(prefix="/files", tags=["Files"])


def _build_url(saved_path: str) -> str:
    """Normalise a saved path to a usable URL."""
    if saved_path.startswith("http"):
        return saved_path
    if saved_path.startswith("/"):
        return saved_path
    return f"/{saved_path}"


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    _current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload a payment proof or generic file and return a public URL.

    Accepts: jpg, png, pdf  |  Max size: platform setting proof_max_upload_mb

    Returns:
        {"file_url": str, "filename": str}
    """
    content = await file.read()
    try:
        validate_file(content, file.filename, max_size_mb=get_setting(db, "proof_max_upload_mb"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    from app.services import proof_service

    user_id = _current_user.get("user_id")
    saved_path, _sha = proof_service.store_proof(
        db, content, file.filename, user_id=user_id, name_hint=proof_service.member_hint(db, user_id),
    )
    db.commit()
    return {
        "file_url": _build_url(saved_path),
        "filename": saved_path.split("/")[-1],
    }


@router.post("/upload/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload a profile avatar / member photo and return a public URL.

    Accepts: jpg, png  |  Max size: 3 MB

    Returns:
        {"file_url": str, "filename": str}
    """
    content = await file.read()
    try:
        validate_file(content, file.filename, max_size_mb=3)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Only images are accepted for avatars
    from pathlib import Path
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png"}:
        raise HTTPException(status_code=400, detail="Avatars must be JPEG or PNG images.")

    # Member avatars go to temporary storage; they are moved to the permanent
    # folder only when an admin approves the profile-update request.
    from app.models.models import Member

    code = db.query(Member.member_code).filter(Member.user_id == current_user.get("user_id")).scalar()
    saved_path = save_pending_avatar(content, file.filename, name_hint=code or f"user{current_user.get('user_id')}")
    return {
        "file_url": _build_url(saved_path),
        "filename": saved_path.split("/")[-1],
    }


@router.post("/upload/branding")
async def upload_branding_image(
    file: UploadFile = File(...),
    _current_user: dict = Depends(get_current_superadmin),
):
    """Upload a logo / hero image for platform settings (superadmin, image only, max 1 MB)."""
    from pathlib import Path

    content = await file.read()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png"}:
        raise HTTPException(status_code=400, detail="Branding images must be JPEG or PNG.")
    try:
        validate_file(content, file.filename, max_size_mb=1)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    saved_path = save_file(content, "branding", file.filename)
    return {"file_url": _build_url(saved_path), "filename": saved_path.split("/")[-1]}


@router.delete("/delete")
async def remove_file(
    file_url: str,
    _current_user: dict = Depends(get_current_user),
):
    """
    Delete a previously uploaded file from Cloudinary by its URL.

    Returns:
        {"deleted": bool}
    """
    success = delete_file(file_url)
    return {"deleted": success}


@router.get("/proof-link")
def proof_link(
    challan_id: int | None = None,
    bulk_group_id: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A fresh short-lived link to a payment's proof, for admins or the member it belongs to."""
    from app.models.models import BulkChallanGroup, Challan, Member
    from app.utils.file_handler import signed_url

    role = str(current_user.get("role") or "").lower()
    own_member_id = db.query(Member.id).filter(Member.user_id == current_user.get("user_id")).scalar()
    if bulk_group_id:
        group = db.query(BulkChallanGroup).filter(BulkChallanGroup.bulk_group_id == bulk_group_id).first()
        if group is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        member_id, ref = group.member_id, group.proof_file_id
    elif challan_id is not None:
        challan = db.query(Challan).filter(Challan.id == challan_id).first()
        if challan is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        member_id, ref = challan.member_id, challan.proof_path
        if not ref and challan.bulk_group_id:
            group = db.query(BulkChallanGroup).filter(BulkChallanGroup.bulk_group_id == challan.bulk_group_id).first()
            ref = group.proof_file_id if group is not None else None
    else:
        raise HTTPException(status_code=400, detail="challan_id or bulk_group_id is required")
    if role not in ("admin", "superadmin") and member_id != own_member_id:
        raise HTTPException(status_code=403, detail="Not allowed to view this proof")
    if not ref or str(ref).startswith("no-proof:"):
        raise HTTPException(status_code=404, detail="No proof was uploaded for this payment")
    url = signed_url(_build_url(str(ref)))
    if not url:
        raise HTTPException(status_code=503, detail="The proof cannot be opened right now. Please try again.")
    return {"url": url, "expires_in": 1800}
