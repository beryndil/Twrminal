# Inspector

The right column of the app shell hosts the **Inspector** — a
tabbed surface that exposes the active session's metadata in long
form. It is the canonical "what is this session doing right now?"
read-out.

This guide describes what each tab shows and when to open it. For
the full observable behavior see
[../behavior/chat.md §Inspector pane](../behavior/chat.md#inspector-pane-non-routing-subsections)
and [../behavior/routing.md §Inspector Routing tab](../behavior/routing.md#inspector-routing-tab).

> **Eight tabs are wired today**, in the order they render:
> **Agent**, **Context**, **Instructions**, **Files**, **Changes**,
> **Metrics**, **Routing**, **Usage**. (The README still references
> a five-tab layout from an earlier release; the implementation is
> ahead of that text.)

## What you can do here

* [Open the inspector](#opening-the-inspector)
* [Read the executor configuration (Agent)](#agent-tab)
* [Read the context-window state (Context)](#context-tab)
* [Read or edit per-session instructions (Instructions)](#instructions-tab)
* [Audit which files the agent touched (Files)](#files-tab)
* [Audit the WRITE-side changes the agent made (Changes)](#changes-tab)
* [Read per-session token + tool-call counters (Metrics)](#metrics-tab)
* [Read the routing decision chain (Routing)](#routing-tab)
* [Read app-wide token rollups (Usage)](#usage-tab)

---

## Walkthrough

### Opening the inspector

Click the chevron at the right edge of the conversation pane (or
press the keyboard shortcut documented in
[../behavior/keyboard-shortcuts.md](../behavior/keyboard-shortcuts.md)).

Active-tab choice is **sticky across page reloads** —
`localStorage` key `bearings-v1:inspector-tab`. If `localStorage`
is unavailable (private browsing, quota exceeded), the in-memory
selection still flips for the page life; the persistence is best-
effort.

**State survives tab switches** — every tab subtree stays mounted
(inactive ones hidden via the HTML `hidden` attribute). Switching
tabs preserves scroll positions, expanded "Why this model?" panels,
already-loaded fetch data, etc.

The pane is empty when no session is selected.

### Agent tab

The executor configuration in long form (vs the conversation
header's compact row). A label/value grid shows:

| Field | Value |
|---|---|
| Executor model | Mapped to user-facing label (`Sonnet 4.6`, `Haiku 4.5`, `Opus 4.7`) using the same string table the new-session dialog uses. Unknown wire names render as themselves. |
| Permission mode | `Default` / `Accept edits` / `Plan` / `Bypass permissions`, or `(default)` when unset. |
| Working directory | Absolute path, monospace, wraps on long paths. |
| Budget cap (USD) | `max_budget_usd` formatted to two decimals, or `no cap` when unset. |
| Total cost (USD) | `total_cost_usd` formatted to two decimals. |
| Messages | Running message count. |

Routing-spec fields (advisor, effort, fallback model, beta
headers) live in the **Routing** tab below — their UI copy is
governed by the routing spec.

### Context tab

Mirrors the context-window / cost data the header band carries,
plus the title and description that the sidebar truncates. The
user sees:

* **Title** — full session title (no truncation).
* **Description** — the session "plug" body, rendered with
  preserved line breaks; `(no description)` when empty.
* **Last context-window pressure** — the most-recent turn's
  context-pressure as a whole-percent integer; `no turn observed
  yet` when the session has not completed a turn.
* **Last context tokens** — the most-recent turn's context-token
  count, locale-formatted with thousands separators.
* **Context-window max** — the model's context-window cap for the
  most-recent turn.

Below the grid is an **Assembled context** section. Today it
renders a placeholder paragraph noting that the system prompt,
tag-default overlays, and vault attachments will surface here once
the assembled-context API lands. The structure is in place so the
visual layout is stable when those fields are wired through.

### Instructions tab

Exposes the per-session free-text instructions
(`session_instructions` on `SessionOut`).

* Non-empty (post-trim) → renders inside a monospace pre-block
  with whitespace-preserving wrap.
* Empty / null / whitespace-only → empty-state copy: `No per-
  session instructions set.` (Whitespace-only is treated as empty
  so a stray newline does not masquerade as content.)

Header carries an **Edit…** button that opens the **SessionEdit
modal** with the instructions textarea focused. The modal is the
canonical editor surface for all four session-level fields (Title,
Description, Budget, Instructions). The Inspector body remains a
read-only view; all edits go through the modal.

The Instructions tab also renders the **full assembled system
prompt** — base prompt + per-tag `CLAUDE.md` layers + tag memories
+ directory brief + history prefix — fetched via
`GET /api/sessions/{id}/system_prompt`. Layer kind is distinguished:

| Source kind | Where it comes from |
|---|---|
| `tag_claude_md` | Per-tag `CLAUDE.md` filesystem content (working-directory walk-up). |
| `tag_memory` | DB-resident memory rows (the `tag_memories` table). `source_path` is `null` for these. |

Both kinds are visible in the breakdown so you can tell which
overlay is actually layered into the next turn.

### Files tab

Aggregated view of every file path the agent has touched in the
active session. Header strip shows **Files Touched** with a count
badge.

**Data source:** `conversationStore.turns` — the in-memory turn
list maintained by the conversation store reducer. No network call
is made; the list updates reactively as new tool events arrive on
the WebSocket.

**Path-key precedence** (applied to each `ToolCallView.inputJson`):

1. `file_path` — `Read`, `Write`, `Edit`.
2. `notebook_path` — `NotebookEdit`.
3. `path` — `Grep`.

`Bash` and `Glob` calls are skipped — they do not address a
specific file path in a way that's meaningful for the touch log.

**Each row shows:**

* Home-shortened path in monospace (`/home/<user>/…` → `~/…` for
  column fit; full path preserved in the tooltip).
* Last-action verb (`Read` / `Write` / `Edit` / `NotebookEdit` /
  `Grep`).
* Touch count `× N` when the path was touched > 1 time.
* Last-touch time formatted by `formatAbsolute` (respects the
  user's display-timezone preference).

Sort: most-recent touch first.

Empty state: *"No files touched yet — A row appears each time the
agent reads, writes, edits, or greps a specific file path."*

### Changes tab

Chronological list of every WRITE-side tool call in the active
session. Header strip shows **Changes** with a count badge.

**Verb mapping** — only three tools produce rows:

| Tool name | Verb badge | Badge colour |
|---|---|---|
| `Write` | Created | Emerald |
| `Edit` | Edited | Amber |
| `NotebookEdit` | Notebook-edited | Indigo |

Path extraction:

* `Write` / `Edit` → `file_path` from `inputJson`.
* `NotebookEdit` → `notebook_path` from `inputJson`.

Excerpt extraction (shown beneath the path row):

* `Write` → `content`.
* `Edit` → `new_string`.
* `NotebookEdit` → `new_source`.

Processed: split on `\n`, take line 0, trim leading whitespace,
clip to 120 characters. Empty excerpt suppresses the excerpt row.

Unlike Files (which deduplicates by path), Changes records **one
row per individual tool call**. Sort: most-recent first.

Empty state: *"No changes yet — A row appears each time the agent
writes a new file, edits an existing file, or modifies a notebook
cell."*

### Metrics tab

Per-session token totals + tool-call counters. Two cards.

**Card 1 — Token totals.** 2×2 grid:

| Cell | Source |
|---|---|
| Input | `conversationStore.sessionInputTokens` — accumulated from `message_complete` frames; reset on session-switch |
| Output | `conversationStore.sessionOutputTokens` |
| Cache read | `conversationStore.sessionCacheReadTokens` (rendered emerald) |
| Cache write | Not yet available — the v18 backend does not emit `cache_creation_tokens`; renders `—` until wired |

All values use short-notation: `< 1 000` → integer, `≥ 1 000` → `N.Nk`,
`≥ 1 000 000` → `N.NM`.

**Card 2 — Tool calls.** 2×2 grid, all derived from
`conversationStore.turns`:

| Cell | Value | Accent |
|---|---|---|
| Total | All `ToolCallView` entries across all turns | default |
| Running | `done === false` count | amber when > 0 |
| Failed | `done && !ok` count | rose when > 0 |
| Total elapsed | Sum of `durationMs` for finished calls | default; `—` when no finished calls |

Elapsed formatter: `< 1 000 ms` → `Nms`; `< 60 000 ms` → `N.Ns`;
`≥ 60 000 ms` → `Nm Ns`.

**Footer link**: *"View cross-session rollups →"* navigates to
`/analytics` so you can pivot from per-session to app-wide.

> **Caveat — counter zeroing on stale sessions.** The Metrics
> tab's per-session totals derive *exclusively* from
> `message_complete` frames received in the current page-life. On
> session-open, `resetConversation()` zeroes the counters; they
> grow as the WS ring-buffer replay delivers historical events.
> Sessions whose runner has been reaped or whose events are older
> than the 5 000-event ring-buffer cap **stay at zero** — even
> though the complete token history is durably stored in the
> `messages` table. The Analytics page reads from the DB and shows
> the true totals.

### Routing tab

Surfaces the routing-decision chain. Per
[../behavior/routing.md](../behavior/routing.md) and the
[routing spec §6](../model-routing-v1-spec.md):

* **Current models + source + reason** — executor model, advisor
  model (with `max_uses` budget), source (`tag_rule` /
  `system_rule` / `default` / `manual_override` /
  `manual_override_quota`), reason string, matched rule label
  when the source is a rule.
* **Per-message badge timeline** — every assistant message in the
  session listed with its routing badge (`Sonnet`, `Sonnet → Opus×2`,
  `Haiku → Opus×1`, `Opus xhigh`), the source, the matched rule.
  Hover any badge for the full reason. Click a row to scroll the
  conversation pane to that message.
* **Advisor totals (this session)** — calls used vs `max_uses`,
  per-advisor token totals.
* **Quota delta this session** — how much overall + per-model
  quota the session has consumed.
* **"Why this model?" expandable evaluation chain** — for the
  most-recent turn (or any selected turn), shows the per-tag rule
  walk in priority order, the system-rule fallback walk, the
  default-model line, the quota guard's pre/post state, and the
  override decision (if any). This is the primary debugging
  surface when a routing decision surprises you.

The routing tab also exposes the **mid-session executor swap**
control. Changing the executor here calls
`PATCH /api/sessions/{id}/model` which invokes
`runner.set_model()` so the next turn uses the new executor without
restarting the runner.

For routing rule management see the [routing guide](routing.md).

### Usage tab

App-wide token rollups (cross-session). Per the
[routing spec §10](../model-routing-v1-spec.md):

* **7-day headroom chart** — daily quota burn vs cap, per model.
  Yellow band at 80%, red band at 95%. The header chevron jumps to
  the [analytics page](analytics.md) for windows beyond 7 days.
* **By-model table** — last 7 days totals by executor model:
  input / output / cache-read tokens, USD, message count.
* **Advisor-effectiveness widget** — proportion of advisor-only
  outcomes (the executor turn was satisfied by the advisor's
  planning) vs full escalations (advisor planning was used but the
  executor still needed full work). Read this when tuning advisor
  `max_uses` per rule.
* **Rules-to-review list** — routing rules whose 14-day override
  rate has crossed `OVERRIDE_RATE_REVIEW_THRESHOLD` (default 30%).
  The user is overriding the rule's prediction often enough to
  suggest the rule is wrong. Click a rule to jump to its editor.

The Usage tab is a per-session entry point into the same data the
[analytics guide](analytics.md) walks in detail.

---

## Reference

### Tab summary

| # | Tab | Read when … | Source |
|---|---|---|---|
| 1 | Agent | You need to verify executor / permission-mode / working-dir / budget without scrolling the header. | `SessionOut` envelope. |
| 2 | Context | You want context-window pressure / token count / max for the most-recent turn. | `SessionOut` `last_context_*` fields. |
| 3 | Instructions | You need to read or edit per-session instructions, or audit the assembled system prompt. | `session_instructions` field; `GET /api/sessions/{id}/system_prompt` for the assembled view. |
| 4 | Files | You want to see every distinct file path the agent has touched. | In-memory `conversationStore.turns`. |
| 5 | Changes | You want a chronological log of WRITE-side tool calls. | In-memory `conversationStore.turns`. |
| 6 | Metrics | You want per-session token totals and tool-call counters. | In-memory accumulators (zeroed on session-open). |
| 7 | Routing | You're debugging a routing decision or want the per-message badge timeline. | `messages` routing columns + spec §6 endpoints. |
| 8 | Usage | You want app-wide rollups (7-day headroom, by-model, advisor effectiveness, rules to review). | Spec §10 endpoints. |

### Action surface

| Action | Trigger | Endpoint |
|---|---|---|
| Open SessionEdit modal | Instructions tab → **Edit…** | `PATCH /api/sessions/{id}` (on Save) |
| Mid-session executor swap | Routing tab → executor dropdown | `PATCH /api/sessions/{id}/model` |
| Jump to analytics | Metrics tab footer / Usage tab header | (UI nav) |
| Jump to a routing rule editor | Usage tab → **Rules to review** row click | (UI nav to `/tags/{id}` or `/settings/routing`) |
| Persist active tab | (automatic) | `localStorage["bearings-v1:inspector-tab"]` |

### Empty states

| Tab | Empty state |
|---|---|
| (any) | When no session selected — pane is blank. |
| Context | `no turn observed yet` for last_context_* fields. |
| Instructions | `No per-session instructions set.` |
| Files | `No files touched yet — …` |
| Changes | `No changes yet — …` |
| Metrics | Cache write renders `—` until backend wires `cache_creation_tokens`; Total elapsed renders `—` until at least one finished tool call. |

---

## See also

* [../concepts.md §6.3](../concepts.md#63-the-full-system-prompt-stack)
  — the system-prompt layer model that the Instructions tab renders.
* [../behavior/chat.md §Inspector pane](../behavior/chat.md#inspector-pane-non-routing-subsections)
  — full observable behavior for tabs 1-6.
* [../behavior/routing.md §Inspector Routing tab](../behavior/routing.md#inspector-routing-tab)
  — full observable behavior for the Routing tab.
* [../model-routing-v1-spec.md](../model-routing-v1-spec.md) §6, §10 —
  spec for the Routing and Usage tabs.
* [routing.md](routing.md) — manage routing rules.
* [analytics.md](analytics.md) — cross-session rollups.
* `frontend/src/lib/components/inspector/` — implementation
  (`InspectorAgent.svelte`, `InspectorContext.svelte`,
  `InspectorInstructions.svelte`, `InspectorFiles.svelte`,
  `InspectorChanges.svelte`, `InspectorMetrics.svelte`,
  `InspectorRouting.svelte`, `InspectorUsage.svelte`).
