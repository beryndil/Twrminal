-- Add a lifecycle flag to sessions: `closed_at` is a nullable ISO
-- timestamp. NULL means open (the default); any value means the
-- session has been marked closed and should render inside the
-- sidebar's collapsed "Closed" group instead of the main list.
--
-- Additive, nullable, no backfill. Existing sessions default to NULL
-- (open). A reorg op that touches a closed session auto-clears the
-- column — work resumed means the flag is stale (see routes_reorg).

ALTER TABLE sessions ADD COLUMN closed_at TEXT;
