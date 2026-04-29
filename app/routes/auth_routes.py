from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.schemas import UserLogin, UserRegisterWithInvite, UserResponse, TokenResponse
from app.services import AuthService
from app.utils import create_access_token, get_current_user
from app.utils.file_handler import save_file, validate_file, delete_file
from app.config import settings
from datetime import timedelta

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(credentials: UserLogin, request: Request, db: Session = Depends(get_db)):
    """
    Login user and get JWT token.
    """
    source_ip = request.client.host if request.client else None
    user = AuthService.login(db, credentials, source_ip=source_ip)
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role},
        expires_delta=access_token_expires,
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
    }


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(registration: UserRegisterWithInvite, db: Session = Depends(get_db)):
    """
    Register new user with valid invite code.
    """
    user = AuthService.register_with_invite(db, registration)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role},
        expires_delta=access_token_expires,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
    }


@router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Get current authenticated user details.
    """
    user = AuthService.get_current_user(db, current_user["user_id"])
    return user


@router.post("/logout")
def logout():
    """
    Logout user (token is invalidated on frontend).
    """
    return {"message": "Logged out successfully"}


@router.post("/me/avatar", response_model=UserResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload or update the current user's profile avatar."""
    if str(current_user.get("role", "")).lower() == "member":
        raise HTTPException(
            status_code=403,
            detail="Members must submit a profile update request for avatar changes",
        )

    content = await file.read()

    try:
        validate_file(content, file.filename, max_size_mb=2)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("jpg", "jpeg", "png"):
        raise HTTPException(status_code=400, detail="Only JPG and PNG images are allowed")

    saved_path = save_file(content, "avatars", file.filename)
    avatar_url = saved_path if saved_path.startswith("http") else f"/{saved_path}"

    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.avatar_url = avatar_url
    db.commit()
    db.refresh(user)
    return user


@router.delete("/me/avatar", response_model=UserResponse)
def remove_avatar(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove the current user's profile avatar."""
    if str(current_user.get("role", "")).lower() == "member":
        raise HTTPException(
            status_code=403,
            detail="Members must submit a profile update request for avatar changes",
        )

    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    previous_avatar_url = user.avatar_url
    user.avatar_url = None
    db.commit()
    db.refresh(user)
    if previous_avatar_url:
        delete_file(previous_avatar_url)
    return user
