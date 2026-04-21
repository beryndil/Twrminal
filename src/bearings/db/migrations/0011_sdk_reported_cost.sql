-- 0011_sdk_reported_cost.sql: fix inflated session totals.
--
-- claude-agent-sdk's ResultMessage.total_cost_usd is CUMULATIVE for the
-- underlying CLI session — when we resume via `resume=sdk_session_id`
-- the value reported on turn N is the sum of spend from turn 1..N,
-- not the per-turn delta. The old `store.add_session_cost` added that
-- cumulative on every turn, inflating `total_cost_usd` quadratically
-- (after n uniform-cost turns, reported ≈ n(n+1)/2 × actual-per-turn).
--
-- Fix: track the last SDK-reported cumulative in its own column and
-- only accumulate the delta each turn. Historical per-turn costs were
-- never recorded, so we cannot reconstruct the correct totals — reset
-- every `total_cost_usd` to 0 so the next turn on any surviving
-- resumable session re-seeds the running total from the SDK's own
-- cumulative (which is correct).

ALTER TABLE sessions ADD COLUMN sdk_reported_cost_usd REAL NOT NULL DEFAULT 0;
UPDATE sessions SET total_cost_usd = 0;
