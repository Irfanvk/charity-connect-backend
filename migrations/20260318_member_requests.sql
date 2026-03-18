-- v2.12 schema update: member requests + member notes
-- Execute manually for existing databases when needed.

ALTER TABLE members
ADD COLUMN IF NOT EXISTS notes TEXT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'requeststatus') THEN
        CREATE TYPE requeststatus AS ENUM ('pending', 'approved', 'rejected');
    END IF;
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'requesttype_v2') THEN
        CREATE TYPE requesttype_v2 AS ENUM (
            'monthly_amount_change',
            'profile_update',
            'complaint',
            'suggestion',
            'general'
        );
    END IF;
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

CREATE TABLE IF NOT EXISTS member_requests (
    id SERIAL PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    request_type requesttype_v2 NOT NULL,
    status requeststatus NOT NULL DEFAULT 'pending',
    subject VARCHAR(255),
    message TEXT NOT NULL,
    requested_amount DOUBLE PRECISION,
    current_amount DOUBLE PRECISION,
    requested_changes TEXT,
    admin_id INTEGER REFERENCES users(id),
    admin_notes TEXT,
    rejection_reason TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    resolved_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX IF NOT EXISTS ix_member_requests_member_id ON member_requests(member_id);
CREATE INDEX IF NOT EXISTS ix_member_requests_user_id ON member_requests(user_id);
