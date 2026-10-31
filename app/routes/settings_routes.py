from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import settings_service
from app.utils.auth import get_current_user

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/public")
def get_public_settings(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Settings the frontend needs (limits etc.); any authenticated user."""
    return settings_service.public_settings(db)


@router.get("/branding")
def get_branding(db: Session = Depends(get_db)):
    """Pre-login branding (theme, organisation name/logo, landing and login text). No auth."""
    return settings_service.branding_settings(db)
