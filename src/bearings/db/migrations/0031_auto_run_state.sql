-- Migration 0031: persist autonomous-driver run state across restarts.
--
-- The `AutoDriverRegistry` (src/bearings/agent/auto_driver_runtime.py)
-- has historically held running drivers in an in-memory dict on
-- app.state.auto_drivers. A systemd restart, app crash, or any other
-- lifespan teardown evaporated that registry — completed checklist
-- items stayed checked (the `checked_at` column is durable), but the
-- run itself silently disappeared. The 2026-04-24 overnight tour run
-- on checklist fae8f1a8501d4b24963fd5e3b2b18e7c lost 16 of 31 items
-- this way and never auto-resumed.
--
-- This table snapshots just enough state to rebuild a `Driver` and
-- re-spawn its `asyncio.Task` from a fresh-boot `lifespan`. The
-- driver's per-item state machine is still ephemeral by design — we
-- DON'T try to resume a leg mid-turn — but the outer loop's
-- bookkeeping (counters, `_attempted_failed` exclusion set, config
-- snapshot, failure detail) survives restart so the rehydrated
-- driver picks up at the next unchecked item with the right
-- failure-policy and exclusion behavior.
--
-- Lifecycle:
--   - `state='running'` while the driver task is live. Rehydrate path
--     reads exactly these rows on lifespan startup and re-creates
--     drivers with the snapshot seeded into the new instance.
--   - `state='finished'` when the driver returns a terminal
--     `DriverResult` (any of `COMPLETED`, `HALTED_*`). Kept on disk
--     for the audit trail; the rehydrate scan ignores them.
--   - `state='errored'` when the driver task raises. Same audit
--     value; rehydrate ignores.
--
-- One row per checklist session. PK on `checklist_session_id` mirrors
-- the in-memory registry's keying so a duplicate-run start hits the
-- same row.
--
-- `config_json` stores `dataclasses.asdict(DriverConfig)` so a
-- rehydrate reads back the same safety caps + permission mode the
-- original `start()` call configured. Bumping a field on `DriverConfig`
-- without a default (which we never do — the dataclass exists exactly
-- to be fully-defaulted) would break the rehydrate path; the existing
-- defaults are conservative enough that we don't expect breakage.
--
-- `attempted_failed_json` is a JSON array of integer item ids. In
-- `failure_policy='skip'` runs the driver excludes these from
-- `next_unchecked_top_level_item` lookups so the loop doesn't
-- re-pick the same uncompleted item forever. Persisting it keeps the
-- skip-set across restarts.
--
-- Best-effort writes: snapshot persistence wraps in try/except so a
-- write failure logs but doesn't crash the driver. The in-memory
-- counters remain authoritative for the running task's status; the
-- table is the rehydrate primer.

CREATE TABLE IF NOT EXISTS auto_run_state (
    checklist_session_id TEXT PRIMARY KEY
        REFERENCES sessions(id) ON DELETE CASCADE,
    state TEXT NOT NULL
        CHECK (state IN ('running', 'finished', 'errored')),
    items_completed INTEGER NOT NULL DEFAULT 0,
    items_failed INTEGER NOT NULL DEFAULT 0,
    items_skipped INTEGER NOT NULL DEFAULT 0,
    legs_spawned INTEGER NOT NULL DEFAULT 0,
    failed_item_id INTEGER,
    failure_reason TEXT,
    config_json TEXT NOT NULL,
    attempted_failed_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auto_run_state_state
    ON auto_run_state(state);
