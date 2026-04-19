-- Projects + tag memories + session-scoped system-prompt override.
-- Additive only — existing sessions post-upgrade get project_id =
-- NULL and no session_instructions, behavior unchanged.
--
-- Layer assembly (base → project → tag memories → session override)
-- lands in a later slice (v0.2.5). This migration just establishes
-- the storage shape those layers read from.

CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    system_prompt TEXT,
    working_dir TEXT,
    default_model TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

ALTER TABLE sessions ADD COLUMN project_id INTEGER
    REFERENCES projects(id) ON DELETE SET NULL;

CREATE INDEX idx_sessions_project ON sessions(project_id);

-- Markdown content injected into the system prompt for every session
-- carrying this tag. Edited in-app; source of truth is the DB. One
-- memory per tag (PK collapses with tag id), FK CASCADE keeps the
-- memory row alive only while its tag exists.
CREATE TABLE tag_memories (
    tag_id INTEGER PRIMARY KEY REFERENCES tags(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Session-level override appended last in prompt assembly, so it
-- wins any conflict with project prompt or tag memories.
ALTER TABLE sessions ADD COLUMN session_instructions TEXT;
