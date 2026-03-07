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
    username: Optional[str] = None
    email: Optional[str] = None
    password: str


class UserRegisterWithInvite(BaseModel):
    invite_code: str
    username: str
    password: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    monthly_amount: Optional[float] = 0.0


class UserResponse(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    email: Optional[str]
    phone: Optional[str]
    role: UserRole
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


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
    full_name: Optional[str] = None
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
    expiry_date: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    class Config:
        extra = "ignore"


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


class InviteUpdate(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    expiry_date: Optional[datetime] = None
    expires_at: Optional[datetime] = None


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
    member_id: Optional[int] = None
    type: ChallanType
    month: Optional[str] = None  # YYYY-MM format
    campaign_id: Optional[int] = None
    amount: float
    payment_method: Optional[str] = None


class ChallanUpdate(BaseModel):
    month: Optional[str] = None
    campaign_id: Optional[int] = None
    amount: Optional[float] = None
    payment_method: Optional[str] = None


class ChallanProofUpload(BaseModel):
    pass  # File upload handled separately


class ChallanApprove(BaseModel):
    approved_by_admin_id: Optional[int] = None


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


class NotificationAdminUpdate(BaseModel):
    title: Optional[str] = None
    message: Optional[str] = None
    is_read: Optional[bool] = None


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


class NotificationSentBatchResponse(BaseModel):
    batch_created_at: datetime
    title: str
    message: str
    target_role: Optional[UserRole] = None
    audience_label: str
    total_recipients: int
    member_recipients: int
    admin_recipients: int
    superadmin_recipients: int
    unread_count: int


class NotificationSentDeleteRequest(BaseModel):
    batch_created_at: datetime
    title: str
    message: str
    recipient_scope: str = "all"  # all | members | admins | superadmins


class NotificationSentDeleteResponse(BaseModel):
    deleted_count: int
    message: str


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


class AuditLogCreate(BaseModel):
    user_id: Optional[int] = None
    action: str
    entity_type: str
    entity_id: int
    old_values: Optional[str] = None
    new_values: Optional[str] = None
    ip_address: Optional[str] = None

# Bulk Challan Schemas (v1.1)
class BulkChallanCreate(BaseModel):
    months: list[str]  # List of YYYY-MM format months
    amount_per_month: float
    proof_file_id: str
    member_id: Optional[int] = None  # Optional for members (uses current user), required for admins
    notes: Optional[str] = None


class BulkChallanLinkedChallan(BaseModel):
    challan_id: int
    month: str
    amount: float
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class BulkChallanResponse(BaseModel):
    bulk_group_id: str
    member_id: int
    created_challans: int
    challan_ids: list[int]
    months: list[str]
    total_amount: float
    proof_file_id: str
    status: str
    created_at: datetime
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class BulkChallanListItem(BaseModel):
    bulk_group_id: str
    member_id: int
    member_name: Optional[str] = None
    member_email: Optional[str] = None
    months: list[str]
    months_count: int
    total_amount: float
    amount_per_month: float
    proof_file_id: str
    proof_url: Optional[str] = None
    status: str
    created_at: datetime
    created_by_email: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class BulkChallanListResponse(BaseModel):
    pending: int
    bulk_operations: list[BulkChallanListItem]

    class Config:
        from_attributes = True


class BulkChallanApprove(BaseModel):
    approved: bool
    admin_notes: Optional[str] = None


class BulkChallanApproveResponse(BaseModel):
    bulk_group_id: str
    status: str
    approved_challans: int
    challan_ids: list[int]
    months_approved: list[str]
    total_amount_approved: float
    approved_by: Optional[str] = None
    approved_at: datetime
    admin_notes: Optional[str] = None

    class Config:
        from_attributes = True


class BulkChallanReject(BaseModel):
    reason: str
    action: str  # "delete"


class BulkChallanRejectResponse(BaseModel):
    bulk_group_id: str
    status: str
    rejected_challans: int
    challan_ids: list[int]
    rejected_at: datetime
    reason: str
    rejected_by: Optional[str] = None

    class Config:
        from_attributes = True


class BulkChallanDetails(BaseModel):
    bulk_group_id: str
    member_id: int
    member_name: Optional[str] = None
    member_email: Optional[str] = None
    months: list[str]
    total_amount: float
    amount_per_month: float
    proof_file_id: str
    proof_url: Optional[str] = None
    status: str
    created_at: datetime
    created_by_email: Optional[str] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    admin_notes: Optional[str] = None
    notes: Optional[str] = None
    linked_challans: list[BulkChallanLinkedChallan]

    class Config:
        from_attributes = True