-- 0001_initial.sql — foundation migration.
--
-- Creates the minimum schema needed before §8 (sessions, tags, etc.)
-- lands. The schema_version table itself is created by the migration
-- runner before this file is applied (see migrations.py); this file
-- is responsible for everything else the foundation needs.
--
-- app_meta: simple key/value store for install-wide metadata. Lets
-- later code stamp first-run timestamps, install IDs, or one-shot
-- flags without minting a new table per concern. NOT a config store —
-- config lives in pydantic-settings (env vars / .env).

CREATE TABLE app_meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
