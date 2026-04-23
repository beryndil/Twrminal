-- Message flags (Phase 8 of docs/context-menu-plan.md). Two booleans
-- per message row, both DEFAULT 0 so existing rows backfill correctly
-- without touching them.
--
--   pinned INTEGER              — 1 = user marked this message to float
--                                 in the conversation header; 0 = normal.
--                                 Pure UX, no runner effect.
--   hidden_from_context INTEGER — 1 = drop this row from the context
--                                 window the agent sees on the next
--                                 turn. The message stays in the DB
--                                 and renders in the conversation view
--                                 (greyed) so the user can toggle it
--                                 back; the prompt assembler is the
--                                 only consumer that reads the column.
--
-- Kept as INTEGER (0/1) rather than a boolean because SQLite has no
-- native bool and every other flag column in this schema follows the
-- same pattern (session.pinned, reorg_audits.*, etc).
--
-- Skipped a 0023 slot when the plan was drafted — the Phase 7 /
-- checkpoints migration landed first as 0024. The runner applies by
-- filename sort, so 0023 slots in behind 0022 on a fresh boot and
-- gets picked up first on an already-bootstrapped database (next to
-- the applied-set lookup in db/_common.py:_apply_migrations).

ALTER TABLE messages
    ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;

ALTER TABLE messages
    ADD COLUMN hidden_from_context INTEGER NOT NULL DEFAULT 0;

-- No index. Both flags are scanned in-place when assembling the context
-- window (a single-session WHERE session_id = ? already drives the
-- existing idx_messages_session), and the sidebar "show pinned first"
-- view doesn't exist yet. Add a partial index if/when it does.
