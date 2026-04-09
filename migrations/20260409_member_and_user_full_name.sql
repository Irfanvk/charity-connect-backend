-- Add dedicated full_name storage and backfill existing records.
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);
ALTER TABLE members ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);

UPDATE users
SET full_name = username
WHERE full_name IS NULL;

UPDATE members m
SET full_name = u.full_name
FROM users u
WHERE m.user_id = u.id
  AND m.full_name IS NULL;
