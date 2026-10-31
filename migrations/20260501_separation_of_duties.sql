-- Separation of duties: reversal tracking + fund utilization two-person approval.
-- Also applied automatically (guarded) by ensure_runtime_schema() in app/database.py.

ALTER TABLE challans ADD COLUMN IF NOT EXISTS reversed_at TIMESTAMP;
ALTER TABLE challans ADD COLUMN IF NOT EXISTS reversed_by_admin_id INTEGER REFERENCES users(id);
ALTER TABLE challans ADD COLUMN IF NOT EXISTS reversal_reason TEXT;

ALTER TABLE challan_bulk_groups ADD COLUMN IF NOT EXISTS reversed_at TIMESTAMP;
ALTER TABLE challan_bulk_groups ADD COLUMN IF NOT EXISTS reversed_by_admin_id INTEGER REFERENCES users(id);
ALTER TABLE challan_bulk_groups ADD COLUMN IF NOT EXISTS reversal_reason TEXT;

ALTER TABLE fund_utilizations ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'fund_utilizations' AND column_name = 'status'
    ) THEN
        ALTER TABLE fund_utilizations ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'pending';
        -- Existing rows keep counting towards balances.
        UPDATE fund_utilizations SET status = 'approved', approved_at = created_at;
    END IF;
END $$;

ALTER TABLE fund_utilizations ADD COLUMN IF NOT EXISTS approved_by_admin_id INTEGER REFERENCES users(id);
ALTER TABLE fund_utilizations ADD COLUMN IF NOT EXISTS rejection_reason TEXT;
ALTER TABLE fund_utilizations ADD COLUMN IF NOT EXISTS reversed_at TIMESTAMP;
ALTER TABLE fund_utilizations ADD COLUMN IF NOT EXISTS reversed_by_admin_id INTEGER REFERENCES users(id);
ALTER TABLE fund_utilizations ADD COLUMN IF NOT EXISTS reversal_reason TEXT;
