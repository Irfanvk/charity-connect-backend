-- Per-member monthly payment reminders. Additive only; applied automatically at
-- startup by Base.metadata.create_all + ensure_runtime_schema(). Safe to re-run.
ALTER TABLE users ADD COLUMN IF NOT EXISTS payment_reminder_enabled BOOLEAN;
ALTER TABLE users ADD COLUMN IF NOT EXISTS payment_reminder_day INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS payment_reminder_logs (
    id SERIAL PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    month VARCHAR(7) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_payment_reminder_member_month_kind UNIQUE (member_id, month, kind)
);
CREATE INDEX IF NOT EXISTS ix_payment_reminder_logs_id ON payment_reminder_logs (id);
CREATE INDEX IF NOT EXISTS ix_payment_reminder_logs_member_id ON payment_reminder_logs (member_id);
