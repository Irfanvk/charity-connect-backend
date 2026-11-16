"""Occasion banners (see app/services/banner_service.py)."""
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import banner_service
from app.utils.auth import get_current_user
from app.utils.file_handler import save_file, validate_file

router = APIRouter(prefix="/banners", tags=["Banners"])

MAX_IMAGE_MB = 3  # the app shrinks images before uploading, so real uploads are far smaller


class BannerIn(BaseModel):
    title: Optional[str] = None
    message: Optional[str] = None
    image_url: Optional[str] = None
    button_label: Optional[str] = None
    button_link: Optional[str] = None
    show_on_login: Optional[bool] = None
    show_to_members: Optional[bool] = None
    show_to_admins: Optional[bool] = None
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/login")
def login_banners(db: Session = Depends(get_db)):
    """Public: banners showing on the login page right now."""
    return {"items": banner_service.active(db, "login")}


@router.get("/for-me")
def my_banners(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Banners for the signed-in user's dashboard right now (members' or admins' banners)."""
    return {"items": banner_service.active(db, "dashboard", str(current_user.get("role", "")).lower())}


@router.get("")
def list_banners(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return banner_service.list_all(db, current_user)


@router.post("", status_code=201)
def create_banner(payload: BannerIn, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return banner_service.create(db, current_user, payload.model_dump())


@router.put("/{banner_id}")
def update_banner(banner_id: int, payload: BannerIn, current_user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    return banner_service.update(db, current_user, banner_id, payload.model_dump(exclude_unset=True))


@router.delete("/{banner_id}", status_code=204)
def delete_banner(banner_id: int, current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    banner_service.delete(db, current_user, banner_id)


@router.post("/image")
async def upload_banner_image(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Admins: upload a banner image (JPG or PNG; the app sends a resized JPG). Returns {image_url}."""
    if str(current_user.get("role", "")).lower() not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    content = await file.read()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("jpg", "jpeg", "png"):
        raise HTTPException(status_code=400, detail="Use a JPG or PNG image")
    try:
        validate_file(content, file.filename, max_size_mb=MAX_IMAGE_MB)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = save_file(content, "banners", file.filename)
    return {"image_url": saved if saved.startswith("http") else f"/{saved}"}
