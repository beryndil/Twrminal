-- Persist the per-session permission mode so plan / acceptEdits /
-- bypassPermissions survive WebSocket reconnects and browser reloads.
-- Pre-0012 the runner always started at `default` on attach, so a user
-- who'd picked `plan` would silently drop back to `Ask` after a refresh
-- and see approval prompts reappear mid-turn. The four valid values
-- match claude-agent-sdk's PermissionMode literal:
-- 'default' | 'plan' | 'acceptEdits' | 'bypassPermissions'.
--
-- NULL means "no explicit mode set" and is treated as 'default' by
-- the runner; existing rows get NULL on backfill so behavior is
-- unchanged for sessions created before this migration.

ALTER TABLE sessions ADD COLUMN permission_mode TEXT;
