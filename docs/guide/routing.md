# Routing

Bearings picks an executor model — and optionally an advisor model
— for every session you create, based on the priority ladder
defined in [routing v1](../model-routing-v1-spec.md). This guide
covers how to read, configure, and override that decision from the
UI.

For the full conceptual picture see
[../concepts.md §4](../concepts.md#4-routing-v1-in-one-page). For
observable wire behavior see
[../behavior/routing.md](../behavior/routing.md). For thresholds
and dataclass shapes see
[../model-routing-v1-spec.md](../model-routing-v1-spec.md).

## What you can do here

* [Read the routing badge on a message](#read-the-routing-badge)
* [Read the routing-preview line in the new-session dialog](#read-the-routing-preview)
* [Override the executor / advisor before starting a session](#override-routing-before-start)
* [Swap the executor mid-session](#swap-the-executor-mid-session)
* [Override a quota-downgrade banner](#override-a-quota-downgrade-banner)
* [Create a tag-specific routing rule](#create-a-tag-specific-routing-rule)
* [Create a system-wide fallback rule](#create-a-system-wide-fallback-rule)
* [Reorder rules within a tier](#reorder-rules-within-a-tier)
* [Disable a rule without deleting it](#disable-a-rule-without-deleting-it)
* [Read the "Why this model?" debug chain](#why-this-model-debug-chain)
* [Read the rules-to-review list](#rules-to-review)
* [Force a fresh quota snapshot](#force-a-fresh-quota-snapshot)

---

## Walkthrough

### Read the routing badge

Every assistant message carries a routing badge in its corner. The
label is one of:

| Label | Meaning |
|---|---|
| `Sonnet` | Sonnet executor, no advisor. |
| `Sonnet → Opus×2` | Sonnet executor, Opus advisor with `max_uses=2` budget remaining. |
| `Haiku → Opus×1` | Haiku executor, Opus advisor with one use remaining. |
| `Opus xhigh` | Opus executor with effort=xhigh. |

Hover the badge for the full **reason** ("matched tag rule:
bearings/architect — Hard architectural reasoning", or "quota
guard: overall used 81% — Opus → Sonnet"). The reason is the
canonical explanation; the badge is a glance-level indicator.

For the per-message timeline of every routing decision in the
session, open the [Inspector → Routing tab](inspector.md#routing-tab).

### Read the routing preview

The new-session dialog renders a live **routing-preview line**
under the routing controls:

* `Routed from tag rule: bearings/architect — Hard architectural reasoning`
* `Routed from system rule: long-message → Opus`
* `Manual override` (after you change any routing field by hand)
* `Default routing — Sonnet executor, Opus advisor (×5 budget)`
  (when no rule matches at all)

The preview updates ~300ms after each keystroke in the first-
message field, after each tag change, and after any manual routing
override. Backed by `POST /api/routing/preview` — the same
evaluator the actual session will use, run dry against `tag_ids`
and `first_message` without creating a session.

### Override routing before start

In the new-session dialog, override any of:

* **Executor model** — dropdown of available models.
* **Advisor model** — dropdown including `(none)`.
* **Advisor max uses** — number input (default 5).
* **Effort level** — `auto` / `low` / `medium` / `high` / `xhigh`.

Touching any of these flips the preview line to **Manual override**
and the session row records `source='manual'`. The override applies
only to this session's first turn; subsequent turns re-evaluate
based on the session's tags + the current quota snapshot.

### Swap the executor mid-session

Open the conversation header's **executor-model dropdown** (or the
Inspector Routing tab's executor control). Picking a different
model calls `PATCH /api/sessions/{id}/model` which invokes
`runner.set_model()`, so the next turn uses the new executor
without restarting the runner.

The swap is recorded with `source='manual'` on the next assistant
message's routing decision.

### Override a quota-downgrade banner

When the [quota guard](../concepts.md#44-quota-guard) downgrades
the routed choice, a yellow banner appears above the **Start
Session** button:

> *"Routing downgraded to Sonnet (overall quota at 81%). [Use Opus
> anyway]"*

Clicking **Use Opus anyway** restores the original pre-guard
choice. The session is created with `source='manual_override_quota'`
and the override is recorded in the override aggregator (visible
in the [Analytics](analytics.md) "rules to review" list if the
rule's override rate crosses 30% over 14 days).

The override applies only to the session being created. The next
new session re-evaluates from the current snapshot.

### Create a tag-specific routing rule

A tag rule fires when its tag is attached to the session AND its
match expression matches the first user message.

1. Navigate to **Tags** in the sidebar primary nav, or right-click
   any tag chip → **Edit tag**.
2. The tag editor shows the tag's metadata (name, color,
   default-model, `working_dir`) and a **Rules** section.
3. Click **+ Rule**. A row appears with:
   * **Match type** — `always` / `keyword` / `regex` /
     `length_gt` / `length_lt`.
   * **Match value** — keyword string (comma-separated for
     multiple), regex pattern, or integer length threshold.
   * **Executor** / **Advisor** / **Advisor max-uses** /
     **Effort** — the routed assignment when this rule fires.
   * **Priority** — integer; lower fires first.
   * **Enabled** — checkbox.
   * **Reason** — free-text, displayed in the badge tooltip and
     in the routing-preview line.
4. Save. The rule is persisted via `POST /api/routing/tag_rules/`.

A keyword expression like `architect, refactor, design` matches a
case-insensitive substring of any of those words against the first
message. A regex expression compiles with `re.IGNORECASE`; an
**invalid regex silently disables the rule** — the evaluation walk
continues past it without raising.

### Create a system-wide fallback rule

System rules fire when no tag rule matched. They live in
**Settings → Routing → System rules** (not on any tag).

1. Navigate to **Settings** → **Routing**.
2. The **System rules** section lists every rule in priority order.
3. Click **+ Rule** to add. Same shape as tag rules.
4. Save (`POST /api/routing/system_rules/`).

A standard install seeds an `always`-type system rule as the final
fallback so the absolute default branch (Sonnet exec / Opus advisor
/ auto effort) is reached only when the rule table is misconfigured
or empty.

### Reorder rules within a tier

Rules are walked in **priority ascending** order — lower number
fires first. Two ways to reorder:

* Edit the **Priority** integer on each rule.
* Drag the rule rows in the editor (the sort order writes to the
  priority column on drop).

Within a single priority, rules tie-break by rule id (creation
order). For tag rules across multiple tags on the same session,
the per-tag walk happens in the tag's own `sort_order`, then by
rule priority within each tag.

### Disable a rule without deleting it

Toggle the **Enabled** checkbox. Disabled rules are skipped during
evaluation but kept in the table for audit / re-enable. This is
the right action when you want to A/B-test a rule change without
losing the original.

`PATCH /api/routing/tag_rules/{id}` with `{"enabled": false}`.

### "Why this model?" debug chain

Open the [Inspector → Routing tab](inspector.md#routing-tab),
expand **"Why this model?"** for the most-recent turn (or any
selected turn). The expander shows:

1. The per-tag rule walk in priority order — which rules were
   tested, which match expression each used, why each one didn't
   match (or why one did).
2. The system-rule fallback walk.
3. The default-model line.
4. The quota guard's pre/post state — overall + Sonnet bucket
   percentages, what got downgraded.
5. The override decision (if any).

This is the primary debugging surface when a routing decision
surprises you.

### Rules-to-review

The **Inspector → Usage tab** and the **Analytics** page both
expose a **Rules to review** list — routing rules whose 14-day
override rate has crossed `OVERRIDE_RATE_REVIEW_THRESHOLD`
(default 30%). The user is overriding the rule's prediction often
enough to suggest the rule is wrong.

Click any row to jump to that rule's editor. Possible actions:

* Tighten the match expression (it's matching too broadly).
* Loosen it (the alternate model the user prefers should fire
  through a different rule).
* Disable the rule and let the next-tier rule take over.
* Delete the rule entirely.

The override aggregator
([`bearings.agent.override_aggregator`](../architecture-v1.md#114-bearingsagent--domain-layer))
maintains the rolling window. For the constant see
[../model-routing-v1-spec.md](../model-routing-v1-spec.md) §6.

### Force a fresh quota snapshot

The [quota poller](../concepts.md#44-quota-guard) polls the
upstream `/usage` endpoint every 5 minutes by default. The guard
reads the **most recent snapshot** at routing time — it does not
trigger a fresh poll itself. So routing decisions can reflect
quota state up to one poll-interval old.

Force an immediate poll outside the regular cadence:

* In the new-session dialog: the routing-preview area exposes a
  small refresh button next to the quota bars.
* In the Inspector Usage tab: the same refresh button.
* Direct: `POST /api/quota/refresh`.

`GET /api/quota/current` returns `404` when **no snapshot has ever
been recorded** (fresh install, or a database migrated from
v0.17.x which predates `quota_snapshots`). Once the first snapshot
arrives, it returns `200` for the lifetime of the database.

---

## Reference

### Routing sources

| Source value | When set |
|---|---|
| `tag_rule` | A tag rule fired. |
| `system_rule` | A system rule fired; no tag rule matched. |
| `default` | Absolute default; no rule of any tier matched. |
| `quota_downgrade` | Quota guard overrode the rule result. |
| `manual` | User picked the model in the new-session dialog or via the mid-session swap. |
| `manual_override_quota` | User clicked "Use [model] anyway" on a quota-downgrade banner. |

### Match types

| Type | Semantics |
|---|---|
| `always` | Unconditional match. |
| `keyword` | Case-insensitive substring; comma-separated list (any term hits). |
| `regex` | Compiles with `re.IGNORECASE`. **Invalid regex silently disables the rule** — walk continues past it. |
| `length_gt` | Matches when the first message body's character length is `> N`. |
| `length_lt` | Matches when the first message body's character length is `< N`. |

### Quota-guard downgrade ladder

Applied **after** the priority ladder picks a model, in this order:

1. **Overall bucket ≥ 80%** — Opus / OpusPlan executor → Sonnet;
   Opus advisor → null.
2. **Sonnet bucket ≥ 80%** — Sonnet executor → Haiku. Advisor
   preserved (advisor draws from the overall bucket, not the
   Sonnet bucket).

Either bucket reading `null` is treated as "no information" and
the corresponding check is skipped (fails open).

The 80% threshold is `QUOTA_THRESHOLD_PCT` in
`bearings.config.constants`. Tuning notes:
[../model-routing-v1-spec.md §13](../model-routing-v1-spec.md).

### Action surface

| Action | Trigger | Endpoint |
|---|---|---|
| Read badge | Hover on any assistant message corner | (UI only) |
| Read preview | New-session dialog routing-preview line | `POST /api/routing/preview` |
| Override before start | New-session dialog routing controls | (folded into `POST /api/sessions`) |
| Swap mid-session | Header executor dropdown / Inspector Routing | `PATCH /api/sessions/{id}/model` |
| Quota override | New-session banner **Use [model] anyway** | (folded into `POST /api/sessions` with `source=manual_override_quota`) |
| Create tag rule | Tag editor → **+ Rule** | `POST /api/routing/tag_rules/` |
| Create system rule | Settings → Routing → **+ Rule** | `POST /api/routing/system_rules/` |
| Edit rule | Click rule row | `PATCH /api/routing/{tag,system}_rules/{id}` |
| Delete rule | Rule row → trash icon | `DELETE /api/routing/{tag,system}_rules/{id}` |
| Reorder rules | Drag rule rows / edit Priority | `PATCH /api/routing/{tag,system}_rules/reorder` |
| Force quota poll | Refresh button next to quota bars | `POST /api/quota/refresh` |
| Read current quota | Quota bars | `GET /api/quota/current` |

---

## See also

* [../concepts.md §4](../concepts.md#4-routing-v1-in-one-page) —
  conceptual picture.
* [../model-routing-v1-spec.md](../model-routing-v1-spec.md) —
  numeric thresholds, dataclass shapes, full evaluation algorithm.
* [../behavior/routing.md](../behavior/routing.md) — observable
  wire contract.
* [inspector.md](inspector.md) — Inspector Routing tab.
* [analytics.md](analytics.md) — override-rate aggregator,
  advisor-effectiveness widget.
* [../api.md §routing](../api.md#routing),
  [../api.md §quota](../api.md#quota),
  [../api.md §usage](../api.md#usage).
* `src/bearings/agent/routing.py` — `evaluate()` pure function.
* `src/bearings/agent/quota.py` — `QuotaPoller` +
  `apply_quota_guard()`.
* `src/bearings/agent/override_aggregator.py` — rolling 14-day
  override-rate aggregation.
