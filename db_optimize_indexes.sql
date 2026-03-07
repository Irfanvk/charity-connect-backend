-- Database optimization indexes for CharityConnect
-- Safe to run multiple times (uses IF NOT EXISTS)

-- Members
CREATE INDEX IF NOT EXISTS idx_members_status ON members(status);
CREATE INDEX IF NOT EXISTS idx_members_created_at ON members(created_at);

-- Challans
CREATE INDEX IF NOT EXISTS idx_challans_member_status ON challans(member_id, status);
CREATE INDEX IF NOT EXISTS idx_challans_status_created_at ON challans(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_challans_member_created_at ON challans(member_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_challans_type_month ON challans(type, month);
CREATE INDEX IF NOT EXISTS idx_challans_campaign_status ON challans(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_challans_approved_by ON challans(approved_by_admin_id);

-- Bulk groups
CREATE INDEX IF NOT EXISTS idx_bulk_groups_status_created_at ON challan_bulk_groups(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bulk_groups_member_created_at ON challan_bulk_groups(member_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bulk_groups_created_by ON challan_bulk_groups(created_by_user_id);

-- Invites
CREATE INDEX IF NOT EXISTS idx_invites_used_expiry ON invites(is_used, expiry_date);
CREATE INDEX IF NOT EXISTS idx_invites_created_by ON invites(created_by_admin_id);

-- Notifications
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread_created ON notifications(user_id, is_read, created_at DESC);

-- Campaigns
CREATE INDEX IF NOT EXISTS idx_campaigns_active_dates ON campaigns(is_active, start_date, end_date);

-- Audit logs
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_created ON audit_logs(entity_type, entity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action_created ON audit_logs(action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_created ON audit_logs(user_id, created_at DESC);

-- Refresh planner stats after index creation
ANALYZE;
