-- Migration 0003: Vector search support tables
-- Adds 4 new tables for vector index state, projections, dirty queue, and build log.
-- Does NOT require sqlite-vec extension. Extension-dependent virtual table is in 0004.

CREATE TABLE IF NOT EXISTS vector_index_state (
  index_name          TEXT PRIMARY KEY,
  schema_version      TEXT NOT NULL DEFAULT '1',
  provider_type       TEXT NOT NULL DEFAULT 'local',
  provider_name       TEXT NOT NULL DEFAULT 'fastembed',
  provider_model      TEXT NOT NULL DEFAULT 'sentence-transformers/all-MiniLM-L6-v2',
  embedding_dim       INTEGER NOT NULL DEFAULT 384,
  distance_metric     TEXT NOT NULL DEFAULT 'cosine',
  quantization        TEXT NOT NULL DEFAULT 'float32',
  enabled             INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
  retrieval_language  TEXT NOT NULL DEFAULT 'en',
  last_incremental_at TEXT,
  last_full_rebuild_at TEXT,
  notes               TEXT,
  updated_at          TEXT NOT NULL
);

-- Insert default index state (disabled until doctor confirms environment)
INSERT OR IGNORE INTO vector_index_state (
  index_name, provider_type, provider_name, provider_model,
  embedding_dim, distance_metric, quantization, enabled,
  retrieval_language, updated_at
) VALUES (
  'default', 'local', 'fastembed',
  'sentence-transformers/all-MiniLM-L6-v2',
  384, 'cosine', 'float32', 0, 'en',
  datetime('now')
);

CREATE TABLE IF NOT EXISTS vector_projection (
  entry_id              TEXT PRIMARY KEY,
  entry_type            TEXT NOT NULL,
  logical_key           TEXT NOT NULL,
  revision              INTEGER NOT NULL DEFAULT 1,
  scope_ref             TEXT NOT NULL,
  source_language       TEXT,
  search_text_en        TEXT,
  search_text_en_hash   TEXT,
  canonical_json_hash   TEXT,
  projection_schema_ver TEXT NOT NULL DEFAULT '1',
  metadata_json         TEXT,
  updated_at            TEXT NOT NULL,
  is_deleted            INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_vector_projection_scope
  ON vector_projection(scope_ref, entry_type);

CREATE INDEX IF NOT EXISTS idx_vector_projection_deleted
  ON vector_projection(is_deleted, updated_at);

CREATE TABLE IF NOT EXISTS vector_dirty_queue (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id      TEXT NOT NULL,
  reason        TEXT NOT NULL DEFAULT 'insert',
  queued_at     TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error    TEXT,
  lock_owner    TEXT,
  locked_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_dirty_queue_entry
  ON vector_dirty_queue(entry_id, queued_at);

CREATE INDEX IF NOT EXISTS idx_dirty_queue_lock
  ON vector_dirty_queue(lock_owner, locked_at)
  WHERE lock_owner IS NOT NULL;

CREATE TABLE IF NOT EXISTS vector_build_log (
  run_id          TEXT PRIMARY KEY,
  mode            TEXT NOT NULL CHECK (mode IN ('incremental', 'full', 'partial')),
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  processed_count INTEGER NOT NULL DEFAULT 0,
  skipped_count   INTEGER NOT NULL DEFAULT 0,
  failed_count    INTEGER NOT NULL DEFAULT 0,
  duration_ms     INTEGER,
  summary_json    TEXT
);
