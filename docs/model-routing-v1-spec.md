# Bearings — Model Routing & Quota Awareness

**Version:** v1.0 spec
**Status:** Replaces the v0.6-era `BEARINGS_MODEL_ROUTING.md`. Written against the April 2026 Claude Code / Agent SDK / Claude Platform feature set.
**Audience:** Bearings authors and Claude Code instances tasked with implementing this spec.

---

## What this is

Bearings is a locally-hosted frontend over the Claude Agent SDK (Claude Code subscription auth). Sessions are organized by tags. Routing decides, per session and per turn, which model handles the request and whether it gets an Opus advisor for hard decisions.

This spec covers the routing layer and its associated quota-awareness surface.

## What this is not

Bearings does **not** reimplement features the SDK / Claude Code already provide. The following are explicitly out of scope:

- **Per-turn model classification.** No Haiku-as-classifier preflight before each session.
- **Automatic mid-session model switching.** Manual switching only, with a re-cost warning. The advisor tool handles "this turn needs more intelligence" without switching.
- **Custom prompt-cache management.** The SDK does this transparently.
- **A standalone token counter.** `ResultMessage.model_usage` provides per-model accounting per turn.
- **Reimplementing `opusplan`, `auto` effort, subagent model selection, or fallback_model.** Use them as-shipped.

The Bearings-unique value is: **persistent per-tag rule sets, quota-aware default shifts, an override-driven tuning loop, and a UI that exposes routing decisions transparently.**

---

## 1. The routing model

Routing has two layers, in this order:

```
Session creation
        │
        ▼
[ Layer 1: Executor + advisor selection ]
        │   - Tag rule fires → set executor, advisor, effort
        │   - System rule fires (no tag rule matched)
        │   - Default fallback (Sonnet executor, Opus advisor, auto effort)
        │
        ▼
[ Quota guard (Bearings) ]
        │   - If cross-model bucket < 20%: downgrade Opus → Sonnet, warn
        │   - If Sonnet bucket < 20%: downgrade Sonnet → Haiku, warn
        │   - "Force original" override one click away
        │
        ▼
[ Resolution ]
        │   - executor=opus → resolve to opusplan unless explicitly typed "opus"
        │   - effort=auto → use CLAUDE_CODE_EFFORT_LEVEL=auto
        │
        ▼
[ Send to Agent SDK ]
        │   - executor model + advisor tool registered
        │   - effort level set
        │   - fallback_model set to executor's tier-down (Sonnet → Haiku, Opus → Sonnet)
        │
        ▼
[ Per turn during session ]
        │   - Executor decides when to call advisor
        │   - Bearings observes via model_usage and renders advisor calls in UI
        │   - User can manually call advisor via /advisor in the input box
        │   - User can manually switch model via header dropdown (with re-cost warning)
```

There is no Layer 2 "in-flight switch logic." The advisor tool is the in-flight intelligence-escalation mechanism, and it lives at the API layer, not in Bearings.

---

## 2. The advisor tool — Bearings' default escalation primitive

The advisor tool (`advisor_20260301`, generally available behind beta header `advisor-tool-2026-03-01`, exposed in Claude Code via `/advisor` since v2.1.101) lets a cheap executor consult Opus mid-generation in a single API call. The executor decides when to consult; the advisor sees full conversation context server-side; advisor output is typically 400–700 text tokens (1,400–1,800 with thinking).

**Why Bearings defaults to executor + advisor instead of single-model:**

- Sonnet executor + Opus advisor: 2.7 SWE-bench Multilingual points above Sonnet solo (74.8% vs 72.1%), at 11.9% lower cost per task.
- Haiku executor + Opus advisor: ~2× BrowseComp score over Haiku solo (41.2% vs 19.7%), at 85% lower cost than Sonnet solo.
- No conversation-history re-cost (advisor sees the same shared context).
- No tonal shift or session-protocol confusion (the user is always talking to one executor).
- Failure mode is graceful: if no decision triggers an advisor call, the session is just a normal executor-only session.

