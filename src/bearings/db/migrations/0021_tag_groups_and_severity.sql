-- Tag groups + severity seed (v0.8.x). Introduces a second filter
-- dimension on the sidebar by grouping tags. The current user-
-- configurable tag set becomes the `general` group; a second `severity`
-- group holds the five-level urgency ladder every session now carries.
--
-- Column is free text with a CHECK constraint so future groupings
-- (status, phase, client, etc.) are a one-line CHECK widen. Reserved
-- word `group` deliberately avoided — `tag_group` reads fine in SQL and
-- maps to a plain attribute in Python / TS without quoting.
--
-- Invariants (enforced at the app layer, not the DB, per design):
--   - every session has exactly one tag whose tag_group = 'severity'
--   - on severity swap, the old severity tag is detached first
--   - deleting the severity tag orphans affected sessions (they simply
--     render without a shield until the user re-assigns); matches the
--     "physical law, not DB constraint" framing of the design chat.

ALTER TABLE tags ADD COLUMN tag_group TEXT NOT NULL DEFAULT 'general'
    CHECK (tag_group IN ('general', 'severity'));

-- Severity ladder, high → low urgency. Colors are the green→red ramp
-- from the design discussion; stored as Tailwind hex values so the
-- frontend can tint the shield SVG via `fill: <color>` directly without
-- a class-name lookup table. Sort order mirrors priority so the filter
-- panel renders Blocker first and Quality of Life last.
--
-- Idempotent: `tags.name` is UNIQUE, so re-running the migration is a
-- no-op on rows that already exist. If a user had already created a
-- tag literally named "Blocker" before this migration landed, the
-- INSERT OR IGNORE preserves their row — they can move it into the
-- severity group later via PATCH /tags/{id}.
INSERT OR IGNORE INTO tags (name, color, pinned, sort_order, created_at, tag_group)
VALUES
    ('Blocker',         '#dc2626', 0, 1, datetime('now'), 'severity'),
    ('Critical',        '#ea580c', 0, 2, datetime('now'), 'severity'),
    ('Medium',          '#f59e0b', 0, 3, datetime('now'), 'severity'),
    ('Low',             '#84cc16', 0, 4, datetime('now'), 'severity'),
    ('Quality of Life', '#10b981', 0, 5, datetime('now'), 'severity');

-- Backfill: every existing session that carries no severity tag gets
-- Low attached. Existing sessions have no opinion on severity and the
-- user's default is Low. `INSERT OR IGNORE` shrugs off the PK conflict
-- on session_tags re-runs; the NOT EXISTS guard keeps a session that
-- somehow already has a severity (e.g. one seeded by a prior partial
-- migration run) from getting a second severity attached.
INSERT OR IGNORE INTO session_tags (session_id, tag_id, created_at)
SELECT
    s.id,
    (SELECT id FROM tags WHERE name = 'Low' AND tag_group = 'severity'),
    datetime('now')
FROM sessions s
WHERE NOT EXISTS (
    SELECT 1 FROM session_tags st
    JOIN tags t ON t.id = st.tag_id
    WHERE st.session_id = s.id AND t.tag_group = 'severity'
);
