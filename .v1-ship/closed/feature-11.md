# Feature 11 closeout — Reliability & dogfood

**Closed:** 2026-05-08T06:08:52Z
**Closer session:** c8ec881d981d44009b8728d72adbff99
**Verifier session:** cb4ae047ef7c4a9ea767b00afbb1e550
**Executor sessions:** all 5 findings resolved via executor commits (no separate executor session IDs recorded in state.json; commits are the artifact chain)

## Findings register

| ID | Verdict | Status | Commit | Notes |
|---|---|---|---|---|
| feature-11-001 | STILL_OPEN | DONE | 9c1c1e50 | tests/test_daily_probe.py — 37 tests (≥29 required) covering run_probes, write_log, render_human, _result_to_jsonl, PROBES constant, retry semantics. No live-service dependency; uses monkeypatched urlopen + tmp_path. |
| feature-11-002 | STILL_OPEN | DONE | 4305a759 | docs/behavior/routing.md created (173-line initial draft). Contains §Quota guard (with never-polled 404 branch, QuotaPoller snapshot cadence, downgrade ladder, user override), §Routing preview endpoint, §Inspector Routing tab. Dangling lychee cross-reference from daily_probe.py:33 and cutover_smoke.py:173 resolved. Extended by commits bab924ab and 1c445ec7 with §Daily probe — retry contract and §Probe log retention. |
| feature-11-003 | STILL_OPEN | DONE | 6ed38d43 | config/bearings-v1-diff-probe.service + config/bearings-v1-diff-probe.timer — oneshot unit hardened (NoNewPrivileges, ProtectSystem=strict, ReadWritePaths=%h/.local/share/bearings-v1/diff-probes), After=bearings-v1-probe.service, OnCalendar=09:20. `systemd-analyze --user verify` passes (no output = clean). CHANGELOG.md install sequence updated. |
| feature-11-004 | STILL_OPEN | DONE | bab924ab | PROBE_RETRY_ATTEMPTS=3 + PROBE_RETRY_BACKOFF_S=1.0 constants; _attempt_probe() helper; _execute_probe() retry loop catches URLError/TimeoutError/OSError/HTTPError-outside-accepted; detail records attempt count when N>1 and "exhausted N/N" on budget exhaustion; --retry-attempts/--retry-backoff CLI flags; 3 new retry-semantics tests in test_daily_probe.py. routing.md §Daily probe — retry contract added in same commit. |
| feature-11-005 | STILL_OPEN | DONE | 1c445ec7 | PROBE_LOG_RETENTION_DAYS_DEFAULT=30 constant + prune_old_logs(log_dir, max_age_days, now) in both daily_probe.py and diff_probe.py; called after write_log() in both main() flows; --max-age-days CLI flag in both; max_age_days=0 disables; non-fatal on OSError; 5 tests each in test_daily_probe.py and test_diff_probe.py; routing.md §Probe log retention and CHANGELOG.md updated in same commit. |

## Behavior-spec coverage

Primary spec: `docs/behavior/routing.md`

End-to-end behaviors verified:

1. **Quota guard never-polled → 404 accepted as healthy** — PROBES tuple at `scripts/daily_probe.py:126` encodes `Probe("quota_current", "/api/quota/current", frozenset({200, 404}))`, matching `routing.md §Never-polled branch`. The `_attempt_probe` helper at line 191 returns a passing `ProbeResult` immediately when `code in probe.accepted_status_codes` — so a 404 is non-retriable and passes. Test: `test_execute_probe_accepted_status_404_passes` in `tests/test_daily_probe.py`.

2. **Retry-before-FAIL on connection refused / HTTP 503 during restart** — `_execute_probe` (daily_probe.py:247) loops up to `retry_attempts` (default 3), sleeping `retry_backoff_s` (default 1.0 s) between attempts; URLError/TimeoutError/OSError/HTTPError-outside-accepted trigger another attempt; detail annotates attempt count. Matches `routing.md §Daily probe — retry contract`. Tests: `test_execute_probe_retry_success_on_second_attempt` (passes on attempt 2, detail = "attempt 2/3"), `test_execute_probe_retry_all_attempts_exhausted` (detail = "exhausted 3/3"), `test_execute_probe_retry_http_503_then_200`.

3. **In-process log pruning after write_log in both probe scripts** — both `scripts/daily_probe.py:492` and `scripts/diff_probe.py:818` call `prune_old_logs(args.log_dir, args.max_age_days, now)` after `write_log` in their `main()` flow. `prune_old_logs` scans for `YYYY-MM-DD.log` files, deletes those older than the cutoff, skips non-matching names, and tolerates a missing log dir. Default window is 30 days; `--max-age-days=0` disables. Matches `routing.md §Probe log retention`. Tests in both test files: threshold boundary (day -31 deleted, day -29 retained), zero-disables, non-matching ignored, missing-dir noop.

## Defect-typology cross-check

| Class | Instances in feature 11 | Resolved by |
|---|---|---|
| Behavior partial | 2 — routing.md missing (#002); test regression net absent (#001) | 4305a759 (routing.md); 9c1c1e50 (test_daily_probe.py) |
| Module exists, unwired | 1 — diff_probe.py existed, no scheduling artifact | 6ed38d43 (systemd unit pair) |
| Promise unenforced (operational) | 2 — no retry contract (#004); no retention policy (#005) | bab924ab (retry); 1c445ec7 (retention) |

*Note: findings 004 and 005 map to "Promise unenforced" (reliability properties documented nowhere and not enforced). The audit typology table doesn't enumerate these as a named class but the pattern matches — the docstring asserted blackbox-probe properties and retention, neither was implemented.*

## Outstanding concerns

None. All five findings are P1/P2; all resolved DONE. `systemd-analyze --user verify` passes clean on the diff-probe unit pair. The retry tests use `retry_backoff_s=0.0` to avoid slow CI; that's correct for test purposes. No DONE_WITH_CONCERNS flags from executors.

## Sign-off

Feature 11 is **CLOSED**. All P0 and P1 findings resolved. All P2 findings resolved (none deferred).
