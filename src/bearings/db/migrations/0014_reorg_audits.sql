-- Slice 5 of the Session Reorg plan
-- (`~/.claude/plans/sparkling-triaging-otter.md`). Persistent record
-- of every move/split/merge op so the source session can render a
-- "N messages moved to <target> at <timestamp>" divider past the 30s
-- undo window. The undo path deletes the corresponding audit row so
-- a cancelled op leaves no divider; that's cheaper than modelling
-- tombstones and matches user intuition ("nothing happened").
--
-- `target_session_id` is nullable + ON DELETE SET NULL so a merge
-- followed by `delete_source=true` (and later deletion of the target)
-- still leaves the audit row readable — the UI renders "(deleted
-- session)" when the FK is null. The snapshotted title is the label
-- shown in the divider so the row stays legible even if the target
-- is later renamed or deleted.
--
-- `op` is constrained to the three user-initiated operations. If a
-- future slice needs a new op name, add a new value with a dedicated
-- migration so old audit rows stay interpretable.

CREATE TABLE IF NOT EXISTS reorg_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    target_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    target_title_snapshot TEXT,
    message_count INTEGER NOT NULL,
    op TEXT NOT NULL CHECK (op IN ('move', 'split', 'merge')),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reorg_audits_source
    ON reorg_audits(source_session_id, created_at);
