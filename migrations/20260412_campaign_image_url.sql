-- Migration: 20260412_campaign_image_url
-- Add image_url column to campaigns table

ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS image_url VARCHAR(1024) NULL;
