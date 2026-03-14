-- Migration 0004: sqlite-vec virtual table
-- REQUIRES sqlite-vec extension to be loaded before running this migration.
-- This migration is handled separately from 0003 because vec0 virtual table
-- creation requires the extension. The migration runner must load the extension
-- before executing this file.
--
-- NOTE: This file is NOT applied by the standard run_migrations() call.
-- It is applied by the vector-doctor or init-vector-index command after
-- confirming the extension is available.
-- NOTE: Changing distance_metric requires dropping and recreating the virtual
-- table in existing databases. keep CREATE IF NOT EXISTS here; vector-doctor
-- should detect drift and instruct rebuild/recreate when needed.

CREATE VIRTUAL TABLE IF NOT EXISTS vec_memory_entries USING vec0(
  entry_id TEXT PRIMARY KEY,
  embedding FLOAT[384] distance_metric=cosine
);
