-- Migration 0002: FTS5 full-text search virtual table
-- Must be applied after 0001_initial_schema.sql.
-- FTS sync is managed in application code (not triggers).

CREATE VIRTUAL TABLE IF NOT EXISTS fts_documents USING fts5(
  entry_id  UNINDEXED,
  type      UNINDEXED,
  key,
  tags,
  body,
  tokenize="unicode61 remove_diacritics 1"
);
