-- CharityConnect Database Initialization Script
-- This script idempotently creates all database schema, relationships, and indexes
-- Safe to run multiple times

-- Enable UUID extension if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create ENUM types
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('superadmin', 'admin', 'member');
EXCEPTION WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE challan_status AS ENUM ('generated', 'pending', 'approved', 'rejected');
EXCEPTION WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE challan_type AS ENUM ('monthly', 'campaign');
EXCEPTION WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE notification_status AS ENUM ('sent', 'read', 'unread');
EXCEPTION WHEN duplicate_object THEN null;
END $$;

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(20) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role user_role DEFAULT 'member' NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_phone (phone),
    INDEX idx_role (role)
);

-- Create members table
CREATE TABLE IF NOT EXISTS members (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    member_code VARCHAR(50) UNIQUE NOT NULL,
    monthly_amount DECIMAL(10, 2) DEFAULT 0.0,
    address TEXT,
    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_member_code (member_code),
    INDEX idx_user_id (user_id),
    INDEX idx_status (status)
);

-- Create invites table
CREATE TABLE IF NOT EXISTS invites (
    id SERIAL PRIMARY KEY,
    invite_code VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(20),
    is_used BOOLEAN DEFAULT false,
    used_by_user_id INTEGER,
    expiry_date TIMESTAMP NOT NULL,
    created_by_admin_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (used_by_user_id) REFERENCES users(id),
    FOREIGN KEY (created_by_admin_id) REFERENCES users(id),
    INDEX idx_invite_code (invite_code),
    INDEX idx_email (email),
    INDEX idx_is_used (is_used),
    INDEX idx_expiry_date (expiry_date)
);

-- Create campaigns table
CREATE TABLE IF NOT EXISTS campaigns (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    target_amount DECIMAL(15, 2) NOT NULL,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_by_admin_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by_admin_id) REFERENCES users(id),
    INDEX idx_is_active (is_active),
    INDEX idx_created_by (created_by_admin_id),
    INDEX idx_date_range (start_date, end_date)
);

-- Create challans table
CREATE TABLE IF NOT EXISTS challans (
    id SERIAL PRIMARY KEY,
    member_id INTEGER NOT NULL,
    type challan_type NOT NULL,
    campaign_id INTEGER,
    month VARCHAR(20),
    amount DECIMAL(10, 2) NOT NULL,
    payment_method VARCHAR(50),
    proof_path VARCHAR(255),
    status challan_status DEFAULT 'generated' NOT NULL,
    approved_by_admin_id INTEGER,
    rejection_reason TEXT,
    bulk_group_id VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    proof_uploaded_at TIMESTAMP,
    approved_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
    FOREIGN KEY (approved_by_admin_id) REFERENCES users(id),
    INDEX idx_member_id (member_id),
    INDEX idx_status (status),
    INDEX idx_campaign_id (campaign_id),
    INDEX idx_bulk_group_id (bulk_group_id),
    INDEX idx_month (month)
);

-- Create challan_bulk_groups table
CREATE TABLE IF NOT EXISTS challan_bulk_groups (
    id SERIAL PRIMARY KEY,
    bulk_group_id VARCHAR(50) UNIQUE NOT NULL,
    member_id INTEGER NOT NULL,
    amount_per_month DECIMAL(10, 2) NOT NULL,
    total_amount DECIMAL(15, 2) NOT NULL,
    proof_file_id VARCHAR(255) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending_approval',
    months_list TEXT NOT NULL,
    challan_ids_list TEXT NOT NULL,
    admin_notes TEXT,
    approved_by_admin_id INTEGER,
    rejection_reason TEXT,
    created_by_user_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP,
    rejected_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (created_by_user_id) REFERENCES users(id),
    FOREIGN KEY (approved_by_admin_id) REFERENCES users(id),
    INDEX idx_bulk_group_id (bulk_group_id),
    INDEX idx_member_id (member_id),
    INDEX idx_status (status)
);

-- Add foreign key to challans for bulk_group_id
ALTER TABLE challans ADD CONSTRAINT fk_bulk_group 
    FOREIGN KEY (bulk_group_id) REFERENCES challan_bulk_groups(bulk_group_id)
    ON DELETE SET NULL;

-- Create notifications table
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    target_role user_role,
    is_read BOOLEAN DEFAULT false,
    read_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user_id (user_id),
    INDEX idx_is_read (is_read),
    INDEX idx_created_at (created_at)
);

-- Create audit_logs table
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    action VARCHAR(255) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER NOT NULL,
    old_values TEXT,
    new_values TEXT,
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user_id (user_id),
    INDEX idx_entity (entity_type, entity_id),
    INDEX idx_created_at (created_at),
    INDEX idx_action (action)
);

-- Seed initial admin user (password: admin123, bcrypt hash)
-- This is a default admin for initial setup - MUST be changed in production
INSERT INTO users (username, email, password_hash, role, is_active)
VALUES ('admin', 'admin@charitconnect.local', '$2b$12$8pMLxMNY7YBNaG5RZqQpKOzHMvZy7Q6VG7/qg5YHWwf7D8zG4qR0m', 'superadmin', true)
ON CONFLICT (username) DO NOTHING;

-- Create indexes for performance optimization
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_members_status ON members(status);
CREATE INDEX IF NOT EXISTS idx_challans_member_month ON challans(member_id, month);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id, created_at);

-- Create function to automatically update updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create triggers for updated_at
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_members_updated_at ON members;
CREATE TRIGGER update_members_updated_at BEFORE UPDATE ON members
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_campaigns_updated_at ON campaigns;
CREATE TRIGGER update_campaigns_updated_at BEFORE UPDATE ON campaigns
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_challans_updated_at ON challans;
CREATE TRIGGER update_challans_updated_at BEFORE UPDATE ON challans
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_challan_bulk_groups_updated_at ON challan_bulk_groups;
CREATE TRIGGER update_challan_bulk_groups_updated_at BEFORE UPDATE ON challan_bulk_groups
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Grant permissions (adjust for your actual user)
-- GRANT ALL PRIVILEGES ON DATABASE charity_connect TO charity_user;
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO charity_user;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO charity_user;
