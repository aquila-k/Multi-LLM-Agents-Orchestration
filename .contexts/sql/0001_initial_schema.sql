-- Migration 0001: Initial schema
-- Creates all core tables, indexes, and partial unique constraints.

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '1');
INSERT OR IGNORE INTO meta (key, value) VALUES ('applied_migrations', '[]');

CREATE TABLE IF NOT EXISTS event_log (
  id             TEXT PRIMARY KEY,
  event_type     TEXT NOT NULL CHECK (event_type IN (
                   'insert','activate','supersede','approve',
                   'reject','rebuild','lock_acquire','lock_release'
                 )),
  subject_family TEXT NOT NULL CHECK (subject_family IN ('memory','policy','system')),
  subject_id     TEXT,
  project_id     TEXT NOT NULL,
  scope_ref      TEXT NOT NULL,
  actor          TEXT NOT NULL DEFAULT 'agent',
  reason         TEXT,
  payload_json   TEXT,
  created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_log_project
  ON event_log(project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_event_log_subject
  ON event_log(subject_id, created_at);

CREATE TABLE IF NOT EXISTS entry_revisions (
  id                 TEXT PRIMARY KEY,
  schema_version     TEXT NOT NULL DEFAULT '1',
  record_family      TEXT NOT NULL DEFAULT 'memory'
                     CHECK (record_family = 'memory'),
  type               TEXT NOT NULL CHECK (type IN (
                       'project_profile','task_snapshot','session_snapshot',
                       'decision','episode','procedural_rule'
                     )),
  key                TEXT NOT NULL,
  scope_ref          TEXT NOT NULL,
  project_id         TEXT NOT NULL,
  repo_id            TEXT,
  worktree_id        TEXT,
  branch_ref         TEXT,
  task_id            TEXT,
  session_id         TEXT,
  scope_level        TEXT NOT NULL CHECK (scope_level IN (
                       'project','branch','task','session'
                     )),
  payload_json       TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN (
                       'active','pending','superseded','archived','draft'
                     )),
  revision           INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  load_policy        TEXT NOT NULL DEFAULT 'on_task_start'
                     CHECK (load_policy IN (
                       'always','on_task_start','on_session_resume',
                       'on_explicit_search','never_auto'
                     )),
  priority           INTEGER NOT NULL DEFAULT 50,
  author             TEXT NOT NULL DEFAULT 'agent',
  change_reason      TEXT,
  source_refs_json   TEXT,
  derived_from_json  TEXT,
  confidence         REAL CHECK (confidence IS NULL OR
                       (confidence >= 0.0 AND confidence <= 1.0)),
  review_status      TEXT,
  supersedes         TEXT REFERENCES entry_revisions(id),
  superseded_by      TEXT REFERENCES entry_revisions(id),
  approved_by        TEXT,
  approved_at        TEXT,
  tags_json          TEXT,
  related_files_json TEXT,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL
);

-- Active uniqueness: only one active revision per logical key
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_entry
  ON entry_revisions(record_family, type, key, scope_ref)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_entry_scope
  ON entry_revisions(scope_ref, type, status);

CREATE INDEX IF NOT EXISTS idx_entry_project
  ON entry_revisions(project_id, type, status);

CREATE INDEX IF NOT EXISTS idx_entry_task
  ON entry_revisions(task_id, status)
  WHERE task_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS active_entries (
  logical_key TEXT PRIMARY KEY,
  entry_id    TEXT NOT NULL REFERENCES entry_revisions(id),
  scope_ref   TEXT NOT NULL,
  type        TEXT NOT NULL,
  key         TEXT NOT NULL,
  revision    INTEGER NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_active_scope
  ON active_entries(scope_ref, type);

CREATE TABLE IF NOT EXISTS policy_revisions (
  id                     TEXT PRIMARY KEY,
  schema_version         TEXT NOT NULL DEFAULT '1',
  key                    TEXT NOT NULL,
  scope_ref              TEXT NOT NULL,
  project_id             TEXT NOT NULL,
  scope_level            TEXT NOT NULL CHECK (scope_level IN (
                           'project','branch','task','session'
                         )),
  target_kind            TEXT NOT NULL CHECK (target_kind IN (
                           'command','file_operation','network',
                           'vcs','tool','any'
                         )),
  match_pattern          TEXT NOT NULL,
  enforcement            TEXT NOT NULL DEFAULT 'confirm'
                         CHECK (enforcement IN ('warn','confirm','deny')),
  rationale              TEXT,
  allowed_when           TEXT,
  requires_human_approval INTEGER NOT NULL DEFAULT 1
                          CHECK (requires_human_approval IN (0, 1)),
  status                 TEXT NOT NULL DEFAULT 'active'
                         CHECK (status IN (
                           'active','pending','superseded','archived','draft'
                         )),
  revision               INTEGER NOT NULL DEFAULT 1,
  author                 TEXT NOT NULL DEFAULT 'agent',
  change_reason          TEXT,
  supersedes             TEXT REFERENCES policy_revisions(id),
  superseded_by          TEXT REFERENCES policy_revisions(id),
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_policy
  ON policy_revisions(key, scope_ref)
  WHERE status = 'active';

CREATE TABLE IF NOT EXISTS active_policies (
  logical_key TEXT PRIMARY KEY,
  policy_id   TEXT NOT NULL REFERENCES policy_revisions(id),
  scope_ref   TEXT NOT NULL,
  key         TEXT NOT NULL,
  enforcement TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
