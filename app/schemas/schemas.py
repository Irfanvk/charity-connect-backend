from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MEMBER = "member"


class ChallanStatus(str, Enum):
    GENERATED = "generated"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ChallanType(str, Enum):
    MONTHLY = "monthly"
    CAMPAIGN = "campaign"


# Auth Schemas
class UserLogin(BaseModel):
    username: str
    password: str


class UserRegisterWithInvite(BaseModel):
    invite_code: str
    username: str
    password: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    monthly_amount: Optional[float] = 0.0


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str]
    phone: Optional[str]
    role: UserRole
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


# Member Schemas
class MemberCreate(BaseModel):
    user_id: int
    member_code: str
    monthly_amount: float = 0.0
    address: Optional[str] = None


class MemberUpdate(BaseModel):
    monthly_amount: Optional[float] = None
    address: Optional[str] = None
    status: Optional[str] = None


class MemberResponse(BaseModel):
    id: int
    user_id: int
    member_code: str
    monthly_amount: float
    address: Optional[str]
    join_date: datetime
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Invite Schemas
class InviteCreate(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    expiry_date: datetime


class InviteResponse(BaseModel):
    id: int
    invite_code: str
    email: Optional[str]
    phone: Optional[str]
    is_used: bool
    expiry_date: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class InviteValidate(BaseModel):
    invite_code: str
    email_or_phone: str


# Campaign Schemas
class CampaignCreate(BaseModel):
    title: str
    description: Optional[str] = None
    target_amount: float
    start_date: datetime
    end_date: datetime


class CampaignUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    target_amount: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: Optional[bool] = None


class CampaignResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    target_amount: float
    start_date: datetime
    end_date: datetime
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Challan Schemas
class ChallanCreate(BaseModel):
    type: ChallanType
    month: Optional[str] = None  # YYYY-MM format
    campaign_id: Optional[int] = None
    amount: float
    payment_method: Optional[str] = None


class ChallanProofUpload(BaseModel):
    pass  # File upload handled separately


class ChallanApprove(BaseModel):
    approved_by_admin_id: int


class ChallanReject(BaseModel):
    rejection_reason: str


class ChallanResponse(BaseModel):
    id: int
    member_id: int
    type: ChallanType
    month: Optional[str]
    campaign_id: Optional[int]
    amount: float
    payment_method: Optional[str]
    proof_path: Optional[str]
    status: ChallanStatus
    created_at: datetime
    proof_uploaded_at: Optional[datetime]
    approved_at: Optional[datetime]
    updated_at: datetime

    class Config:
        from_attributes = True


# Notification Schemas
class NotificationCreate(BaseModel):
    user_id: Optional[int] = None
    title: str
    message: str
    target_role: Optional[UserRole] = None


class NotificationUpdate(BaseModel):
    is_read: bool


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    title: str
    message: str
    is_read: bool
    created_at: datetime
    read_at: Optional[datetime]

    class Config:
        from_attributes = True


# Audit Log Schemas
class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int]
    action: str
    entity_type: str
    entity_id: int
    old_values: Optional[str]
    new_values: Optional[str]
    ip_address: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