**Default policy:**

| Executor | Default advisor | Default `max_uses` | Default effort |
|---|---|---|---|
| Sonnet 4.6 | Opus 4.6 (or Opus 4.7 once Bearings has been tested against it) | 5 | `auto` |
| Haiku 4.5 | Opus 4.6 | 3 | `auto` |
| Opus 4.7 | (none — same-model advisor is redundant) | — | `xhigh` (the Opus 4.7 default) |

A tag rule can override any of these.

**The advisor toggle in the new-session dialog:**

The model picker becomes a two-axis selector:

```
Executor:   [ Sonnet 4.6 ▾ ]
Advisor:    [ Opus 4.6 ▾ ]   [ ☑ enabled ]   [ max calls: 5 ▾ ]
Effort:     [ auto ▾ ]
```

When `Executor = Opus`, the advisor row collapses to a hint: "Opus is the executor — advisor not needed."

---

## 3. Tag routing rules

### Schema

```sql
CREATE TABLE tag_routing_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL DEFAULT 100,
    enabled INTEGER NOT NULL DEFAULT 1,

    -- Match
    match_type TEXT NOT NULL CHECK (match_type IN ('keyword', 'regex', 'length_gt', 'length_lt', 'always')),
    match_value TEXT,                                  -- NULL valid for match_type='always'

    -- Outcome
    executor_model TEXT NOT NULL,                      -- 'sonnet' | 'haiku' | 'opus' | full ID
    advisor_model TEXT,                                -- NULL = no advisor; 'opus' typical
    advisor_max_uses INTEGER DEFAULT 5,
    effort_level TEXT DEFAULT 'auto',                  -- 'auto' | 'low' | 'medium' | 'high' | 'xhigh'

    -- Documentation
    reason TEXT NOT NULL,                              -- shown in UI when this rule fires
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX idx_tag_routing_priority ON tag_routing_rules(tag_id, priority, enabled);

CREATE TABLE system_routing_rules (
    -- Same columns as tag_routing_rules but no tag_id.
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    priority INTEGER NOT NULL DEFAULT 1000,
    enabled INTEGER NOT NULL DEFAULT 1,
    match_type TEXT NOT NULL CHECK (match_type IN ('keyword', 'regex', 'length_gt', 'length_lt', 'always')),
    match_value TEXT,
    executor_model TEXT NOT NULL,
    advisor_model TEXT,
    advisor_max_uses INTEGER DEFAULT 5,
    effort_level TEXT DEFAULT 'auto',
    reason TEXT NOT NULL,
    seeded INTEGER NOT NULL DEFAULT 0,                 -- 1 = shipped default, 0 = user-added
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX idx_system_routing_priority ON system_routing_rules(priority, enabled);
```

### Match types

- **`keyword`** — case-insensitive substring match against the first user message of the session. `match_value` is a comma-separated list; any match triggers the rule.
- **`regex`** — Python `re.IGNORECASE` regex against the first user message. Compiled once per evaluation. Invalid regexes disable the rule and surface an error in the editor.
- **`length_gt`** / **`length_lt`** — message length in characters compared against `int(match_value)`.
- **`always`** — unconditional. Used as the lowest-priority fallback in system rules.

ML or embedding-based matchers are explicitly out of scope. The override-rate signal (Section 8) is how rules get tuned, not by classification accuracy.

### Evaluation

When a new session is created:

