-- Admin-recorded payments (maker-checker): who entered a challan, how it was paid, and who collected cash.
ALTER TABLE challans ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER REFERENCES users(id);
ALTER TABLE challans ADD COLUMN IF NOT EXISTS entry_source VARCHAR(20);
ALTER TABLE challans ADD COLUMN IF NOT EXISTS transaction_ref VARCHAR(100);
ALTER TABLE challans ADD COLUMN IF NOT EXISTS received_on DATE;
ALTER TABLE challans ADD COLUMN IF NOT EXISTS collected_by_user_id INTEGER REFERENCES users(id);
ALTER TABLE challans ADD COLUMN IF NOT EXISTS entry_notes TEXT;

-- Backfill: imported history was approved without an approver or proof; all other old rows were member-created.
UPDATE challans SET entry_source = 'import'
WHERE entry_source IS NULL AND LOWER(status::text) = 'approved' AND approved_by_admin_id IS NULL AND proof_path IS NULL;
UPDATE challans SET entry_source = 'self' WHERE entry_source IS NULL;
