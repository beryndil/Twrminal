-- Session templates (Phase 9b of docs/context-menu-plan.md). A
-- template captures enough of a session's starting configuration to
-- spawn a new session with one click: the working_dir, model, the
-- first user prompt / session_instructions, and the set of tags to
-- attach on create.
--
-- The "Save as template" action on the sidebar session menu drops a
-- row here; the "New from template" path instantiates the saved row
-- into a fresh session via `POST /sessions/from_template/{id}`.
-- Templates themselves have no FK to the originating session — once
-- extracted they stand alone, so deleting the source session never
-- touches the template. Tags are stored by id in a JSON array to keep
-- the schema flat; missing tags at instantiation time are silently
-- skipped (tag may have been deleted since the template was saved).
--
-- Column shape per plan §4.3:
--   id TEXT PK          — uuid4 hex, stable across renames
--   name TEXT NN        — user-visible label shown in the picker
--   body TEXT           — nullable first-prompt body; NULL means
--                         "blank session, user types the first turn"
--   working_dir TEXT    — nullable; NULL inherits the configured
--                         default at instantiation time
--   model TEXT          — nullable; NULL inherits session defaults
--   session_instructions TEXT
--                       — nullable; copied verbatim to the new
--                         session's column if set
--   tag_ids_json TEXT NN
--                       — JSON-encoded `[int, int, ...]`. Empty list
--                         is legal and encoded as "[]". We don't split
--                         into a junction table because a template is
--                         a small, write-once blob — no query patterns
--                         need to join on tag membership.
--   created_at TEXT NN  — ISO-8601, UTC
--
-- Index on (created_at DESC) so the picker query ("newest templates
-- first") walks the index without a sort step. Name uniqueness is
-- intentionally NOT enforced at the DB level — two users of the same
-- local bearings instance (rare but possible) shouldn't hit an
-- IntegrityError trying to save a template that happens to share a
-- label with an older one.

CREATE TABLE IF NOT EXISTS session_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    body TEXT,
    working_dir TEXT,
    model TEXT,
    session_instructions TEXT,
    tag_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_templates_created
    ON session_templates(created_at);
