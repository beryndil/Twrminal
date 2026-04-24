-- Canonical schema for Bearings. Migrations in migrations/ apply in order.

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    working_dir TEXT NOT NULL,
    model TEXT NOT NULL,
    title TEXT,
    description TEXT,
    max_budget_usd REAL,
    total_cost_usd REAL NOT NULL DEFAULT 0,
    session_instructions TEXT,
    sdk_session_id TEXT,
    -- Persisted PermissionMode ('default' | 'plan' | 'acceptEdits' |
    -- 'bypassPermissions'). NULL treated as 'default' by the runner.
    -- See migration 0012.
    permission_mode TEXT,
    -- Nullable ISO timestamp. NULL = open (default). Non-null = the
    -- user marked the session closed and the sidebar renders it inside
    -- the collapsed "Closed" group. Reorg ops touching a closed session
    -- auto-clear the column. See migration 0015.
    closed_at TEXT,
    -- Session kind discriminator: 'chat' (the historical default) runs
    -- through the agent runner and renders a conversation; 'checklist'
    -- carries no runner and renders a structured item list from the
    -- `checklists` / `checklist_items` tables. The runner + WS + reorg
    -- endpoints guard on this column. See migration 0016.
    kind TEXT NOT NULL DEFAULT 'chat'
        CHECK (kind IN ('chat', 'checklist')),
    -- Inverse pointer for per-item paired chats (migration 0017).
    -- When non-NULL this chat session is "about" a specific checklist
    -- item; the prompt assembler injects a checklist-context layer on
    -- every turn so the agent can see the parent checklist, sibling
    -- items, and the current item's state. SET NULL cascade so a
    -- deleted item degrades the chat to a plain session with a
    -- "(checklist deleted)" breadcrumb rather than destroying history.
    checklist_item_id INTEGER REFERENCES checklist_items(id) ON DELETE SET NULL,
    -- View-tracking pair (migration 0020). `last_completed_at` stamps
    -- every runner MessageComplete so the sidebar can tell whether a
    -- session has produced output since the user last looked. NULL on
    -- sessions that have never finished an assistant turn.
    last_completed_at TEXT,
    -- `last_viewed_at` stamps every time the user focuses / selects
    -- the session. NULL means "never viewed." Unviewed indicator is
    -- computed at render time as
    --   last_completed_at IS NOT NULL AND
    --   (last_viewed_at IS NULL OR last_completed_at > last_viewed_at).
    last_viewed_at TEXT,
    -- Session pinning (migration 0022). Boolean — 0 = normal, 1 =
    -- pinned. The sidebar sorts pinned sessions to the top of their
    -- tag group regardless of recency. Per plan decision §2.2 there
    -- is no separate archived_at column; archive is an alias for
    -- close via the `session.archive` action ID.
    pinned INTEGER NOT NULL DEFAULT 0,
    -- Latched flag for the "needs attention — red flashing" sidebar
    -- indicator (migration 0029). Set to 1 when the runner emits an
    -- `ErrorEvent` for this session; cleared back to 0 when a later
    -- turn completes successfully. Closed sessions render no indicator
    -- regardless, so closing is the natural "I won't retry" out.
    error_pending INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    thinking TEXT,
    created_at TEXT NOT NULL,
    -- Populated on assistant turns from ResultMessage.usage. Nullable
    -- because user rows never carry usage and historical assistant
    -- rows predate 0011. See db/migrations/0011_message_token_usage.sql.
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_creation_tokens INTEGER,
    -- Set the moment a user message is re-queued by the runner-boot
    -- replay path after a mid-turn server restart (migration 0019).
    -- NULL on every user row that has not been replayed (the common
    -- case) and on every assistant row (the column is meaningless
    -- there). Written BEFORE the replay hits the queue so a second
    -- crash can't trigger an infinite replay loop.
    replay_attempted_at TEXT,
    -- Message flag pair (migration 0023). `pinned` floats the row in
    -- the conversation header; `hidden_from_context` drops it from the
    -- context window assembled for the next agent turn (the row stays
    -- in the DB and renders greyed in the conversation view). Both
    -- INTEGER 0/1, DEFAULT 0 so existing rows backfill correctly.
    pinned INTEGER NOT NULL DEFAULT 0,
    hidden_from_context INTEGER NOT NULL DEFAULT 0,
    -- Token→path mapping for terminal-style `[File N]` attachments
    -- (migration 0027). JSON array of
    --   `[{"n": 1, "path": "/abs/...", "filename": "f.log", "size_bytes": 1234}]`.
    -- NULL on any row without attachments (every assistant row and
    -- most user rows). Keeping the mapping here — rather than
    -- substituting paths into `content` — means the transcript can
    -- render chips on reload and the runner-boot replay path can
    -- re-substitute the same mapping when re-queueing an orphan turn.
    attachments TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    input TEXT NOT NULL,
    output TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id, started_at);
