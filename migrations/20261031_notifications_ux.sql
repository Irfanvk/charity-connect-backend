-- Notifications UX: deep links, push delivery stats, preferences, quiet hours.
-- Alembic is not configured; apply manually (also applied automatically by ensure_runtime_schema).
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS category VARCHAR(30);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS link_url VARCHAR(255);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS entity_type VARCHAR(30);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS entity_id INTEGER;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS is_urgent BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE users ADD COLUMN IF NOT EXISTS quiet_hours_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS quiet_hours_start VARCHAR(5);
ALTER TABLE users ADD COLUMN IF NOT EXISTS quiet_hours_end VARCHAR(5);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    endpoint TEXT NOT NULL UNIQUE,
    p256dh VARCHAR(255) NOT NULL,
    auth VARCHAR(255) NOT NULL,
    user_agent VARCHAR(500),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS vapid_key_id VARCHAR(32);
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS last_success_at TIMESTAMP;
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS last_failure_at TIMESTAMP;
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS last_failure_reason VARCHAR(255);
ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS device_label VARCHAR(100);

CREATE TABLE IF NOT EXISTS notification_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    category VARCHAR(30) NOT NULL,
    push_enabled BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS ix_notification_preferences_user_id ON notification_preferences (user_id);