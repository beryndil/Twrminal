# Routing — observable behavior

Bearings assigns each session an executor model, an optional advisor
model, and an effort level before the first user message reaches the
Claude Agent SDK. This document covers what routing does and when it
changes the model choice; it does not prescribe implementation. For
numeric thresholds, dataclass shapes, and the full evaluation algorithm
see [docs/model-routing-v1-spec.md](../model-routing-v1-spec.md).

Sibling subsystems referenced here: [sessions](sessions.md).

---

## Priority ladder

Routing evaluation walks three tiers in order for every new session:

1. **Tag rules** — enabled rules attached to all tags on the session,
   ordered by priority ascending (lower number = checked first), with
   rule id as a tiebreaker across tags. First match wins;
   `source = 'tag_rule'`.
2. **System rules** — enabled global rules, same priority ordering.
   First match wins; `source = 'system_rule'`.
3. **Absolute default** — Sonnet executor, Opus advisor, `auto` effort;
   `source = 'default'`. Reached only when no rule of any tier matches.
   Normal operation seeds an `always`-type system rule as a fallback, so
   the absolute default is a fail-safe for a misconfigured or empty rule
   table.

Each rule has a match type: `always` (unconditional), `keyword`
(case-insensitive substring, comma-separated), `regex` (Python
`re.IGNORECASE`), `length_gt`, or `length_lt`. An invalid regex silently
disables the individual rule — the evaluation walk continues with the
remaining rules in the tier rather than aborting.

---

## Routing sources

The `source` field on a routing decision records how the model choice was
made. Observable values and when they appear:

| Source | When set |
|---|---|
| `tag_rule` | A tag rule fired. |
| `system_rule` | A system rule fired; no tag rule matched. |
| `default` | Absolute default; no rule of any tier matched. |
| `quota_downgrade` | Quota guard overrode the rule result (see below). |
| `manual` | User manually picked a model in the new-session dialog. |
| `manual_override_quota` | User clicked "Use [model] anyway" on a quota-downgrade banner. |

The source and its associated `reason` string are stored on the session
row and displayed in the routing badge (Inspector → Routing tab) as
tooltip text.

---

## Quota guard

The quota guard is a post-evaluation pass that downgrades the routed
model when usage buckets approach their limits. It runs after the
priority ladder so tag rules and system rules remain authoritative until
the budget forces a change.

### Snapshot cadence

`QuotaPoller` is a background task that polls the upstream `/usage`
endpoint on a fixed cadence (default: every 5 minutes, per
[docs/model-routing-v1-spec.md](../model-routing-v1-spec.md) §4). The
first poll fires immediately when the Bearings server starts rather than
waiting one full interval; subsequent polls follow the fixed cadence.

Each poll result is persisted as a row in the `quota_snapshots` table
regardless of whether the upstream endpoint was reachable — an
unreachable poll stores a "no info" row (both percentage fields `null`)
rather than silently dropping the sample.

The guard reads the **most recent `quota_snapshots` row** at routing
time; it does not trigger a fresh poll. Routing decisions can therefore
reflect quota state up to one poll interval old. The routing-badge
tooltip shows the `overall_used_pct` and `sonnet_used_pct` that were
current at decision time.

`POST /api/quota/refresh` forces an immediate poll outside the regular
cadence. The new-session routing preview and the Usage panel both expose
an on-demand refresh button that calls this endpoint.

### Never-polled branch — `/api/quota/current`

`GET /api/quota/current` returns the latest `quota_snapshots` row as
JSON. When **no snapshot has ever been recorded** — for example on a
fresh install, or on a database migrated from v0.17.x (which predates
the `quota_snapshots` table) — the endpoint returns **`404 Not Found`**
rather than `200` with an empty body.

This is the documented "never polled" state. It means the poller has not
yet had a chance to write its first row, not that the endpoint itself is
missing. Callers that probe for quota-endpoint availability must accept
both `200` and `404` as healthy responses. The daily probe and cutover
smoke scripts encode this as `accepted_status_codes = {200, 404}` for
the `quota_current` probe.

Once the first snapshot arrives (first poll after startup, or a manual
`POST /api/quota/refresh`), `GET /api/quota/current` returns `200` for
the lifetime of that database.

### Downgrade ladder

When a snapshot is available the guard applies two ordered steps:

**Step 1 — overall-bucket check.** If `overall_used_pct ≥ 80%`:

- An Opus or OpusPlan executor is downgraded to Sonnet.
- An Opus advisor is disabled (`advisor_model` set to `null`).
- `source` is set to `'quota_downgrade'`; `reason` carries the
  percentage (e.g. `"quota guard: overall used 81% — Opus → Sonnet"`).

