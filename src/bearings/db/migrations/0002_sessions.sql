-- 0002_sessions.sql — sessions table.
--
-- First real domain object. Stores the metadata for each agent
-- session driven by Bearings: working directory, model pin, kind
-- (chat | executor | orchestrator | fixer per the autonomous-execution
-- pattern in ~/.claude/CLAUDE.md), human title and "plug" description,
-- and an optional max_budget USD cap.
--
-- Notes:
-- - id is a TEXT-encoded UUID4 generated server-side. Clients don't
--   supply it; the service layer mints it. TEXT (not BLOB) so SQLite
--   GUI tools render it sanely and human-readable URLs work without
--   conversion.
-- - kind is CHECK-constrained at the SQL level so a typo can't smuggle
--   in an unknown value even if the service layer's enum check is
--   bypassed. Defense in depth.
-- - created_at / updated_at use SQLite's strftime-with-fractional
--   seconds so we keep millisecond ordering precision in test runs
--   that create rows in tight loops. The service layer touches
--   updated_at explicitly on every update.
-- - max_budget is REAL (nullable) — NULL means "no cap". Sentinel
--   values (0, -1) would be ambiguous; NULL is the SQL-native way.

CREATE TABLE sessions (
    id           TEXT PRIMARY KEY,
    working_dir  TEXT NOT NULL,
    model        TEXT NOT NULL,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    max_budget   REAL,
    kind         TEXT NOT NULL CHECK (kind IN ('chat', 'executor', 'orchestrator', 'fixer')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX sessions_kind_created_at ON sessions (kind, created_at DESC);
CREATE INDEX sessions_created_at ON sessions (created_at DESC);
