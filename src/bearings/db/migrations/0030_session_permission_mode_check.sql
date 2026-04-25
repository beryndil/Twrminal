-- Migration 0030: enforce permission_mode enum at SQL level.
--
-- Migration 0012 added `sessions.permission_mode` as a free-form TEXT
-- column. The PermissionMode enum is enforced in
-- `set_session_permission_mode` at the Python layer, but a stray
-- INSERT/UPDATE that bypasses that helper (test fixture, manual repair,
-- future code path) can land an arbitrary string and the runner will
-- happily forward it to the SDK on the next attach.
--
-- SQLite can't ALTER an existing column to add a CHECK constraint —
-- the supported path is a full table rebuild, which is destructive on
-- a column referenced by FKs from `checklist_items` /
-- `checklist_items.chat_session_id` / `sessions.checklist_item_id`.
-- Use triggers instead: same enforcement surface, additive only.
--
-- Lifecycle:
--   AFTER INSERT and AFTER UPDATE OF permission_mode triggers raise
--   an ABORT if the new value is non-NULL and not one of the four
--   allowed PermissionMode literals. NULL stays valid (== "default"
--   per the runner's read path).
--
-- The schema.sql declaration carries the inline CHECK form so a fresh
-- DB minted from schema.sql gets the column-level constraint directly;
-- this migration is the equivalent for already-migrated DBs.

CREATE TRIGGER IF NOT EXISTS sessions_permission_mode_check_insert
BEFORE INSERT ON sessions
FOR EACH ROW
WHEN NEW.permission_mode IS NOT NULL
    AND NEW.permission_mode NOT IN
        ('default', 'plan', 'acceptEdits', 'bypassPermissions')
BEGIN
    SELECT RAISE(ABORT, 'invalid permission_mode');
END;

CREATE TRIGGER IF NOT EXISTS sessions_permission_mode_check_update
BEFORE UPDATE OF permission_mode ON sessions
FOR EACH ROW
WHEN NEW.permission_mode IS NOT NULL
    AND NEW.permission_mode NOT IN
        ('default', 'plan', 'acceptEdits', 'bypassPermissions')
BEGIN
    SELECT RAISE(ABORT, 'invalid permission_mode');
END;
