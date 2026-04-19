from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.utils.file_handler import validate_file, save_file, delete_file
from app.utils.auth import get_current_user

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
):
    """
    Upload a payment proof or generic file and return a public URL.

    Accepts: jpg, png, pdf  |  Max size: 3 MB

    Returns:
        {"file_url": str, "filename": str}
    """
    content = await file.read()
    try:
        validate_file(content, file.filename, max_size_mb=3)
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

    saved_path = save_file(content, "avatars", file.filename)
    return {
        "file_url": _build_url(saved_path),
        "filename": saved_path.split("/")[-1],
    }


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
