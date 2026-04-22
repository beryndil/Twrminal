-- 0019: mark user messages whose turn has been re-queued after a
-- server restart so we never replay the same orphan twice.
--
-- Context: when `bearings.service` is stopped (SIGTERM) while a turn
-- is mid-flight, the `claude` SDK subprocess dies with exit 143 before
-- emitting the assistant reply. The user message is already persisted
-- but has no follower. On next runner boot we want to resubmit that
-- prompt so the turn eventually completes — but if that replay also
-- dies (second restart before reply) we must not loop forever. Setting
-- `replay_attempted_at` BEFORE enqueueing the replay is the fail-closed
-- guard: the next boot sees the column set and treats the prompt as
-- already handled, even if no assistant row exists yet.
--
-- Additive and idempotent: NULL on every existing and future user row
-- until a replay actually fires. Assistant rows never carry a value —
-- the column is meaningful only for user turns awaiting completion.

ALTER TABLE messages ADD COLUMN replay_attempted_at TEXT;
