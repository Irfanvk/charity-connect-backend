-- Member self-activation: existing (imported) members activate their own account,
-- an admin approves. Additive only; applied automatically at startup by
-- Base.metadata.create_all + ensure_runtime_schema(). Safe to run more than once.
ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_phone VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS welcome_pending BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS member_activations (
    id SERIAL PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id),
    member_code_entered VARCHAR(50) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    username VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    email VARCHAR(255),
    whatsapp_phone VARCHAR(20),
    last_paid_month VARCHAR(7),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    rejection_reason TEXT,
    admin_notes TEXT,
    reviewed_by_admin_id INTEGER REFERENCES users(id),
    reviewed_at TIMESTAMP,
    source_ip VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_member_activations_id ON member_activations (id);
CREATE INDEX IF NOT EXISTS ix_member_activations_member_id ON member_activations (member_id);
CREATE INDEX IF NOT EXISTS ix_member_activations_username ON member_activations (username);
CREATE INDEX IF NOT EXISTS ix_member_activations_status ON member_activations (status);
