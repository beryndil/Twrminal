# Analytics

The Analytics page (`/analytics`) is Bearings' cross-session
rollup view. It exists because Bearings sits in the request path —
every turn passes through it — so we can measure where the
subscription bucket is going **per tag, per session, per injected
context block** without a separate observability layer.

The full spec is in [BEARINGS_ANALYTICS_v1.md](../../BEARINGS_ANALYTICS_v1.md)
(at the repo root). This guide is the user-facing walkthrough.

## What you can do here

* [Read the bucket attribution view](#read-the-bucket-attribution-view)
* [Read the redundancy / repeated-plug view](#read-the-redundancy--repeated-plug-view)
* [Promote a repeated plug to a tag memory](#promote-a-repeated-plug-to-a-tag-memory)
* [Promote a repeated plug to an `on_open.sh` hook](#promote-a-repeated-plug-to-an-on_open-hook)
* [Read the plug-length monitor](#read-the-plug-length-monitor)
* [Suppress a warning you've reviewed](#suppress-a-warning-youve-reviewed)
* [Start a new session with a freshly-drafted plug](#start-a-new-session-with-a-fresh-plug)
* [Read advisor effectiveness + rules to review](#advisor-effectiveness--rules-to-review)

---

## Walkthrough

### Read the bucket attribution view

The first card on the Analytics page answers *"which tags are
consuming the bucket fastest?"*

You see:

* a **per-tag stacked bar** of the current week's bucket
  consumption (input + output + cache-read tokens, split by model
  to respect the tokenizer-aware aggregation rule — Opus 4.7's
  tokenizer produces up to 35% more tokens for identical text);
* a **headroom remaining** indicator at the top — current bucket
  usage as a percentage of the cap;
* a **burn rate** sparkline showing the last 7 days' daily burn
  with a projected exhaust line.

Hovering any tag bar shows the breakdown by model and by session.
Clicking a tag opens its tag editor (you can adjust routing rules
to throttle high-burn tags from there — see [routing](routing.md)).

The view is read from the `turns` table populated by
`bearings.web.routes.analytics` capturing every assistant turn's
token usage. Backend: `GET /api/analytics/attribution`.

### Read the redundancy / repeated-plug view

The second card answers *"which injected context blocks are
repeating across sessions?"*

A **plug** in this context is the layer Bearings injects at
session start (and that Claude Code reloads on `/compact`):
`CLAUDE.md`, tag memories, system-prompt additions, MCP tool
descriptions, skill descriptions. It is **not** the conversation
that grows turn-by-turn.

The view shows:

* a **table of plug-block hashes** ordered by repeat count
  (highest first);
* per row: the block's first 80 chars (preview), the count of
  distinct sessions in which it appeared, the latest session it
  appeared in, the token cost per occurrence, the cumulative
  token cost.

Clicking a row opens a **diff view** showing the block content
verbatim and its appearances across sessions. From the diff view
you can promote the block (next two sections) or suppress its
warning.

Backend: `GET /api/analytics/redundancy`,
`GET /api/analytics/plug-blocks/{hash}`,
`GET /api/analytics/plug-blocks/{hash}/versions`.

### Promote a repeated plug to a tag memory

In the diff view for any plug-block:

1. Click **Promote → tag memory**.
2. A modal opens with a **target tag** picker (the tag classes
   that appeared in the sessions where this block was injected
   are preselected).
3. Pick the tag, optionally edit the title, optionally edit the
   body.
4. Save. The promotion fires
   `POST /api/analytics/plug-blocks/{hash}/promote-to-tag-memory`
   which:
   * creates a new memory row under the target tag with the
     block's body;
   * marks the block hash as "promoted-to-tag-memory" in the
     redundancy table so it stops appearing in future scans;
   * is **idempotent** — re-promoting the same hash to the same
     tag returns the existing memory rather than creating a
     duplicate.

The next session you create with that tag will see the block via
the [memories](vault-and-memories.md) overlay rather than via the
ad-hoc injection path — same content, less re-sending.

### Promote a repeated plug to an `on_open` hook

In the diff view:

1. Click **Promote → on_open.sh**.
2. The modal helps you compose an `on_open.sh` hook that
   reproduces the block on session start (typically by writing it
   to the `.bearings/` directory or by emitting it inline).
3. Save. The promotion fires
   `POST /api/analytics/plug-blocks/{hash}/promote-to-on-open`.

Same idempotency + deduplication semantics as the tag-memory
path.

### Read the plug-length monitor

The third card monitors the cumulative byte size of every
session's plug at session-start. The view shows:

* a **sessions list** with each session's plug-length category:
  green / yellow / red against the configured thresholds;
* a **distribution histogram** so you see whether the tail is
  fat (most sessions are green but a few are red) or skewed
  (every session is creeping into yellow).

Clicking a yellow / red session opens its **plug-summary** —
which blocks contributed the bytes — so you can identify the
culprit (often a single oversize tag memory or a verbose
`CLAUDE.md` walk-up).

Per the spec, the warnings are **soft** — yellow is a dismissible
suggestion, red is a persistent banner, neither blocks work. The
user makes the call; the system surfaces the data.

Backend: `GET /api/analytics/sessions/{session_id}/plug-summary`.

### Suppress a warning you've reviewed

Right-click any warning row → **Suppress this warning**. The
suppression is recorded at the level you suppressed at (per-
block, per-session, or globally for the rule). Suppressed warnings
are hidden from the default view; a *"show suppressed"* toggle
in the card header re-includes them.

Backend: `POST /api/analytics/warnings/suppress`.

### Start a new session with a fresh plug

The Analytics card carries a **Start new session with fresh plug**
button. Clicking it:

1. Calls `GET /api/analytics/draft-new-session` — the backend
   asks Claude (via the AI-draft path) to draft a slimmed plug
   based on your current redundancy + length data.
2. Opens a modal showing the drafted plug for review.
3. You edit the draft, accept it, or cancel.
4. On accept, fires `POST /api/analytics/sessions/from-draft` to
   create the new session with the drafted plug as its system-
   prompt overlay.

This is the canonical workflow for "I've been seeing red plug-
length warnings and I want to start fresh on a leaner context."

### Advisor effectiveness + rules to review

Two smaller widgets at the bottom of the Analytics page surface
data the [Inspector → Usage tab](inspector.md#usage-tab) also
shows:

* **Advisor effectiveness** — the proportion of advisor-only
  outcomes (executor turn satisfied by advisor planning) vs full
  escalations (advisor planning was used but the executor still
  did the work). Tune advisor `max_uses` per [routing](routing.md)
  rule based on this number.
* **Rules to review** — routing rules whose 14-day override rate
  has crossed `OVERRIDE_RATE_REVIEW_THRESHOLD` (default 30%).
  Click any row to jump to the rule's editor.

---

## Reference

### What the Analytics page does NOT do

* **No cross-session semantic comparison.** The "are these two
  blocks similar?" question would need an LLM call inside the
  tracker, which is out of scope.
* **No per-token dollar amounts.** The user is on a subscription
  plan; the bucket runs out, then more is purchased. Bucket
  headroom + burn rate are the primary signals — never tokens-
  as-cents.
* **No conversation-history token tracking.** Conversation
  history is Claude Code's domain (handled by `/compact`); the
  analytics layer is concerned with the *injected* layer that
  Bearings owns.
* **No "savings vs all-Sonnet baseline" KPI.** The spec retired
  this; the routing override aggregator is the canonical signal
  for routing fitness.

### Tokenizer-aware aggregation invariant

> **Never aggregate token counts across models without splitting
> by model first.**

The schema enforces this — every `turns` row carries its `model`
field. Aggregation queries that don't group by model are bugs.
Opus 4.7's tokenizer produces up to 35% more tokens for identical
text vs prior Opus versions, so naive cross-model totals are
meaningless.

### Action surface

| Action | Trigger | Endpoint |
|---|---|---|
| Bucket attribution | Page load | `GET /api/analytics/attribution` |
| Redundancy table | Page load | `GET /api/analytics/redundancy` |
| Plug-block detail | Click table row | `GET /api/analytics/plug-blocks/{hash}` |
| Plug-block versions | Detail view tab | `GET /api/analytics/plug-blocks/{hash}/versions` |
| Promote → tag memory | Diff view → button | `POST /api/analytics/plug-blocks/{hash}/promote-to-tag-memory` |
| Promote → on_open.sh | Diff view → button | `POST /api/analytics/plug-blocks/{hash}/promote-to-on-open` |
| Plug-length monitor | Page load | `GET /api/analytics/turns` (filtered) |
| Per-session plug summary | Click monitor row | `GET /api/analytics/sessions/{session_id}/plug-summary` |
| Suppress warning | Right-click → Suppress | `POST /api/analytics/warnings/suppress` |
| Draft fresh plug | **Start new session…** | `GET /api/analytics/draft-new-session` |
| Create from draft | Modal → Accept | `POST /api/analytics/sessions/from-draft` |
| Bucket snapshots | Page load (background) | `GET /api/analytics/bucket/current` |
| Plug blocks batch | Filter UI | `POST /api/analytics/plug-blocks/batch` |

---

## See also

* [BEARINGS_ANALYTICS_v1.md](../../BEARINGS_ANALYTICS_v1.md) —
  full spec at the repo root.
* [routing.md](routing.md) — adjust routing rules to throttle
  high-burn tags.
* [vault-and-memories.md](vault-and-memories.md) — promotion
  target for repeated plugs.
* [inspector.md §Usage tab](inspector.md#usage-tab) — same data,
  per-session entry point.
* [../api.md §analytics](../api.md#analytics).
* `src/bearings/web/routes/analytics.py`,
  `src/bearings/db/audits.py` (turns + bucket_snapshots tables).
* `frontend/src/lib/components/analytics/`.