1. Collect all enabled rules from all tags applied to the session, in priority order across tags (lower priority number = checked first).
2. Walk the list, evaluating each rule against the first user message.
3. First match wins. Capture `executor_model`, `advisor_model`, `advisor_max_uses`, `effort_level`, `reason`.
4. If no tag rule matches, evaluate enabled system rules in priority order. Same first-match-wins semantics.
5. If no system rule matches either (which shouldn't happen given the seeded `always` fallback, but fail safe anyway), use the absolute default: Sonnet 4.6 executor + Opus 4.6 advisor + `auto` effort.
6. Apply the quota guard (Section 4). If the guard downgrades, capture `routing_source = 'quota_downgrade'` and surface the original-vs-actual choice in the UI.
7. Store the resulting decision on the session row and on each subsequent message row.

### Default seeded system rules

Priorities are sparse. Lower number = checked earlier.

| Priority | Match | Executor | Advisor | Effort | Reason |
|---:|---|---|---:|---:|---|
| 10 | keyword: `architect, design system, refactor across, multi-file, system design, plan mode, plan.md` | opus (resolves to opusplan) | (none — Opus solo) | xhigh | Hard architectural reasoning — Opus solo with extended thinking |
| 20 | keyword: `rename, format, lint, typo, fix indent, capitalize, sort imports, remove unused, add comment` | haiku | opus | low | Mechanical task — Haiku handles 90% of Sonnet quality at fraction of cost |
| 30 | keyword: `explore, find where, search the, map out, list all, locate` | haiku | opus | low | Exploration — Haiku is what Anthropic auto-selects for the Explore subagent |
| 40 | regex: `^(what\|where\|when\|who\|how do I) ` | haiku | opus | low | Quick lookup |
| 50 | length_lt: 80 | haiku | opus | low | Short query, simple task |
| 60 | length_gt: 4000 | sonnet | opus | high | Long context, complex problem |
| 1000 | always | sonnet | opus | auto | Workhorse default |

Notes on the defaults:

- **Opus only fires on the architect/design rule** at priority 10, and even there resolves to `opusplan` so execution drops to Sonnet automatically. This is intentional. The Sonnet-Opus SWE-bench gap is 1.2 points; Opus pulls ahead specifically on hard reasoning, not coding generally.
- **Haiku is used aggressively** because the Haiku-Sonnet gap is wider (~6 SWE-bench points) than Sonnet-Opus, but Haiku+Opus advisor recovers most of that gap on hard cases.
- **All Sonnet and Haiku defaults pair with the Opus advisor.** This is the major change from the v0.6 spec, which had no advisor concept.
- **Effort defaults to `auto` for the workhorse rule**, letting adaptive thinking decide per-step. Specific rules override (`xhigh` for architecture, `low` for quick lookups, `high` for long-context).

User-added system rules slot in between the seeded ones at any priority. Disabled rules are skipped, not deleted.

---

## 4. Quota guard — the Bearings-unique mechanic

Claude Code's `/usage` command surfaces the user's current quota state. Bearings polls this and uses it to shift routing defaults when budget runs low. This is the single feature Bearings ships that the CLI does not.

### The two buckets (Max plan, post-Nov 2025)

- **Cross-model overall bucket** — all models count.
- **Sonnet-only bucket** — only Sonnet usage counts. Sits underneath the overall.

Hitting either throttles. The buckets are independent: routing Opus → Sonnet doesn't burn the Sonnet bucket at the same rate as it saves the overall.

### Polling

A background task in `bearings.agent.quota` polls `/usage` every 5 minutes (or on-demand from the UI). Results cached in:

```sql
CREATE TABLE quota_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at INTEGER NOT NULL,
    overall_used_pct REAL,                             -- 0.0–1.0
    sonnet_used_pct REAL,
    overall_resets_at INTEGER,                         -- unix timestamp
    sonnet_resets_at INTEGER,
    raw_payload TEXT                                   -- JSON, for forward compatibility
);

CREATE INDEX idx_quota_recent ON quota_snapshots(captured_at DESC);
```

The most recent snapshot is read by the quota guard during routing.

### Guard rules

When routing resolves an executor/advisor pair, before sending to the SDK:

```
if overall_used_pct >= 0.80:
    if executor == 'opus':
        downgrade executor → 'sonnet', set routing_source = 'quota_downgrade'
    if advisor == 'opus':
        disable advisor (set advisor_model = NULL,
                         source = 'quota_downgrade',
                         reason = 'advisor disabled — overall quota ≥ 80%')

if sonnet_used_pct >= 0.80 and executor == 'sonnet':
    downgrade executor → 'haiku',
        set routing_source = 'quota_downgrade',
        keep advisor (advisor uses overall bucket, not Sonnet bucket)
```

**Each downgrade is reversible with one click** in the new-session dialog: "Quota low, downgraded to Sonnet — [Use Opus anyway]." The override is captured as `routing_source = 'manual_override_quota'` for analytics.

### Surfaced in the UI

The session header always shows two small bars: overall remaining %, Sonnet remaining %. They turn yellow at 80%, red at 95%. Hovering shows reset time. Clicking opens the Usage tab in the inspector.

This is the most concrete daily-use feature for someone who hits weekly limits regularly. It's not subtle: the bars are always there, and they get more aggressive as the week wears on.

---

## 5. Per-message tracking

The SDK already exposes per-model usage on every turn via `ResultMessage.model_usage`. Bearings persists the relevant fields per message — no custom token counting.

### Schema additions to `messages`

```sql
ALTER TABLE messages ADD COLUMN executor_model TEXT;        -- e.g. 'claude-sonnet-4-6'
ALTER TABLE messages ADD COLUMN advisor_model TEXT;         -- e.g. 'claude-opus-4-6' or NULL
ALTER TABLE messages ADD COLUMN effort_level TEXT;          -- 'auto'|'low'|'medium'|'high'|'xhigh'
ALTER TABLE messages ADD COLUMN routing_source TEXT;        -- 'tag_rule'|'system_rule'|'default'|'manual'|'quota_downgrade'|'manual_override_quota'
ALTER TABLE messages ADD COLUMN routing_reason TEXT;        -- the rule's reason string

-- From model_usage (per-model breakdown)
ALTER TABLE messages ADD COLUMN executor_input_tokens INTEGER;
ALTER TABLE messages ADD COLUMN executor_output_tokens INTEGER;
ALTER TABLE messages ADD COLUMN advisor_input_tokens INTEGER;       -- 0 if no advisor call
ALTER TABLE messages ADD COLUMN advisor_output_tokens INTEGER;
ALTER TABLE messages ADD COLUMN advisor_calls_count INTEGER DEFAULT 0;
ALTER TABLE messages ADD COLUMN cache_read_tokens INTEGER;
```

### Backfill for legacy data

Pre-v1 messages don't have these fields. The migration sets them best-effort from the session's `model` field with `routing_source = 'unknown_legacy'`. Analytics filter these out of override-rate calculations.

### Per-message UI

Every assistant message bubble carries a small badge in its corner:

- `Sonnet` (no advisor used this turn)
- `Sonnet → Opus×2` (Sonnet executor, advisor consulted twice)
- `Haiku → Opus×1`
- `Opus xhigh` (Opus solo at xhigh effort)

Hovering the badge shows the routing reason ("matched tag rule: bearings/architect — Hard architectural reasoning").

---

## 6. New-session dialog

Replaces the model-section dialog described in the v0.6-era `BEARINGS_MODEL_ROUTING.md`.

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│ New Session                                                 │
├─────────────────────────────────────────────────────────────┤
│ Tags:        [bearings] [arch-linux] [+]                    │
│ Working dir: [~/projects/bearings ▾]   [Browse]             │
│                                                             │
│ ── Routing (auto-resolved from tags + first message) ──     │
│ Executor:    [ Sonnet 4.6 ▾ ]                               │
│ Advisor:     [ Opus 4.6 ▾ ]   [ ☑ enabled ]   [ max: 5 ]    │
│ Effort:      [ auto ▾ ]                                     │
│                                                             │
│ ⓘ Routed from tag bearings rule "Workhorse default"         │
│                                                             │
│ Quota: ████████░░ overall 78%   ███░░░░░░░ sonnet 31%       │
│                                                             │
│ First message:                                              │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │                                                         │ │
│ │                                                         │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│                              [Cancel]   [Start Session]     │
└─────────────────────────────────────────────────────────────┘
```

### Reactive behavior

- Typing in the first-message field re-evaluates rules in real time (debounced ~300ms). The "Routed from..." line updates with the matched rule.
- Changing tags re-evaluates rules.
- If the user manually changes Executor / Advisor / Effort, the routed-from line changes to "Manual override" and the rule is no longer evaluated for this session.
- If the quota guard would downgrade the routed choice, a yellow banner appears: "Routing downgraded to Sonnet (overall quota at 81%). [Use Opus anyway]" — clicking restores the original.

### What's gone vs the v0.6 spec

- No "Suggested:" hint with apply button. The chosen executor/advisor IS the suggestion. One less click.
- No classifier preview. The Haiku-as-classifier feature is cut entirely.
- No max_budget_usd field (correctly cut earlier; on subscription auth it doesn't apply).

---

## 7. Mid-session controls

### Manual model switch (kept, with warning)

The conversation header has an executor dropdown showing the current model. Clicking opens a confirmation:

```
Switch executor: Sonnet → Opus
This will re-cost ~38,000 input tokens of conversation history at Opus rates.
Estimated impact on overall bucket: +1.4%

[Cancel]   [Switch]
```

The token estimate is computed client-side from the cached session token count. Estimates are explicitly labeled "estimated" because the SDK doesn't expose a "what would this cost" preview; the math is approximate.

### Manual advisor invocation

The user can type `/advisor` in the message input as the first token to force the executor to consult the advisor for that turn. This is independent of the rule system and doesn't change the session's routing config — it's a per-turn override.

### What's not in scope

- **No automatic mid-session switching.** Same as the previous spec; reasoning hasn't changed (re-cost + tonal/protocol concerns).
- **No automatic effort-level changes mid-session.** `auto` effort handles per-step adaptive thinking already.
- **No automatic advisor escalation by Bearings.** The executor decides when to call the advisor; that's the executor's role, not Bearings'.

---

## 8. Telemetry and the tuning loop

The override rate is the signal that drives rule revision. A rule with a high override rate is wrong, regardless of what it was supposed to do.

### Override-rate calculation

For each rule, weekly:

```
override_rate = (sessions where user manually changed executor or advisor before send) /
                (sessions where this rule fired)
```

Rules with `override_rate > 0.30` over the last 14 days are surfaced in the routing rule editor as "Review:" highlighted rows.

### Quota efficiency

Per-week aggregation:

```
- Total executor input/output tokens by model
- Total advisor input/output tokens
- Number of advisor calls
- Cache read tokens (a measure of how well caching is working)
- Quota at week start vs week end (from quota_snapshots)
```

Surfaced in the Usage tab as a rolling 7-day chart and a "weekly headroom remaining at this point in the week" line.

**Not surfaced:** "savings vs all-Sonnet baseline." On the dual-bucket plan, this number is misleading. Replaced with the headroom-remaining view.

### Manual escalation indicator

The number of times the user manually invoked `/advisor` in a session, or manually switched models mid-session, is logged. High counts on a particular tag suggest the tag's default rule should be tightened (e.g. always-on advisor instead of conditional).

---

## 9. API additions

```
GET    /api/tags/{id}/routing                   # list rules for tag
POST   /api/tags/{id}/routing                   # add rule
PATCH  /api/routing/{id}                        # update rule (tag or system)
DELETE /api/routing/{id}
PATCH  /api/tags/{id}/routing/reorder           # body: { ids_in_priority_order: [...] }

GET    /api/routing/system                      # list system rules
POST   /api/routing/system                      # add system rule
PATCH  /api/routing/system/{id}
DELETE /api/routing/system/{id}
PATCH  /api/routing/system/reorder             # body: { rule_ids: [id, id, ...] }
                                               # → reordered system rule list
                                               # Mirrors PATCH /api/tags/{id}/routing/reorder.
                                               # Frontend uses this single call instead of N
                                               # sequential PATCH /{id} calls.
                                               # DEFERRED to v1.1: feature 3 cleanup did not
                                               # implement; frontend uses N-PATCH workaround
                                               # (routingRules.ts reorderSystemRules) and is
                                               # fully functional without this endpoint.
                                               # Tracked as finding feature-3-001-extra.

POST   /api/routing/preview                     # body: { tags: [ids], message: "..." }
                                                # → { executor, advisor, advisor_max_uses,
                                                #     effort, source, reason,
                                                #     evaluated_rules: [...],
                                                #     quota_downgrade_applied: bool }

GET    /api/quota/current                       # latest quota snapshot
POST   /api/quota/refresh                       # force-refresh from /usage
GET    /api/quota/history?days=30               # quota_snapshots for the chart

GET    /api/usage/by_model?period=week
GET    /api/usage/by_tag?period=week
GET    /api/usage/override_rates?days=14        # for "Review:" highlighted rules
```

There is no `/api/routing/classifier` endpoint. The classifier is cut.

---

## 10. UI surfaces

### New: Quota bars in the session header

Always visible. Two small horizontal bars: overall remaining %, sonnet remaining %. Yellow at 80% used, red at 95%. Hover: reset time.

### Modified: Routing rule editor

Lives under each tag (tag → "Routing" subtab) and a global section under settings for system rules.

Each rule renders as a row:

```
[priority] [match-type ▾] [match-value..........] →
[executor ▾] +  [advisor ▾] [☑ enabled]  [effort ▾]
[reason....................]   [⋮]
```

Drag-handle on the left to reorder. Right-click `⋮`: Test against message, Duplicate, Disable, Delete.

**"Test against message"** is a deterministic dialog — it evaluates the rule's match condition against pasted text and shows the resulting routing decision. No LLM call. Test inputs are not stored.

### Modified: Inspector "Routing" subsection

Shows for the active session:

- Current executor + advisor models, source (rule / system / manual / quota_downgrade), and reason
- Per-message routing badge timeline (scroll-correlated with the conversation)
- Total advisor calls this session and total advisor tokens consumed
- Quota delta this session: tokens against overall bucket, against Sonnet bucket
- "Why this model?" expandable showing the rule evaluation chain

### New: Usage tab in the inspector

Replaces the v0.6 dashboard concept.

- **Headroom remaining** chart: rolling 7-day plot of overall bucket and Sonnet bucket consumption, with reset markers.
- **By model** table: tokens consumed this week, broken down by model.
- **Advisor effectiveness** widget: advisor calls / sessions, advisor tokens / total tokens, qualitative read of "is the advisor pulling its weight."
- **Rules to review** list: rules with override rate > 30% in the last 14 days, click to jump to the rule editor.

---

## 11. Build order

Each step is a coherent chunk for Claude Code.

1. **Schema migrations.**
   - `tag_routing_rules`, `system_routing_rules`, `quota_snapshots`
   - `messages` ALTER ADD COLUMN for routing/usage fields
   - Best-effort backfill of legacy messages with `routing_source = 'unknown_legacy'`

2. **Rule evaluation.** Pure function `bearings.agent.routing.evaluate(message, tag_ids, system_rules) → RoutingDecision`. Unit tests for priority ordering, match-type semantics, fallthrough behavior, advisor-disabled-on-Opus-executor.

3. **Default system rules seeded** at first run, idempotent on `seeded = 1`.

4. **`/usage` polling and quota guard.**
   - `bearings.agent.quota` background task polling every 5 minutes
   - `apply_quota_guard(decision, latest_snapshot) → decision'`
   - `quota_snapshots` writes
   - API endpoints: `/api/quota/current`, `/api/quota/refresh`, `/api/quota/history`

5. **API endpoints** for tag rules, system rules, preview.

6. **Per-message routing-source tracking.** Wire executor/advisor/effort/source/reason into the agent call path. Read `ResultMessage.model_usage` and persist to message rows.

7. **New-session dialog integration.** Reactive routing preview (debounced), advisor toggle, manual override capture, quota banner.

8. **Quota bars in session header.** Always-visible, yellow/red thresholds, hover for reset time.

9. **Header executor dropdown for mid-session switching** with the re-cost warning dialog.

10. **`/advisor` per-turn force-invoke** in the input box.

11. **Routing rule editor UI.** Rule rows, drag-reorder, deterministic test-against-message dialog, enable/disable.

12. **Inspector Routing subsection.** Per-message badge correlation, evaluation chain, why-this-model expandable.

13. **Usage tab in inspector.** Headroom chart, by-model table, advisor effectiveness, rules-to-review list.

14. **Override-rate aggregation.** Background task, 14-day rolling, surfaces rules with `override_rate > 0.30`.

Steps 1–7 give working routing. Steps 8–10 give the quota-aware and manual-control surfaces. Steps 11–14 give the tuning loop.

---

## 12. Non-decisions (explicit)

These have been considered and intentionally left out:

- **No Haiku-as-classifier preflight.** Cut. Reasoning: token cost, latency, RouteLLM evidence that LLM classification of this kind is mediocre, and the advisor pattern handles the "smart escalation" use case better.
- **No automatic mid-session model switching.** Manual only. Re-cost + tonal/protocol concerns are real model-behavior properties, not engineering problems.
- **No automatic advisor invocation by Bearings.** The executor decides when to consult; that's the design of the advisor tool. Bearings just exposes the toggle and tracks the calls.
- **No "savings vs all-Sonnet baseline" KPI.** Replaced with bucket-headroom view. The dual-bucket plan makes this baseline misleading.
- **No model-version pinning per rule.** Rules say `sonnet` / `haiku` / `opus`; Bearings resolves to the current canonical version. Users who want to pin a specific model override at the session level via the dropdown.
- **No cross-user shared rule libraries.** Single-user tool. Importing/exporting rule sets is potentially a v1.x feature if Dave specifically wants it.
- **No A/B testing of rules.** Override rate is the feedback mechanism. Anything more sophisticated is overkill for a personal tool.
- **No ML-trained routers.** Out of scope. If 6+ months of override telemetry shows clear failure modes that rules can't capture, revisit then with the logged data as training input.

---

## 13. Risks worth flagging

These are honest framings of where this design might be wrong:

1. **The advisor-tool numbers are Anthropic's own.** Sonnet+Opus advisor scoring 74.8% on SWE-bench Multilingual vs 72.1% solo is a 2.7-point lift on one benchmark. Independent verification is sparse as of this writing. The cost-savings claim (11.9% lower per task) is more solid because it's structural — the advisor does ~500 tokens, the executor does the bulk — but it depends on advisor invocation frequency that may differ from Anthropic's eval distribution. Bearings should treat the numbers as plausible defaults, not guarantees.

2. **The quota guard's 80% threshold is a guess.** Could be too conservative (downgrading when there was still plenty of room) or too liberal (failing to downgrade until it's too late). The right number is probably user-configurable and informed by Dave's actual mid-week consumption pattern. Ship at 80%, tune from logs after a month.