**Step 2 — Sonnet-bucket check** (applied after step 1). If
`sonnet_used_pct ≥ 80%` and the executor after step 1 is Sonnet:

- Sonnet executor is downgraded to Haiku.
- The advisor is **preserved** — the advisor draws from the overall
  bucket, not the Sonnet bucket, so Sonnet exhaustion alone does not
  force advisor removal.

If neither threshold trips, the decision is returned unchanged except
that the current quota percentages are folded in for analytics. If a
bucket percentage is `null` in the snapshot the guard treats that bucket
as "no information" and skips its check — the guard fails open on
missing data rather than forcing unnecessary downgrades.

The 80% threshold is the `QUOTA_THRESHOLD_PCT` constant in
`bearings.config.constants`. Rationale and tuning notes:
[docs/model-routing-v1-spec.md](../model-routing-v1-spec.md) §13.

### User override

When the guard fires, the new-session dialog shows a yellow banner:

> "Routing downgraded to Sonnet (overall quota at 81%). [Use Opus anyway]"

Clicking **Use [model] anyway** restores the original pre-guard choice
and records `source = 'manual_override_quota'` so the override appears
in analytics. The override applies only to the session being created;
the next new session re-evaluates from the current snapshot.

---

## Routing preview endpoint

`POST /api/routing/preview` accepts a `{ tag_ids, first_message }` body
and returns a preview of the routing decision — including any quota-guard
downgrade — without creating a session. Used by the new-session form to
show the model assignment before the user clicks Create.

The response includes a `quota_downgrade_applied` boolean (true when
`source == 'quota_downgrade'`) so the frontend can conditionally render
the downgrade banner.

---

## Inspector Routing tab

Every session's final routing decision is stored on the session row and
on each message row (capturing the at-decision quota percentages). The
Inspector **Routing** tab surfaces:

- The `executor_model` and `advisor_model` chosen.
- The `source` and `reason` string.
- The `evaluated_rules` list — the ordered ids of every rule the walker
  tested, rendered as the evaluation chain for "Why this model?"
  debugging.
- The `quota_state_at_decision` percentages at the time routing ran.

---

## Daily probe — retry contract

`scripts/daily_probe.py` uses a blackbox-probe pattern: each endpoint is
attempted up to `PROBE_RETRY_ATTEMPTS` times (default: **3**) before a
FAIL result is recorded. A `PROBE_RETRY_BACKOFF_S` sleep (default:
**1.0 s**) separates consecutive attempts.

**Retriable conditions** (trigger a retry and continue to the next
attempt):

- Network-level failures: `URLError`, `TimeoutError`, `OSError` —
  e.g. connection refused during a `bearings-v1.service` restart.
- `HTTPError` whose status code is **outside** the probe's
  `accepted_status_codes` — e.g. HTTP 503 during a graceful restart.

**Non-retriable results** (returned immediately, no further attempts):

- A successful 2xx/3xx response from `urlopen`.
- An `HTTPError` whose status code is **inside** `accepted_status_codes`
  (e.g. 404 for `/api/quota/current` before the first quota snapshot).

When a probe passes on attempt *N* > 1, the `detail` field in the JSONL
log records the attempt count, e.g. `"ok status=200 (attempt 2/3)"`.
When all attempts are exhausted, the final `detail` reads
`"... (exhausted 3/3 attempts)"`.

The retry budget and backoff are overridable via `--retry-attempts` and
`--retry-backoff` CLI flags, which default to the `PROBE_RETRY_ATTEMPTS`
and `PROBE_RETRY_BACKOFF_S` constants in `scripts/daily_probe.py`.

---

## Probe log retention — `--max-age-days`

Both `scripts/daily_probe.py` and `scripts/diff_probe.py` apply
in-process log retention after writing the JSONL log for the current
run.

**Default retention window:** `PROBE_LOG_RETENTION_DAYS_DEFAULT = 30`
days. Files in the probe log directory whose names match the
`YYYY-MM-DD.log` pattern and whose date is strictly more than 30 days
before the current run time are deleted.

**Override:** `--max-age-days <N>` on either script overrides the
default. Setting `--max-age-days 0` disables pruning entirely (useful
during the dogfood window when full history is wanted).

**Pruning rules:**

- Only filenames matching `YYYY-MM-DD.log` are considered. Other files
  (`README`, `*.log.gz`, partial names, etc.) are silently skipped.
- A missing log directory is silently tolerated (first run, dry-run,
  different mount).
- `OSError` on individual unlinks is warning-logged and skipped; the
  probe does not abort.
- The prune call runs *after* `write_log()` succeeds, so today's log
  is always written before any old logs are removed.

The constant and the flag live in each script's own module; no shared
library is involved (stdlib-only constraint per the module docstrings).