CREATE INDEX IF NOT EXISTS idx_tool_calls_message_id ON tool_calls(message_id);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    default_working_dir TEXT,
    default_model TEXT,
    -- Tag grouping dimension (migration 0021). 'general' = the
    -- original user-configurable tag set; 'severity' = the
    -- Blocker/Critical/Medium/Low/QoL urgency ladder every session
    -- carries. CHECK-constrained so typos never land in the column.
    -- The sidebar filter panel renders each group as its own section
    -- (HR divider between) and the app layer enforces
    -- "exactly one severity tag per session" on session create /
    -- tag attach — not enforced at the DB level on purpose, so a
    -- user deleting their severity tag just orphans the affected
    -- sessions without blocking the delete.
    tag_group TEXT NOT NULL DEFAULT 'general'
        CHECK (tag_group IN ('general', 'severity'))
);

CREATE TABLE IF NOT EXISTS session_tags (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_session_tags_tag ON session_tags(tag_id);

CREATE TABLE IF NOT EXISTS tag_memories (
    tag_id INTEGER PRIMARY KEY REFERENCES tags(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Session reorg audit trail (Slice 5 of the Session Reorg plan).
-- One row per move/split/merge op records where messages went and
-- when. The source session's conversation view renders these inline
-- as persistent dividers; the undo path deletes the row so cancelled
-- ops leave no trace. See migration 0014.
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

-- Checklist primitives (Slice 1 of nimble-checking-heron). A checklist
-- is a distinct session kind: exactly one `checklists` row per
-- session whose `kind = 'checklist'`, and N items hanging off it.
-- Cascade-on-delete sweeps items when the checklist goes, and sweeps
-- the checklist when its session goes. `parent_item_id` is present
-- for later nesting work — it stays NULL on top-level rows. See
-- migration 0016.
CREATE TABLE IF NOT EXISTS checklists (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checklist_id TEXT NOT NULL REFERENCES checklists(session_id) ON DELETE CASCADE,
    parent_item_id INTEGER REFERENCES checklist_items(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    notes TEXT,
    checked_at TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    -- Forward pointer for per-item paired chats (migration 0017).
    -- NULL when the user has never opened "Work on this" for the item;
    -- non-NULL = exactly one paired chat session was spawned. SET NULL
    -- cascade so deleting the paired chat reverts the item to the
    -- "no chat opened yet" state rather than destroying the item.
    chat_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_checklist_items_checklist
    ON checklist_items(checklist_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_checklist_items_parent
    ON checklist_items(parent_item_id);
-- Pairing lookups (migration 0017). Point queries in both directions
-- are common: ChecklistView pulls items-with-pairing per checklist,
-- and the prompt assembler reverse-looks-up the item from the
-- session id on every turn build.
CREATE INDEX IF NOT EXISTS idx_checklist_items_chat_session
    ON checklist_items(chat_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_checklist_item
    ON sessions(checklist_item_id);

-- Session templates (migration 0025). Stand-alone snapshot of the
-- fields needed to spawn a new session from the "Save as template"
-- action. No FK to the originating session — once extracted a
-- template outlives its source. `tag_ids_json` is a JSON array of
-- tag ids; unknown tag ids at instantiation time are silently
-- skipped.
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
