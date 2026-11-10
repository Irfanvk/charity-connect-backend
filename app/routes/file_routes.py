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

    saved_path = save_file(content, "proofs", file.filename)
    return {
        "file_url": _build_url(saved_path),
        "filename": saved_path.split("/")[-1],
    }


@router.post("/upload/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
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
    saved_path = save_pending_avatar(content, file.filename)
    return {
        "file_url": _build_url(saved_path),
        "filename": saved_path.split("/")[-1],
    }


@router.post("/upload/branding")
async def upload_branding_image(
    file: UploadFile = File(...),
    _current_user: dict = Depends(get_current_superadmin),
):
    """Upload a logo / QR / hero image for platform settings (superadmin, image only, max 1 MB)."""
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
