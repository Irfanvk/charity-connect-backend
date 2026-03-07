from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, Enum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class UserRole(str, enum.Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MEMBER = "member"


class ChallanStatus(str, enum.Enum):
    GENERATED = "generated"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ChallanType(str, enum.Enum):
    MONTHLY = "monthly"
    CAMPAIGN = "campaign"


class NotificationStatus(str, enum.Enum):
    SENT = "sent"
    READ = "read"
    UNREAD = "unread"


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.MEMBER, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    member = relationship("Member", back_populates="user", uselist=False)
    notifications = relationship("Notification", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")
    requests = relationship("Request", back_populates="created_by_user")

    @property
    def full_name(self):
        return self.username


class Member(Base):
    __tablename__ = "members"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    member_code = Column(String(50), unique=True, nullable=False, index=True)
    monthly_amount = Column(Float, default=0.0)
    address = Column(Text, nullable=True)
    join_date = Column(DateTime, server_default=func.now())
    status = Column(String(50), default="active")  # active, inactive, suspended
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="member")
    challans = relationship("Challan", back_populates="member")

    @property
    def full_name(self):
        if self.user:
            return self.user.username
        return None


class Invite(Base):
    __tablename__ = "invites"
    
    id = Column(Integer, primary_key=True, index=True)
    invite_code = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(20), nullable=True, index=True)
    is_used = Column(Boolean, default=False)
    used_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    expiry_date = Column(DateTime, nullable=False)
    created_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    used_by = relationship("User", foreign_keys=[used_by_user_id])
    created_by = relationship("User", foreign_keys=[created_by_admin_id])


class Campaign(Base):
    __tablename__ = "campaigns"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    target_amount = Column(Float, nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    created_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_admin_id])
    challans = relationship("Challan", back_populates="campaign")


class Challan(Base):
    __tablename__ = "challans"
    
    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    type = Column(Enum(ChallanType), nullable=False)  # monthly or campaign
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    month = Column(String(20), nullable=True)  # YYYY-MM format for monthly
    amount = Column(Float, nullable=False)
    payment_method = Column(String(50), nullable=True)  # cash, bank transfer, etc.
    proof_path = Column(String(255), nullable=True)
    status = Column(Enum(ChallanStatus), default=ChallanStatus.GENERATED, nullable=False)
    approved_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    bulk_group_id = Column(String(50), ForeignKey("challan_bulk_groups.bulk_group_id"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    proof_uploaded_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    member = relationship("Member", back_populates="challans")
    campaign = relationship("Campaign", back_populates="challans")
    approved_by = relationship("User", foreign_keys=[approved_by_admin_id])
    bulk_group = relationship("BulkChallanGroup", back_populates="challans")


class BulkChallanGroup(Base):
    __tablename__ = "challan_bulk_groups"
    
    id = Column(Integer, primary_key=True, index=True)
    bulk_group_id = Column(String(50), unique=True, nullable=False, index=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    amount_per_month = Column(Float, nullable=False)
    total_amount = Column(Float, nullable=False)
    proof_file_id = Column(String(255), nullable=False)
    status = Column(String(20), default="pending_approval", nullable=False)  # pending_approval, approved, rejected
    months_list = Column(Text, nullable=False)  # JSON array of months
    challan_ids_list = Column(Text, nullable=False)  # JSON array of challan IDs
    admin_notes = Column(Text, nullable=True)
    approved_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    notes = Column(Text, nullable=True)  # Member notes
    
    # Relationships
    member = relationship("Member")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    approved_by = relationship("User", foreign_keys=[approved_by_admin_id])
    challans = relationship("Challan", back_populates="bulk_group")


class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    target_role = Column(Enum(UserRole), nullable=True)  # Send to specific role if null=all
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="notifications")


class Request(Base):
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    request_type = Column(String(50), nullable=False, default="question")
    subject = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    priority = Column(String(20), nullable=False, default="medium")
    status = Column(String(20), nullable=False, default="pending")
    admin_response = Column(Text, nullable=True)
    resolved_by = Column(String(255), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    created_by_user = relationship("User", back_populates="requests")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(255), nullable=False)
    entity_type = Column(String(50), nullable=False)  # Member, Challan, Campaign, etc.
    entity_id = Column(Integer, nullable=False)
    old_values = Column(Text, nullable=True)  # JSON
    new_values = Column(Text, nullable=True)  # JSON
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="audit_logs")
