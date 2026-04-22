-- Session pinning (Phase 4a.1 of docs/context-menu-plan.md). Introduces
-- a boolean column so the sidebar can float pinned sessions to the top
-- of their tag group, independent of recency. Pinning is a pure UX
-- affordance — no runner behavior changes, no prompt layer changes.
--
-- Per plan decision §2.2 (Archive is an alias for Close), there is NO
-- `archived_at` column. The v0.9.x release train uses the existing
-- `closed_at` as the archive state. A future major version may split
-- closed vs archived; the `session.archive` action ID stays stable so
-- the rename is a backend-only change when that day comes.
--
-- Idempotent: `ADD COLUMN` on SQLite raises if the column exists, but
-- the migration runner (see db/store.py) has already applied-migration
-- tracking so re-running this on an initialized database is a no-op at
-- the runner level.

ALTER TABLE sessions
    ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;

-- Unpinned is the 99% case, so no session is pre-pinned on backfill.
-- A partial index would speed "WHERE pinned = 1" listings but we don't
-- expect enough pinned rows to matter at the scales Bearings ships at
-- today (single-user localhost). If that changes, add:
--   CREATE INDEX idx_sessions_pinned ON sessions(pinned) WHERE pinned = 1;