3. **`/usage` polling cadence affects responsiveness.** 5-minute polls mean the guard can be up to 5 minutes stale — fine for normal use, marginal during a sustained burst. If a session burns 10% of overall in 5 minutes, the next session inherits stale state. Mitigation: refresh on session creation.

4. **Mid-session switch token estimates are approximate.** The SDK doesn't expose a preview API. The estimate is computed from the cached session token count multiplied by the new model's input rate. Off by ±20% is plausible. UI labels it "estimated" honestly.

5. **Tag rule writers can produce nonsensical combinations.** A tag with 30 conflicting rules will have undefined behavior (priority ties resolve in insertion order). The UI prevents priority duplicates on creation; the user is responsible for keeping rule sets coherent. If this becomes a real problem in use, add a "rule conflict checker" to the editor in v1.x.

6. **Anthropic's third-party policy.** As long as Bearings is personal use, this is fine. Productization would require Anthropic approval — keep the README disclaimer prominent.

7. **The advisor tool is in beta.** `advisor-tool-2026-03-01`. Behavior or pricing could change. If it leaves beta or gets a behavior change, the routing layer's primary mechanism changes. Watch the API release notes.

---

## Appendix A: Field reference for `RoutingDecision`

```python
@dataclass(frozen=True)
class RoutingDecision:
    executor_model: str                # 'sonnet' | 'haiku' | 'opus' | full ID
    advisor_model: str | None          # 'opus' | None
    advisor_max_uses: int              # 0–N; ignored if advisor_model is None
    effort_level: str                  # 'auto' | 'low' | 'medium' | 'high' | 'xhigh'
    source: str                        # 'tag_rule' | 'system_rule' | 'default'
                                       # | 'manual' | 'quota_downgrade'
                                       # | 'manual_override_quota' | 'unknown_legacy'
    reason: str                        # human-readable explanation
    matched_rule_id: int | None        # NULL for 'default', 'manual', 'unknown_legacy'
    evaluated_rules: list[int]         # IDs of rules that were checked but didn't match,
                                       # for the "Why this model?" debug surface
    quota_state_at_decision: dict      # snapshot of overall_used_pct, sonnet_used_pct
                                       # at the moment of decision, for analytics
```

