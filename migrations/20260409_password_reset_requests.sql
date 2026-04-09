-- Password reset requests table
CREATE TABLE IF NOT EXISTS password_reset_requests (
    id SERIAL PRIMARY KEY,
    identifier VARCHAR(255) NOT NULL,           -- email / username / phone submitted by requester
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,  -- resolved user, nullable until matched
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | approved | rejected | used
    reset_token VARCHAR(128) UNIQUE,            -- generated on admin approval
    token_expires_at TIMESTAMP,                 -- token valid for 24h
    admin_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    admin_notes TEXT,
    rejection_reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    resolved_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_prr_status ON password_reset_requests(status);
CREATE INDEX IF NOT EXISTS idx_prr_token ON password_reset_requests(reset_token);
CREATE INDEX IF NOT EXISTS idx_prr_user_id ON password_reset_requests(user_id);
