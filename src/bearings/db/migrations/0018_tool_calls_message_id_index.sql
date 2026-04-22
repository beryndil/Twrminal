-- 0018: speed up reverse lookups of tool_calls by message_id.
--
-- SQLite does not auto-index foreign key columns, so every
-- "tool_calls WHERE message_id = ?" lookup scans the table. The
-- primary consumer is `attach_tool_calls_to_message` (store helper)
-- and any message-scoped join that surfaces a message's tool calls.
--
-- Additive and idempotent: safe to apply on populated databases,
-- no row changes, reversible by DROP INDEX.

CREATE INDEX IF NOT EXISTS idx_tool_calls_message_id
    ON tool_calls(message_id);
