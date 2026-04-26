-- Migration 0033: tri-state checklist items (open / done / blocked).
--
-- Today a checklist item is binary: `checked_at` IS NULL means open,
-- `checked_at` IS NOT NULL means done. The autonomous driver
-- (src/bearings/agent/auto_driver.py) treats every non-done outcome
-- the same — `failure_policy=halt` stops the run, `failure_policy=skip`
-- advances but leaves the item open with a generic failure note.
--
-- That binary model has no way to express "this item is genuinely
-- outside the agent's reach and needs Dave to act" — pay a bill,
-- plug in hardware, supply a 2FA code, etc. Those items shouldn't
-- halt the run, shouldn't be silently skipped, and shouldn't have
-- their paired session auto-closed. They need a third state.
--
-- This migration adds the columns; the driver wiring, sentinel
-- grammar, cascade carve-out, and frontend rendering land in
-- subsequent commits per `~/.claude/plans/crimson-flagging-checklist.md`.
--
-- Columns:
--   `blocked_at` — ISO-8601 timestamp the agent flagged the item.
--     NULL on every existing row; non-null only after an
--     `CHECKLIST_ITEM_BLOCKED` sentinel from the autonomous driver.
--   `blocked_reason_category` — one of five enum values
--     (`physical_action`, `payment`, `external_credential`,
--     `identity_or_2fa`, `human_judgment`). Single-column CHECK
--     enforces the enum at write time; the driver's sentinel parser
--     also validates before reaching the DB.
--   `blocked_reason_text` — short reason text + the agent's `TRIED:`
--     log of attempts, embedded as plain text. No separate column for
--     `tried` — the parser reassembles the structured shape on read
--     when the UI needs to render it.
--
-- Mutual exclusion (`checked_at` IS NULL OR `blocked_at` IS NULL) is
-- NOT a CHECK constraint here: SQLite's ALTER TABLE ADD COLUMN
-- cannot add a multi-column CHECK after table creation. The
-- invariant is enforced at the application layer in
-- `set_item_blocked()` and in the close-cascade path that clears
-- `blocked_at` whenever `checked_at` is set.
--
-- Additive — no backfill. Every existing row reads back as
-- (NULL, NULL, NULL), which the model serializes the same way, and
-- the cascade query reads as "not blocked" the same as today.
ALTER TABLE checklist_items ADD COLUMN blocked_at TEXT;
ALTER TABLE checklist_items ADD COLUMN blocked_reason_category TEXT CHECK (
  blocked_reason_category IS NULL OR blocked_reason_category IN (
    'physical_action',
    'payment',
    'external_credential',
    'identity_or_2fa',
    'human_judgment'
  )
);
ALTER TABLE checklist_items ADD COLUMN blocked_reason_text TEXT;
