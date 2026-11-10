import hashlib
import re
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from app.config import settings
from app.database import get_db
from app.models import User
from sqlalchemy.orm import Session

# Configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
http_bearer = HTTPBearer(auto_error=False)

# Get from config
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def generate_invite_code() -> str:
    """Generate invite code in INV-XXXXXX format."""
    characters = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(characters) for _ in range(6))
    return f"INV-{suffix}"


def generate_member_code(last_member_code: Optional[str] = None) -> str:
    """
    Generate sequential member code.
    Format: MEM-0001, MEM-0002, etc.
    """
    if last_member_code is None:
        return "MEM-0001"

    try:
        # Extract all digits from the code (handles MEM001, MEM-0001, plain numbers, etc.)
        digits = re.sub(r"[^0-9]", "", str(last_member_code))
        number = int(digits) if digits else 0
        next_number = number + 1
        return f"MEM-{next_number:04d}"
    except (ValueError, AttributeError):
        return "MEM-0001"


def password_fingerprint(password_hash: str) -> str:
    """Short, non-reversible fingerprint of the stored hash. Changes whenever the password does."""
    return hashlib.sha256(f"{SECRET_KEY}:{password_hash or ''}".encode()).hexdigest()[:16]


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    now = datetime.utcnow()
    to_encode.update({"iat": now, "nbf": now, "exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict:
    """Verify and decode JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def resolve_session_role(db: Session, payload: dict, user_id: int):
    """
    Return the role to trust for this token.

    Long-lived "remember me" tokens (claim ``rm``) are re-checked against the
    account so they stop working once the user is deactivated or changes /
    resets the password, and they use the user's current role rather than the
    one baked into a weeks-old token. Short tokens keep the existing behaviour.
    """
    if not payload.get("rm"):
        return payload.get("role")
    user = db.query(User).filter(User.id == user_id).first()
    if (
        not user
        or not user.is_active
        or payload.get("pwv") != password_fingerprint(user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user.role.value if hasattr(user.role, "value") else str(user.role)


async def get_current_user(credentials = Depends(http_bearer), db: Session = Depends(get_db)):
    """Get current user from token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = verify_token(token)
    user_id = payload.get("sub")
    
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc
    
    role = resolve_session_role(db, payload, user_id)

    try:
        now = datetime.utcnow()
        stale_before = now - timedelta(minutes=1)
        db.query(User).filter(
            User.id == user_id,
            (User.last_seen_at.is_(None)) | (User.last_seen_at < stale_before),
        ).update({"last_seen_at": now}, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()

    return {"user_id": user_id, "role": role}


def get_current_admin(current_user: dict = Depends(get_current_user)):
    """Verify current user is admin or superadmin."""
    if current_user["role"] not in ["admin", "superadmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def get_current_superadmin(current_user: dict = Depends(get_current_user)):
    """Verify current user is superadmin."""
    if current_user["role"] != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin access required",
        )
    return current_user
