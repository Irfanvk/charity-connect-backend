from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import UserLogin, UserRegisterWithInvite, UserResponse, TokenResponse
from app.services import AuthService
from app.utils import create_access_token, get_current_user
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
