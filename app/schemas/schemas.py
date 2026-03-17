import re
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Any
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


class CampaignTargetMode(str, Enum):
    TARGETED = "targeted"
    UNLIMITED = "unlimited"


class CampaignEndDateMode(str, Enum):
    FIXED = "fixed"
    OPEN = "open"


class RequestType(str, Enum):
    APPROVAL = "approval"
    QUESTION = "question"
    COMPLAINT = "complaint"
    SUGGESTION = "suggestion"
    PAYMENT_CHANGE = "payment_change"
    OTHER = "other"


# Auth Schemas
class UserLogin(BaseModel):
    username: Optional[str] = None  # Can be username or email
    email: Optional[str] = None     # Backward compatibility
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

    @field_validator("monthly_amount")
    @classmethod
    def validate_monthly_amount(cls, value: Optional[float]) -> float:
        if value is None:
            return 0.0
        if value and (value < 50 or value > 10000):
            raise ValueError("Monthly amount must be between ₹50 and ₹10,000")
        return value

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if len(value or "") < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", value):
            raise ValueError("Password must include at least one uppercase letter")
        if not re.search(r"[a-z]", value):
            raise ValueError("Password must include at least one lowercase letter")
        if not re.search(r"\d", value):
            raise ValueError("Password must include at least one number")
        if not re.search(r"[^A-Za-z0-9]", value):
            raise ValueError("Password must include at least one special character")
        return value


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
    # Legacy path: create member for an existing user.
    user_id: Optional[int] = None
    member_code: Optional[str] = None

    # Admin onboarding path (offline member creation from admin UI/import).
    member_id: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

    monthly_amount: float = 0.0
    address: Optional[str] = None
    join_date: Optional[datetime] = None
    status: Optional[str] = "active"
    city: Optional[str] = None
    notes: Optional[str] = None


class MemberUpdate(BaseModel):
    member_id: Optional[str] = None
    member_code: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    monthly_amount: Optional[float] = None
    address: Optional[str] = None
    status: Optional[str] = None
    join_date: Optional[datetime] = None
    city: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("monthly_amount")
    @classmethod
    def validate_monthly_amount(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and (value < 50 or value > 10000):
            raise ValueError("Monthly amount must be between ₹50 and ₹10,000")
        return value


class MemberResponse(BaseModel):
    id: int
    user_id: int
    member_id: Optional[str] = None
    full_name: Optional[str] = None
    member_code: str
    phone: Optional[str] = None
    email: Optional[str] = None
    monthly_amount: float
    address: Optional[str]
    join_date: datetime
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MemberImportSummary(BaseModel):
    total_rows: int
    members_created: int
    members_linked_existing: int
    challans_created: int
    rows_skipped: int
    errors: list[str]


class MemberSummaryResponse(BaseModel):
    total_members: int
    active_members: int


class ChallanHistoryImportSummary(BaseModel):
    total_rows: int
    challans_created: int
    members_linked_existing: int
    rows_skipped: int
    errors: list[str]


class CampaignPaymentImportSummary(BaseModel):
    total_rows: int
    campaigns_created: int
    challans_created: int
    members_linked_existing: int
    rows_skipped: int
    errors: list[str]


class ImportJobCreateResponse(BaseModel):
    job_id: str
    status: str
    message: str


class ImportJobStatusResponse(BaseModel):
    job_id: str
    job_type: str
    filename: str
    status: str
    progress: int
    message: str
    created_at: str
    updated_at: str
    result: Optional[Any] = None
    error: Optional[str] = None


class SystemWipeRequest(BaseModel):
    confirm_text: str
    purpose: str
    password_attempts: List[str] = Field(default_factory=list)
    keep_admins: bool = True
    wipe_files: bool = True


class SystemWipeResponse(BaseModel):
    users_deleted: int
    members_deleted: int
    challans_deleted: int
    campaigns_deleted: int
    invites_deleted: int
    notifications_deleted: int
    requests_deleted: int
    audit_logs_deleted: int
    bulk_groups_deleted: int
    files_deleted: int
    kept_superadmins: int
    kept_admins: int


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
    invited_by: Optional[str] = None
    status: str = "pending"

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
    target_mode: CampaignTargetMode = CampaignTargetMode.TARGETED
    target_amount: Optional[float] = None
    min_amount: float = 100.0
    start_date: datetime
    end_date_mode: CampaignEndDateMode = CampaignEndDateMode.FIXED
    end_date: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_campaign_rules(self):
        if self.min_amount <= 0:
            raise ValueError("Minimum amount must be greater than 0")

        if self.target_mode == CampaignTargetMode.TARGETED:
            if self.target_amount is None or self.target_amount <= 0:
                raise ValueError("Target amount must be greater than 0 for targeted campaigns")
        else:
            self.target_amount = None

        if self.end_date_mode == CampaignEndDateMode.FIXED:
            if self.end_date is None:
                raise ValueError("End date is required for fixed-duration campaigns")
            if self.end_date < self.start_date:
                raise ValueError("End date cannot be earlier than start date")
        else:
            self.end_date = None

        return self


class CampaignUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    target_mode: Optional[CampaignTargetMode] = None
    target_amount: Optional[float] = None
    min_amount: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date_mode: Optional[CampaignEndDateMode] = None
    end_date: Optional[datetime] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_partial_campaign_rules(self):
        if self.min_amount is not None and self.min_amount <= 0:
            raise ValueError("Minimum amount must be greater than 0")

        if self.target_mode == CampaignTargetMode.UNLIMITED:
            self.target_amount = None
        elif self.target_amount is not None and self.target_amount <= 0:
            raise ValueError("Target amount must be greater than 0")

        if self.end_date_mode == CampaignEndDateMode.OPEN:
            self.end_date = None

        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("End date cannot be earlier than start date")

        return self


class CampaignResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    target_mode: CampaignTargetMode = CampaignTargetMode.TARGETED
    target_amount: Optional[float]
    min_amount: float = 100.0
    collected_amount: float = 0.0
    participants_count: int = 0
    start_date: datetime
    end_date_mode: CampaignEndDateMode = CampaignEndDateMode.FIXED
    end_date: Optional[datetime]
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


class ChallanSummaryResponse(BaseModel):
    total_challans: int
    approved_count: int
    pending_count: int
    total_collected: float
    monthly_collection: float


class ChallanListResponse(BaseModel):
    items: List[ChallanResponse]
    total: int
    skip: int
    limit: int


class ChallanPayableMonthsResponse(BaseModel):
    member_id: int
    current_month: str
    pending_months: List[str]
    current_month_payable: bool
    upcoming_months: List[str]
    all_months: List[str]


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


class RequestCreate(BaseModel):
    request_type: RequestType = RequestType.QUESTION
    subject: str
    message: str
    priority: str = "medium"

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: str) -> str:
        allowed = ["low", "medium", "high"]
        if value.lower() not in allowed:
            raise ValueError(f"Priority must be one of: {', '.join(allowed)}")
        return value.lower()


class RequestUpdate(BaseModel):
    status: Optional[str] = None
    admin_response: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None


class RequestResponse(BaseModel):
    id: int
    created_by_user_id: int
    created_by: Optional[str] = None
    request_type: str
    subject: str
    message: str
    priority: str
    status: str
    admin_response: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    is_profile_update: bool = False
    profile_update_member_id: Optional[int] = None
    profile_update_changed_fields: Optional[dict[str, Any]] = None
    profile_update_submitted_at: Optional[str] = None
    created_at: datetime
    updated_at: datetime

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