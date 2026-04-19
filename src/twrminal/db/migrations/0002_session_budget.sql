-- 0002_session_budget.sql: per-session max_budget_usd cap for
-- `claude-agent-sdk`'s ClaudeAgentOptions.max_budget_usd. NULL = no cap.

ALTER TABLE sessions ADD COLUMN max_budget_usd REAL;
