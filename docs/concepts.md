# Concepts

This page is the connected mental model of Bearings. It exists so a
new reader can answer *what is this and how do its pieces fit
together* in one sitting, before diving into the reference layer.

The reference layer that this page links into:

| Concern | Where |
|---|---|
| Architectural decomposition (packages, classes, interfaces) | [architecture-v1.md](architecture-v1.md) |
| Per-subsystem observable behavior | [behavior/](behavior/) |
| Routing v1 specification | [model-routing-v1-spec.md](model-routing-v1-spec.md) |
| Task-oriented user guides | [guide/](guide/) |
| Curated HTTP/WS API reference | [api.md](api.md) |
| Authoritative wire shapes | [openapi.json](openapi.json) |

If you want the executable answer to "how do I do X?", go to
[guide/](guide/). This page answers "what is X, why does it exist,
and what does it touch?"

---

## 1. What Bearings is

Bearings is a localhost web UI that streams Claude Code agent
sessions. Each running agent appears as a row in the sidebar; the
conversation, tool calls, and system-prompt assembly are persisted
to SQLite turn-by-turn; a typed HTTP/WebSocket API exposes every
surface the UI consumes.

Three things distinguish Bearings from a transcript-only viewer:

* **It runs the agent.** The
  [`bearings.agent`](architecture-v1.md#114-bearingsagent--domain-layer)
  package owns a per-session Claude Agent SDK loop, prompt
  assembly, event translation, runner fleet, autonomous checklist
  driver, routing evaluation, quota guard, and an in-process MCP
  server. The UI is a window onto a live process, not a log
  reader.
* **It persists every routing decision.** Every assistant turn
  records the executor model, advisor model (if any), source
  (tag-rule / system-rule / default), reason, matched rule, token
  usage, and quota state at decision time. The Inspector renders
  this per-message; the Analytics page rolls it up across windows.
  See [routing](#4-routing-v1-in-one-page) below.
* **It treats tags as first-class infrastructure.** Tags don't just
  group sidebar rows — they select routing rules, layer
  system-prompt overlays, govern auto-driver inheritance, and
  enforce cardinality. See [tags](#3-how-tags-drive-everything).

Bearings binds to `127.0.0.1:8788` by default, persists state under
`~/.local/share/bearings-v1/`, and runs as a systemd unit
(`bearings-v1.service`) or directly via `bearings serve`. It is
designed for a single user on a single machine; auth is configurable
but optional for the localhost case.

---

## 2. The session model

A session is the central object. Everything else — messages, tool
calls, checkpoints, checklists, memories, paired chats, routing
decisions, usage rows — hangs off a session.

### 2.1 What a session row carries

A row in the `sessions` table carries:

* **identity** — a UUID `id`, a `title`, an optional `description`
  ("the plug"), an optional `closing_summary`;
* **execution shape** — `model`, `working_dir`, `permission_mode`,
  `max_budget_usd`;
* **routing columns** — `routing_executor_model`,
  `routing_advisor_model`, `routing_advisor_max_uses`,
  `routing_effort_level`, `routing_source`, `routing_reason`;
* **lifecycle timestamps** — `created_at`, `updated_at`,
  `last_completed_at`, `last_viewed_at`, `closed_at`;
* **kind** — see below;
* **back-pointers** — `checklist_item_id`, `parent_session_id`,
  `pivot_message_id` for paired chats and spawn-from-reply.

`message_count` and the per-window token rollups are denormalised on
the row so the sidebar doesn't pay an aggregation per render.

### 2.2 Session kinds

A session's `kind` is one of two values, set at create time and
never changed:

| Kind | What it is |
|---|---|
| `chat` | A conversation: one composer, an executor (and optional advisor) Claude turn-by-turn, tool-use approvals via the conversation pane. The default. |
| `checklist` | A structured-list pane (no composer) with items, drag-reorder, an Auto-driver run-control widget, and per-item paired chats. See §5 below. |

A `chat`-kind session can additionally be a **paired chat** — a
regular chat whose `checklist_item_id` points back at a checklist
leaf. A `chat`-kind session can also be a **spawn-from-reply** —
its `pivot_message_id` and `parent_session_id` point at the
conversation it was forked from. Both are observable in the chat's
header (a breadcrumb chip) but the underlying row is still
`kind='chat'`.

### 2.3 Lifecycle states

A session is **open** until `closed_at` is set; closed sessions move
to a collapsed sidebar group, refuse new prompts (the prompt
endpoint returns `409`), but remain readable, exportable, and
re-openable. Closing is reversible. Deleting is not.

Checklists cannot be closed via the close endpoint
(`POST /api/sessions/{id}/close` returns `422` for
`kind='checklist'`). A checklist auto-closes only when every root
item is checked. See [behavior/checklists.md](behavior/checklists.md)
for the cascade rules.

### 2.4 Persisted vs. ephemeral

| Persisted | Ephemeral |
|---|---|
| Messages (user / assistant / tool / system) | The runner's `is_running` / `is_awaiting_user` state |
| Tool-call rows (one-to-many on the message) | Live token streams (re-derived on reload) |
| SDK transcript entries (raw blobs) | Composer drafts (held in the frontend store) |
| Routing decisions + per-message usage | The "did the user view this row" pip — derived from `last_completed_at` vs `last_viewed_at` |
| Checkpoints (snapshot/restore points) | The current Auto-driver leg in flight |
| Tag attachments | Search-result counts |

A page reload drops everything in the right column; the next
WebSocket tick restores enough of it (runner state, sessions
broadcast) that the user does not notice.

For full session-lifecycle behavior — create, rename, close, fork,
merge, duplicate, export, import — see
[behavior/sessions.md](behavior/sessions.md) and the matching
[guide/sessions.md](guide/sessions.md).

---

## 3. How tags drive everything

A tag in Bearings is **not** a free-form label — it is one of three
**classes** with strict cardinality rules per session:

| Class | Cardinality per session | What it does |
|---|---|---|
| `project` | at most 1 | Drives sidebar grouping; carries inherited `default_model` and `working_dir` for new sessions; selects per-tag routing rules and tag memories. |
| `severity` | at most 1 | Drives the conversation header's severity shield colour. Severity tags carry no `default_model` / `working_dir`. |
| `general` | unbounded | Free-form labels. Same routing-rule and memory-overlay surface as `project` tags but with no inheritance. |

Cardinality is enforced at session create AND at session PATCH (any
attempt to attach a second project or severity tag returns `422`).
This invariant means that downstream consumers — the routing
evaluator, the system-prompt assembler, the sidebar grouper — can
read each class's slot directly without iterating.

Tag-driven surfaces:

* **Routing.** Per-tag routing rules attach to a tag id. When the
  user creates a session with that tag, the rule fires (per the
  priority ladder in §4). Multiple matching tags resolve through
  the spec's tie-breaking rules.
* **System-prompt overlays.** Each tag can carry zero or more
  *memories* — short markdown blocks resolved into the system
  prompt on every turn. See §6.
* **Sidebar.** The sidebar groups by project tag; severity tags
  paint the row's left edge; general tags appear as chips on hover.
* **Inheritance.** When a paired chat spawns from a checklist leaf,
  the new chat inherits the checklist's project + general tags.
  Severity tags do not inherit (they are session-state-specific).

The full tag model — colours, default-model overlays, slash-namespace
back-compat (`<group>/<name>`), the per-class sort order — is
covered in [behavior/sessions.md](behavior/sessions.md) §"Tag" and
[architecture-v1.md §1.1.3](architecture-v1.md#113-bearingsdb--schema--per-concern-queries).

---

## 4. Routing v1 in one page

Routing v1 is the system that picks the **executor model** (and
optionally an **advisor model**) for each turn. It is deterministic,
fully visible per-message in the Inspector, and aggregated across
windows in the Analytics page.

### 4.1 Inputs

For each turn, the evaluator receives:

* the user message body and any attachments;
* the session's tags (with their attached routing rules);
* the system-routing rules (a per-instance fallback ladder);
* the current quota snapshot (overall + per-model headroom).

### 4.2 Priority ladder

The evaluator walks rules in this fixed order, first match wins:

1. **Per-tag rules** — every rule on every attached tag, ordered by
   the tag's `sort_order` then the rule's intra-tag order. The
   first rule whose match expression matches the message wins.
2. **System rules** — the per-instance fallback ladder. Same first-match
   semantics.
3. **Default** — the runtime default model (per
   `config/constants.py` `DEFAULT_EXECUTOR_MODEL`).

### 4.3 Advisor consultation

A matched rule can specify an **advisor model** — a second model
that runs first to produce a planning turn that's prepended to the
executor's context. Advisor calls are capped per-session by
`max_uses` (default 5). The advisor's token usage is recorded
separately on the message row so the Analytics "advisor
effectiveness" widget can compare advisor-only outcomes vs full
escalations.

### 4.4 Quota guard

After the rule match, the **quota guard** (`apply_quota_guard()` in
[`bearings.agent.quota`](architecture-v1.md#114-bearingsagent--domain-layer))
checks the executor model's headroom. If the chosen model is
within `QUOTA_THRESHOLD_PCT` (default 80%) of its hard cap, the
guard downgrades the choice (typically Opus → Sonnet) and the UI
shows a yellow banner: `"Routing downgraded to Sonnet (overall
quota at NN%). [Use Opus anyway]"`. Clicking the override
restores the original choice and records the override for
analytics.

The `quota_state_at_decision` field on every assistant message
captures the snapshot the routing decision was made against. The
Inspector → Routing tab renders it.

### 4.5 Override aggregator

The override aggregator
([`bearings.agent.override_aggregator`](architecture-v1.md#114-bearingsagent--domain-layer))
maintains a rolling 14-day per-rule override rate. Rules whose rate
crosses `OVERRIDE_RATE_REVIEW_THRESHOLD` (default 30%) appear in the
Analytics "rules to review" list — the user is choosing the
overridden model often enough that the rule's prediction may be
wrong.

### 4.6 Where to look

| Need | Source |
|---|---|
| Numbers, dataclass shapes, endpoint payloads, UI strings | [model-routing-v1-spec.md](model-routing-v1-spec.md) |
| Observable UI behavior (badges, banners, preview line) | [behavior/routing.md](behavior/routing.md) |
| Walkthrough — creating tag rules, system rules, overriding | [guide/routing.md](guide/routing.md) |
| Code | `src/bearings/agent/routing.py`, `src/bearings/agent/quota.py`, `src/bearings/agent/override_aggregator.py` |
| HTTP routes | [api.md §routing](api.md#routing), [api.md §quota](api.md#quota), [api.md §usage](api.md#usage) |

---

## 5. Paired chats and checklists

A **checklist** is a structured-list session: items, optional
nesting, drag-reorder, run-control. It has no composer of its own —
work happens in **paired chats**.

### 5.1 The pair relationship

A pair is a 1:1 link between exactly one checklist *leaf* item and
exactly one chat session. The pair is observable from both sides:

* **Item side** — the leaf shows a clickable chat title and a
  *Continue working* affordance. An unpaired leaf shows the **💬
  Work on this** spawn button.
* **Chat side** — the conversation header carries a breadcrumb chip
  `<checklist title> › <item label>`. Clicking the parent segment
  selects the parent checklist; clicking the item segment scrolls
  the parent pane to the item.

Spawning is idempotent (a second click selects the existing pair).
The chat inherits the checklist's working directory, model, and
project + general tags. Detaching is unconditional — the pair
pointer is cleared on both sides; the chat keeps its history.

### 5.2 Cascading state

Checking a paired leaf closes its paired chat. A non-leaf parent
auto-fills its derived checkbox when every child is complete. The
checklist session itself auto-closes when every root item is
complete. Auto-close is **one-directional**: unchecking does not
re-open.

### 5.3 The autonomous driver

The checklist header carries a small **Auto-driver** widget
(Start / Stop / Skip / failure-policy / visit-existing toggles).
When started, the driver:

1. picks the first unchecked item in sort order;
2. spawns (or reuses, if visit-existing is on) a paired chat for
   that item;
3. consumes the **sentinels** the agent emits in its assistant text
   — `done`, `handoff`, `followup` (blocking + non-blocking),
   `blocked`, `failed` — and reacts:
   * `done` → check item, advance;
   * `handoff` → kill current leg, spawn successor leg with the
     plug as first prompt;
   * blocking `followup` → recurse into the new child;
   * `blocked` / `failed` → honour the failure policy (`halt` or
     `skip`);
4. ticks the live counters (`items_completed`, `items_failed`,
   `legs_spawned`, …) on the status line.

The driver carries safety caps: max legs per item (5), max items
per run (50), max blocking-followup depth (3). It also runs a
**pressure watchdog**: when the agent's last turn produced no
handoff and the reported context-window pressure crossed 60%, the
driver injects one nudge ("please emit a handoff plug now") before
treating a quiet turn as a silent-exit failure.

### 5.4 Spawn from reply

Outside of checklists, every completed assistant message in a
non-paired chat exposes a **＋ SPAWN** action pill. Clicking it
forks a new chat whose first user message is the clicked assistant
body as a Markdown blockquote, with `parent_session_id` and
`pivot_message_id` set so the back-link can render. The spawn is
idempotent on the same `(parent, pivot)` pair while the spawned
chat is open.

For full behavior — sentinel formats, driver state machine,
breadcrumb anatomy — see
[behavior/checklists.md](behavior/checklists.md),
[behavior/paired-chats.md](behavior/paired-chats.md), and the
walkthrough in [guide/checklists.md](guide/checklists.md) /
[guide/paired-chats.md](guide/paired-chats.md).

---

## 6. Vault, memories, and the system prompt

Three layers contribute markdown content to the system prompt the
agent sees on every turn. They are independent — you can use any of
them alone — but understanding their interaction matters when the
agent's behavior surprises you.

### 6.1 The vault — read-only plans + TODOs

The **vault** is a read-only browser over the user's planning
markdown:

* every `.md` file directly under each configured plan root (e.g.
  `~/.claude/plans/`);
* every `TODO.md` matched by the configured globs (e.g.
  `~/Projects/**/TODO.md`).

The vault renders these files; it does not edit them. The on-disk
files are the source of truth (the user's editor, git, agent
sessions write to them). The vault provides search, drag-into-
composer, and right-click "copy as markdown link" / "copy doc body"
actions. Secret-shaped tokens are masked behind a "Show" toggle at
render time only — clipboard paths still receive the literal text.

The vault is **not** a system-prompt source — it does not feed the
agent. It exists so the user does not have to terminal-hop to read
their plans.

### 6.2 Memories — tag-keyed system-prompt overlays

A **memory** is a markdown block stored in the database, attached
to a tag. On every turn:

1. The system-prompt assembler walks the session's attached tags in
   precedence order (lowest precedence tag first, highest last).
2. For each tag, it appends every **enabled** memory's body to
   `extra_system_prompt_parts`.
3. Memories land **after** the per-tag `CLAUDE.md` filesystem
   layers, so memory directives win on conflicts.

Editing a memory and sending the next prompt reflects the change
without restarting the runner. Disabled memories are excluded;
deleted memories are absent on the next turn.

Memories are managed at `/memories` — the route renders a flat
global index (filterable by tag chip) and a per-tag editor. The
**Inspector → Instructions tab** distinguishes the two source
kinds: `tag_claude_md` (filesystem) vs `tag_memory` (DB-resident).

### 6.3 The full system-prompt stack

Each turn's system prompt is layered (lowest → highest precedence):

1. **Base prompt** — the static Bearings agent prompt
   (`agent/base_prompt.py`).
2. **Per-tag `CLAUDE.md` layers** — read from the working directory
   walk-up.
3. **Tag memories** — DB-resident, ordered by tag precedence.
4. **Directory-context brief** — `.bearings/` onboarding brief, if
   the working directory has one.
5. **History prefix** — recent transcript condensed for context
   (capped at `HISTORY_PRIME_MAX_CHARS`).
6. **Routing decision context** — beta headers, `fallback_model`,
   advisor wiring.

For the assembler implementation see
[`bearings.agent.prompt`](architecture-v1.md#114-bearingsagent--domain-layer);
for the `.bearings/` directory contract see
[`bearings.bearings_dir`](architecture-v1.md#117-bearingsbearings_dir--directory-context-contract).

---

## 7. Glossary

Terms with load-bearing meaning in the UI or the API. Each entry
links to its canonical reference.

* **advisor** — a second Claude model that runs first to produce a
  planning turn prepended to the executor's context. Capped per-
  session by `max_uses`. See [§4.3](#43-advisor-consultation).
* **app shell** — the persistent SvelteKit layout: sidebar +
  conversation/list pane + (optional) inspector drawer.
* **`.bearings/`** — per-directory context contract (manifest +
  state + pending). See
  [behavior/bearings-cli.md](behavior/bearings-cli.md) for `bearings
  here` / `bearings pending` and
  [`bearings_dir`](architecture-v1.md#117-bearingsbearings_dir--directory-context-contract)
  for the on-disk schema.
* **breadcrumb (paired chat)** — the `parent › item` chip in a
  paired chat's header.
* **checkpoint** — Bearings' own snapshot/restore point on a
  message, distinct from the SDK's `enable_file_checkpointing`. See
  [api.md §checkpoints](api.md#checkpoints).
* **checklist** — a structured-list session (`kind='checklist'`).
  See [§5](#5-paired-chats-and-checklists).
* **closed** — a session with `closed_at` set. Cannot accept new
  prompts (returns `409`); remains readable, exportable, and
  re-openable.
* **director / driver** — the autonomous checklist driver. See
  [§5.3](#53-the-autonomous-driver).
* **executor (model)** — the Claude model that runs the assistant
  turn (after the advisor, if any).
* **fork** — create a new session sharing the parent's history up
  to a chosen message. The parent retains its full history.
* **handoff (sentinel)** — the autonomous-driver sentinel that
  triggers a successor leg with the agent's plug as first prompt.
* **inspector** — the right-side drawer with eight tabs (Agent,
  Context, Instructions, Files, Changes, Metrics, Routing, Usage).
  See [guide/inspector.md](guide/inspector.md). (The README still
  references a five-tab layout from an earlier release; the
  implementation is ahead of that text.)
* **kind** — the immutable session-type discriminator: `chat` or
  `checklist`.
* **leaf** — a checklist item with no children. Only leaves can
  be paired with a chat.
* **leg** — one autonomous-driver iteration on an item. A `handoff`
  ends one leg and spawns the next.
* **memory** — a tag-keyed system-prompt overlay block. See
  [§6.2](#62-memories--tag-keyed-system-prompt-overlays).
* **paired chat** — a `kind='chat'` session whose
  `checklist_item_id` points at a checklist leaf. See
  [§5.1](#51-the-pair-relationship).
* **plug** — a session's `description` field. The shorthand comes
  from the Beryndil session-handoff protocol where the description
  carries the successor's first prompt context.
* **pin / pinned** — a sticky bit on a session row that keeps it
  pinned to the top of its sidebar group.
* **pressure (context)** — the agent's reported context-window
  fill. Triggers context-pressure handoff hints (per
  `~/.claude/rules/executor-handoff-on-pressure.md`) and the
  driver's pressure-watchdog nudge at 60%.
* **routing badge** — the per-message corner label (`Sonnet`,
  `Sonnet → Opus×2`, `Haiku → Opus×1`, `Opus xhigh`). Hover reveals
  the matched rule + reason.
* **routing decision** — the `(executor, advisor, source, reason,
  matched_rule, quota_state_at_decision)` tuple persisted on every
  assistant turn.
* **routing source** — one of `tag_rule` / `system_rule` /
  `default` / `manual_override` / `manual_override_quota`. See
  [behavior/routing.md](behavior/routing.md).
* **runner** — the per-session worker holding the SDK loop, prompt
  queue, ring buffer, subscriber set, and idle-reap signal. See
  [`bearings.agent.runner`](architecture-v1.md#114-bearingsagent--domain-layer).
* **sentinel** — a structured marker the agent emits inside its
  assistant text (`done`, `handoff`, `followup`, `blocked`,
  `failed`) that the autonomous driver consumes. See
  [§5.3](#53-the-autonomous-driver) and
  [behavior/checklists.md](behavior/checklists.md) §"Sentinels".
* **session** — a row in the `sessions` table. See [§2](#2-the-session-model).
* **spawn from reply** — the **＋ SPAWN** action on an assistant
  message that forks a new chat with the message body as a
  blockquote first prompt. See [§5.4](#54-spawn-from-reply).
* **tag class** — `project` / `severity` / `general`. See
  [§3](#3-how-tags-drive-everything).
* **viewed pip** — the green sidebar pip indicating the session has
  output the user has not yet opened
  (`last_completed_at > last_viewed_at`). See
  [behavior/sessions.md](behavior/sessions.md) §"Activity indicator".
