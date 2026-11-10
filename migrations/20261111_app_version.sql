-- Which web app build each user's device last reported. Additive; applied at startup.
ALTER TABLE users ADD COLUMN IF NOT EXISTS app_version VARCHAR(40);
ALTER TABLE users ADD COLUMN IF NOT EXISTS app_version_seen_at TIMESTAMP;