---

## Appendix B: Glossary

- **Executor** — the model that runs the session turn-by-turn. Sees all tool results, generates output. Default Sonnet.
- **Advisor** — the higher-intelligence model the executor consults mid-generation via the `advisor_20260301` tool. Default Opus. Server-side, single API call, full shared context.
- **Bucket** — a quota counter on the Max plan. Two relevant buckets: cross-model overall, Sonnet-only.
- **Effort level** — adaptive-thinking control. `auto` lets the model decide per-step; `low/medium/high/xhigh` are fixed levels. `xhigh` is Opus 4.7 only.
- **Quota guard** — Bearings logic that downgrades executor/advisor when bucket use exceeds a threshold.
- **Override rate** — fraction of sessions where the user manually changed routing before send. Used to identify rules that are wrong.

---

## Errata

Historical inconsistencies corrected during CCW-5 (spec consistency audit). Preserved here for traceability.

### E-1: `advisor_disabled_reason` (struck from §4)

The original §4 guard-rules block set a field `advisor_disabled_reason = 'quota_overall_high'` when the advisor was disabled due to quota pressure. This field does not exist in the frozen `RoutingDecision` dataclass (Appendix A). Code correctly followed Appendix A throughout. The body text has been updated: advisor-disabled state is conveyed via `advisor_model = None` (already in the original block), `source = 'quota_downgrade'`, and the `reason` string — all of which are `RoutingDecision` fields.

### E-2: `V0.2.0_SPEC.md` cross-reference (updated in §6)

§6 referenced `V0.2.0_SPEC.md` as the predecessor dialog spec. That file does not exist in the repository; the header of this document correctly identifies the predecessor as the v0.6-era `BEARINGS_MODEL_ROUTING.md`. The §6 reference has been updated to match.

### E-3: System-rule reorder endpoint (added to §9)

No system-rule reorder endpoint was specified, leaving the frontend to fall back on N sequential `PATCH /api/routing/system/{id}` calls when reordering. `PATCH /api/routing/system/reorder` has been added to §9 to match the tag-rule reorder surface. Implementation is deferred to feature 3 cleanup.
