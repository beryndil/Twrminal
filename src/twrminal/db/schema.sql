-- Canonical schema for Twrminal. Migrations in migrations/ apply in order.

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    working_dir TEXT NOT NULL,
    model TEXT NOT NULL,
    title TEXT,
    max_budget_usd REAL,
    total_cost_usd REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    thinking TEXT,
    created_at TEXT NOT NULL
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
