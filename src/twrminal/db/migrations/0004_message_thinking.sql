-- 0004_message_thinking.sql: persist extended-thinking output alongside
-- the assistant message. Sourced from Thinking events accumulated during
-- the turn. Nullable — only assistant turns with extended thinking
-- enabled populate this column.

ALTER TABLE messages ADD COLUMN thinking TEXT;
