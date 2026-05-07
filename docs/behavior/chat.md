# Chat — observable behavior

A chat session is a tagged conversation between the user and one Claude executor (with an optional advisor). This document lists what the user sees and can do; it does not prescribe how any of it is implemented. Implementation choices are governed by `docs/architecture-v1.md`.

Sibling subsystems referenced here:
[paired-chats](paired-chats.md), [tool-output-streaming](tool-output-streaming.md), [prompt-endpoint](prompt-endpoint.md), [keyboard-shortcuts](keyboard-shortcuts.md), [context-menus](context-menus.md).

## When the user creates a chat

The user opens the new-session dialog (sidebar "+" button, the keyboard shortcut documented in [keyboard-shortcuts](keyboard-shortcuts.md), or by selecting a template). The dialog requires:

* any number of tags (zero or more), partitioned across the three tag classes — at most one *project*, at most one *severity*, any number of *general* labels. The project tag drives sidebar grouping and inheritance; the severity tag drives the header shield colour; general tags are free-form labels (see [vault](vault.md) for how tags surface elsewhere). Cardinality is enforced on session create: payloads with two project tags or two severity tags return 422.
* a working directory (free-text path or browse);
* a routing selection per spec §6 (executor model, optional advisor model with `max_uses`, effort level);
* a first message body.

The user sees a routing-preview line ("Routed from tag rule …") that updates ~300 ms after each keystroke in the first-message field, after each tag change, and after any manual routing override. Per spec §6 the line text changes to "Manual override" once the user touches the executor / advisor / effort controls. Quota bars (overall + Sonnet) are visible inside the dialog and turn yellow at 80 %, red at 95 %.

If the quota guard would downgrade the routed choice (per spec §4), a yellow banner appears above the Start button: "Routing downgraded to Sonnet (overall quota at NN%). [Use Opus anyway]". Clicking the override restores the original executor and records the override for analytics.

Pressing **Start Session** creates the row, attaches the tags, sends the first message, and opens the new chat in the conversation pane. The sidebar adds a row for the chat under each of its tags.

## When the user opens an existing chat

Clicking a sidebar row selects that chat. The conversation pane renders:

* a header band: title, severity shield, attached tag chips, paired-checklist breadcrumb (when the chat was spawned from a checklist item — see [paired-chats](paired-chats.md)), executor model dropdown, total-cost / context-window indicator, a quota bar pair, and a **feedback button** (megaphone glyph) — clicking the feedback button opens `https://github.com/Beryndil/Bearings/issues/new` in a new tab, pre-filled with the Bearings version (fetched lazily on first click and cached), browser UA, platform, language, and a steps-to-reproduce scaffold; Bearings does not POST any data — the user submits the GitHub form manually (gap-cycle-01-008, Beryndil standards §17);
* the conversation body: every message turn in chronological order, oldest at top;
* a composer: multi-line input, attachment chips, send button, slash-command popup.

Selecting the row also marks the session "viewed": the green activity pip on the sidebar row clears. Selecting the row fires `POST /api/sessions/{id}/viewed`, which stamps `last_viewed_at` server-side and emits a sessions-broadcast upsert so the pip also clears on any other open tab or window within the same WebSocket tick. Refocusing the browser tab while a session is already selected (tab visibility-change) fires the same POST. See [keyboard-shortcuts](keyboard-shortcuts.md) for `j` / `k` / `Alt+1..9` navigation between sidebar rows.

### Activity indicator

Each sidebar row has a single coloured pip indicator rendered to the left of the session title. The pip reflects the live agent state for that session, updated in real time via the `/ws/sessions` broadcast. Four states, resolved in priority order (first match wins):

| Priority | Colour | Animation | Condition |
|---|---|---|---|
| 1 | **Red** | Flashing ping | Agent is parked waiting for user input (tool-use approval or `AskUserQuestion`) **OR** `error_pending` is latched on the session |
| 2 | **Orange** | Flashing ping | Agent turn is actively running and not parked on a question |
| 3 | **Green** | Solid dot | Session has new assistant output the user has not yet opened (`last_completed_at > last_viewed_at`, or `last_viewed_at` is null). Suppressed on the currently-selected row. |
| 4 | — | (absent) | Session is idle and caught up — no pip is rendered |

The red and orange states are driven by `runner_state` WebSocket broadcast events (`is_awaiting_user` and `is_running` fields respectively). The green state is driven by the `last_completed_at` / `last_viewed_at` timestamps on the `SessionOut` row, which the sessions-broadcast upsert keeps current. Colour carries the full meaning — the pip dimensions and animation rhythm are identical across all active states.

The `is_running` and `is_awaiting_user` fields from `runner_state` events are maintained in the sessions store as `Set<string>` collections (`running` and `awaiting`). They are not persisted to the `SessionOut` row because they represent transient runner state; a page reload or server restart resets them to empty (the broadcast reconnects and re-emits state on the next runner event).

## What a message turn looks like

Each turn is one user message followed by zero or more tool calls and exactly one final assistant message. The user-visible anatomy:

* **User bubble** — body text rendered as Markdown, attachment chips at the bottom (`[File 1] foo.log`-style chips opened from [context-menus](context-menus.md) → attachment).
* **Tool-work drawer** (collapsible `<details>`) — one row per tool call. Each row shows tool name, an elapsed-time readout that ticks live while the call is running, and a chevron to expand inline output. Output streams in as it arrives (see [tool-output-streaming](tool-output-streaming.md)). Failed calls render in red. A "⤴ TOOLS" jump button appears on the assistant bubble when the drawer was collapsed during the streaming turn.
* **Assistant bubble** — Markdown body, optional thinking block (collapsible, dim), per-message routing badge (per spec §5) in the corner, "Ask for more detail" button hovering on the right edge.
* **Routing badge** (per spec §5) — short label such as `Sonnet`, `Sonnet → Opus×2`, `Haiku → Opus×1`, `Opus xhigh`. Hovering reveals the routing reason ("matched tag rule: bearings/architect — Hard architectural reasoning").
* **Per-message usage column** (per spec §5) — input / output / cache-read tokens for the executor and (when present) the advisor, surfaced in the inspector’s per-message timeline (see Inspector Routing — cross-referenced in §What the user does NOT see in chat).

## Tool-call hydration contract

*Added in gap-cycle-03-012.*

When a session is opened, the conversation pane fetches messages via `GET /api/sessions/{id}/messages`. For sessions where the ring-buffer events are no longer available (the runner was reaped, the server was restarted, or the session is older than the 5000-event ring-buffer cap), the tool-work drawer rows on completed assistant turns would be silently absent if the pane relied solely on WS replay.

To fill this gap, the pane calls `GET /api/sessions/{id}/tool_calls?message_ids=ID1&message_ids=ID2&…` immediately after `listMessages` returns, passing the assistant message ids from the current page. The response is a flat list of `ToolCallOut` rows grouped by the caller by `message_id`.

**Endpoint**:
* `GET /api/sessions/{id}/tool_calls` — 404 when the session is absent; 200 with `[]` when no tool calls exist.
* `?message_ids=ID` — repeated query param; omit to return all tool calls for the session (used by export / admin paths).
* Response shape: `ToolCallOut[]` — `id`, `message_id`, `tool_name`, `input_json`, `output`, `ok`, `duration_ms`, `error_message`, `created_at`.

**Persistence**: Tool calls are written to the `tool_calls` DB table at end-of-turn alongside the assistant message row. The `message_id` column references the Bearings message id (not the SDK's Anthropic API id) so the REST endpoint can be queried with the same ids `listMessages` returns.

**Idempotency**: The hydration path skips assistant turns whose `toolCalls` array is already populated (WS replay was faster). The `tool_call_start` WS event skips inserting a drawer row if the call id is already present. `tool_output_delta` skips delta accumulation if the call is already marked `done`. This means the DB hydration and WS replay paths compose safely without duplicating drawer rows.

## LiveTodos hydration contract

*Added in gap-cycle-03-013.*

The `LiveTodos` panel shows the agent's most-recent `TodoWrite` output as a sticky collapsible strip above the message turns. Because `TodoWrite` events are only broadcast via the ring-buffer WebSocket, a session whose runner has been reaped or whose events are older than the ring-buffer cap would show an empty panel until the user sends a new prompt — even though the last `TodoWrite` payload is durably stored in the `tool_calls` table.

To fill this gap, the conversation pane calls `GET /api/sessions/{id}/todos` once on session open, before establishing the WebSocket subscription. If the response is non-null, `liveTodos` is seeded immediately and the panel renders without delay.

**Endpoint**:
* `GET /api/sessions/{id}/todos` — 404 when the session is absent; 200 with `null` when the session has never emitted a `TodoWrite`; 200 with `{todos_json: string}` when a persisted `TodoWrite` exists.
* `todos_json` is the serialised `todos` array extracted from the raw `TodoWrite` input envelope `{"todos": [...]}` — identical in shape to the `todos_json` field on the `todo_write_update` WebSocket event.

**Seed vs live event ordering**: The hydration seed is applied before the WebSocket subscription connects. Once the WS is live, any `todo_write_update` event that arrives via replay or a new turn overwrites the seeded value via the same `JSON.parse` path — the hydration and live-event paths are fully composable. The panel's visible state at any moment reflects whichever source provided the most-recent update.

**Non-fatal errors**: If the hydration fetch fails (network error, 5xx), the panel stays hidden until the agent re-emits a `TodoWrite` call via the WebSocket. The error is not surfaced to the user — it is an optimistic prefetch, not a required load.

## Conversation rendering

The body uses Markdown (CommonMark + GFM) with syntax-highlighted code blocks. Inside any rendered message body the linkifier auto-detects:

* `https://…` and `http://…` URLs — rendered as anchors that open in a new tab with `noopener noreferrer`;
* `file://…` URLs — rendered as anchors the local "Open in editor" handler can dispatch on;
* absolute filesystem paths and (when the session has a working directory) paths shaped like `frontend/src/lib/x.svelte` — resolved against the session's working directory and rendered as `file://` anchors. Paths that can't be resolved against an absolute root are left as plain text rather than producing a broken anchor.

Long lines wrap; pre-formatted code blocks scroll horizontally inside their own container. The conversation auto-scrolls to the bottom on a new turn unless the user has scrolled up — see [tool-output-streaming](tool-output-streaming.md) for the scroll-anchor rules.

## Composer — attachment ingestion

*Added in gap-cycle-03-001.*

The composer accepts files via drag-and-drop onto the textarea. Pasting files via Ctrl+V is not wired in v1.0.

### Drop behaviour

When the user drops one or more files onto the composer:

1. Each file is uploaded immediately and independently via `POST /api/uploads` (multipart/form-data with a single `file` part per request). Multiple files trigger one request each, all fired concurrently — the backend exposes no `/api/uploads/batch` route in v18.
2. While a file upload is in-flight, a chip appears in the composer's attachment row (above the textarea) showing the filename and a spinner. The chip's status cycles: `uploading` → `done` (server id assigned) or `error` (inline warning shown on the chip).

### Upload error

If a single file upload fails (non-2xx from `/api/uploads`), the chip changes to the error style and shows a warning glyph with the server's `detail` message as a tooltip. The error chip does not block the Send button; the user can remove it and retry the drop. Other in-flight uploads from the same drop batch are not affected.

### Remove before send

Clicking the × button on a chip removes it immediately. If the upload is still in-flight, the `AbortController` signal fires and the request is cancelled; the byte stream is dropped. The chip disappears from the UI before the abort round-trip completes.

### Send gate

The Send button is disabled while any chip has `status === "uploading"`. Once all chips in the row reach `"done"` or `"error"` state, the gate lifts — the user may then send with the text draft.

### Prompt body — attachment id list

When the user submits, the ids of all `"done"` chips are collected and sent as `upload_ids: number[]` in the `POST /api/sessions/{id}/prompt` body alongside `content`. The backend's `PromptIn` model uses `extra="ignore"`, so the field is silently discarded server-side today. This is a **forward-compatible placeholder** — the field shape is intentionally pinned here so a future `PromptIn` revision can activate it without a client change. The design choice is: pass the ids eagerly; don't wait for the backend to formally declare the field.

On a successful prompt send, all attachment chips are cleared from the composer row.

### Chip lifecycle summary

| Chip state | Spinner | Error glyph | Remove button | Blocks Send |
|---|---|---|---|---|
| `uploading` | yes | no | yes (aborts) | **yes** |
| `done` | no | no | yes (no abort needed) | no |
| `error` | no | yes | yes (no abort) | no |

## Slash commands in the composer

Typing `/` at the start of the composer opens a filter popup of available commands. The user picks one with arrow keys + Enter, or by clicking. The two slash commands the user observes from the chat surface:

* `/advisor` (spec §7) — when typed as the first token of a message, forces the executor to consult the advisor on this turn regardless of the session's normal advisor wiring. The badge on that turn renders "→ Opus×1" (or higher) even on sessions where the advisor is normally disabled. This is per-turn only; the session config is unchanged.
* `/checkpoint` — inserts a labelled gutter mark in the conversation that the user can later fork from (see [context-menus](context-menus.md) → checkpoint actions).

Slash commands the SDK exposes (e.g. `/clear`, `/compact`) pass through to the underlying agent and are observable as their normal effects rather than a Bearings-specific UI.

## Sending a message

Pressing Enter (or Cmd/Ctrl+Enter, depending on the user's draft-newline preference) sends the composed text. The user observes:

1. The composer empties and a fresh user bubble appears at the bottom of the conversation.
2. A "thinking" pip appears next to the bubble while the executor formulates the first response.
3. As the agent streams its reply, the assistant bubble grows in place. Tool calls open as rows in the tool-work drawer above the assistant bubble. See [tool-output-streaming](tool-output-streaming.md).
4. On turn completion the assistant bubble's routing badge resolves to its final value, the cost/usage indicator in the header updates, and the context-window pressure meter ticks.

The composer remains usable during a turn (the user can type the next message), but pressing send while a turn is in flight queues the next prompt rather than interleaving it. See [prompt-endpoint](prompt-endpoint.md) for the same semantics over HTTP.

## Regenerate from here

Right-clicking any **assistant** turn in the conversation opens the context menu. When the turn is **not** the last assistant turn in the conversation, the menu includes the action **"Regenerate from this message…"**. When the turn is the last assistant turn, this action is suppressed — the top-level **"Regenerate (rewrite in place)"** action covers that case without truncating history.

Selecting "Regenerate from this message…" opens a small confirmation dialog:

```
Discard N messages and regenerate from here?
                               [Cancel]  [Regenerate]
```

`N` is the total number of messages that will be removed: the clicked assistant turn plus any turns that follow it (subsequent user/assistant exchanges).

Clicking **Regenerate**:

1. Fires `POST /api/sessions/{id}/regenerate_from/{message_id}`, where `message_id` is the id of the clicked assistant turn.
2. The server finds the user message immediately preceding the clicked assistant turn (the "pivot"), deletes all messages after the pivot (including the clicked assistant turn and any subsequent turns), and re-dispatches the pivot user message content to the runner.
3. The conversation pane reflects the truncation on the next WebSocket update; a new assistant turn begins streaming from the pivot.

Clicking **Cancel** dismisses the dialog with no changes.

The endpoint returns `202 Accepted` on success. It returns `404` if the session or message is not found, `409` if the session is closed, `422` if the named message is not an assistant turn, or `429` if the rate limit is exceeded.

## Stopping or interrupting a turn

A **Stop** control appears in the composer area whenever a turn is in flight. Pressing it interrupts the agent at the next safe boundary; the partially-streamed assistant bubble is preserved with a `[stopped]` annotation. The user can immediately type a new message — the session is ready for the next turn.

A small "undo stop" inline appears for a few seconds after stopping, letting the user re-issue the same prompt without retyping it.

## Manual mid-session model switch

The conversation header has an executor dropdown showing the current model. Picking a different model opens a confirmation per spec §7:

```
Switch executor: Sonnet → Opus
This will re-cost ~38,000 input tokens of conversation history at Opus rates.
Estimated impact on overall bucket: +1.4%

[Cancel]   [Switch]
```

Confirming changes the executor for all subsequent turns in this session; turns already streamed keep whatever model produced them. Their badges (per spec §5) preserve the model that ran them. The "estimated" word is part of the dialog text on purpose: the cost preview is approximate.

## Approval modal

When the agent invokes a tool that requires user approval, a centred modal opens over the conversation pane. Two flavours render:

* **Generic tool approval** — for any tool gated by the SDK's permission callback. The modal shows the tool name, a JSON view of the tool input, and **Allow** / **Deny** buttons. Allow submits `{approved: true}`; Deny submits `{approved: false}`.

* **Agent question** — when the agent invokes the built-in `AskUserQuestion` tool. The modal title reads "Agent is asking:" and the body adapts to one of three shapes the tool input can take:

    * *Structured* `{questions: [...]}` — one block per question, each with a header (small caps), the question prompt, a "Pick one" / "Pick one or more" hint, a list of selectable options, and an **Other** free-text input below the option list. Single-select questions render as radios; `multiSelect: true` renders checkboxes. The Submit button stays disabled until every question has at least one selection **or** a non-empty Other text. On submit, picks are encoded as one labelled line per question (e.g. `Schema: First-class column`) joined by newlines and posted as the `answer` text. When Other is non-empty: for single-select it replaces the radio pick; for multi-select it is appended after the selected labels (e.g. `Tags: alpha, beta, my custom tag`).

    * *Legacy free-text* `{question: "..."}` — a textarea with placeholder "Type your answer…" and a Submit button. Enter (without shift) submits; Shift+Enter inserts a newline.

    * *Unrecognised input* — neither shape matches. The modal pretty-prints the raw JSON in a fixed-height scrollable block under the notice "Question shape not recognised — answer in free text:" and surfaces the same free-text textarea so the user can still respond. This is a defensive fallback against a future change to the AskUserQuestion shape.

    In all three shapes a **Cancel** button sits to the left of Submit in the footer. Cancel POSTs `{approved: false}` (no answer) so the SDK callback resolves as a denial and the agent receives a final answer rather than blocking the broker indefinitely. This mirrors the **Deny** semantics of the generic tool-approval modal.

The modal stays visible until the backend's `approval_resolved` event arrives over the WebSocket; submit-button errors render inline (red text) without closing the modal. There is no client-side timeout — a stuck approval is a UX bug, not a security gate.

**WebSocket reconnect guard.** Both modal flavours subscribe to `wsConnectionStatus.state` (the sessions-broadcast WebSocket, same source as the status strip). When the state is not `'open'` (i.e. `'closed'` or `'error'`), all action buttons — Allow, Deny, Submit, Cancel — are disabled and an amber inline banner reads "Reconnecting — your response will send once the socket is back." The buttons re-enable as soon as the socket transitions back to `'open'`, without dismissing the modal. This prevents the user from POSTing an approval into a dead socket, which would leave the modal open indefinitely because the `approval_resolved` event can never arrive.

**Esc is blocked while an approval modal is open.** Both modal flavours install a window-level capture-phase `keydown` listener for the duration they are mounted. Any Escape keypress is consumed (`preventDefault` + `stopPropagation`) before it can reach the Esc cascade, the command palette, the cheat sheet, or any other overlay handler. The modals are dismiss-only via the action buttons (Allow / Deny / Submit / Cancel) — keyboard dismiss is intentionally disabled to prevent accidental gate resolution. *Added in gap-cycle-10-010.*

## Sidebar system-status card (gap-cycle-08-006)

A card-shaped container is pinned at the sidebar bottom, above the identity block. It exposes two always-visible health rows so users dwelling in the sidebar can answer "system OK?" without scanning the full-width status strip at the bottom of the app shell.

| Row | Condition | Dot colour | Label |
|---|---|---|---|
| **Connection** | WebSocket `'open'` | accent green | Connected |
| **Connection** | WebSocket `'closed'` or `'error'` | rose | Disconnected |
| **Claude** | WebSocket `'open'` | accent green | Reachable |
| **Claude** | WebSocket `'closed'` or `'error'` | rose | Unreachable |

Both rows are derived from the sessions-broadcast `wsConnectionStatus.state`. The card is intentionally redundant with the bottom status strip — the strip is the at-a-glance full-width row; the card is the at-rest read for sidebar dwell.

Note: v17 exposed an amber "Connecting…" state from `agent.state`. v18's `wsConnectionStatus` transitions directly from `'closed'` to `'open'` with no intermediate connecting state; amber is unused in v18.

## Error states

* **Agent error mid-turn.** The current assistant bubble closes with a red error block stating the underlying error message. The session row in the sidebar gains a red flashing pip ("needs attention now"). The user can post another message; if the next turn completes successfully the red flag clears.
* **Auth required / token expired.** The conversation pane shows a banner "Backend requires sign-in" and the composer is disabled until the user re-authenticates.
* **Backend unreachable.** A persistent banner appears at the top of the app shell ("Backend unreachable — retrying"). The conversation continues to render the cached transcript; new sends queue locally and surface a "queued" badge on the user bubble until the connection comes back.
* **Closed session.** The composer is hidden and replaced with a "Reopen session" button. Per [prompt-endpoint](prompt-endpoint.md), HTTP prompts to a closed session return 409 — the same gate the UI enforces.
* **Closed paired-chat-side.** See [paired-chats](paired-chats.md).

## Reconnect / resume

After a network blip or a tab reload the conversation reattaches and any events the agent emitted while the client was away are replayed in order, then the live stream resumes. The user sees the in-flight tool drawer fill in retroactively (no missing rows) and the assistant bubble continues growing from where it left off. If the server was killed mid-turn after the user's prompt was persisted but before any assistant output, the user observes a "resuming prompt from previous session" hint above the user bubble before the agent re-starts the turn.

## The agent loop start/stop semantics

The agent loop for a chat is implicit:

* It starts when the chat is selected for the first time after server boot, or whenever the user sends a prompt to a session whose runner has been idle long enough to have been torn down.
* It runs until the assistant emits the turn-final message, then idles waiting for the next prompt.
* Pressing **Stop** ends the current turn early; the loop returns to idle.
* A long-idle session's runner is torn down server-side (the user observes nothing — the next send transparently spins it back up).
* Closing a session drains its runner; subsequent prompts via [prompt-endpoint](prompt-endpoint.md) get a 409 until the session is reopened.

**History persistence across respawn.** Every time the agent's underlying SDK subprocess writes a transcript line, Bearings mirrors it to durable storage. When the supervisor respawns the subprocess (model swap, idle reap, server restart, recovery from ERROR), the new subprocess inherits the full conversation context — the user observes no "this is the start of the session" reset on the next turn. The mirror is invisible in the UI; it surfaces only as continuity ("the agent still knows what we were just discussing"). Transcripts are scoped to a single Bearings session and cleaned up automatically when the session row is deleted.

## Inspector pane (non-routing subsections)

The right column of the app shell hosts the **Inspector** pane: a tabbed surface that exposes the active session's per-row metadata in long form. Eight tabs are wired today, in the order they render: **Agent**, **Context**, **Instructions**, **Files**, **Changes**, **Metrics**, **Routing**, **Usage**. The first six are described here; the routing-and-usage pair belongs to §"What the user does NOT see in chat" because it is governed by the routing spec.

The pane is empty-state when no session is selected (boot, tag filter empties the list, sidebar selection cleared). Picking a session activates the last-selected tab; **the active-tab choice is sticky across page reloads** — it is persisted to `localStorage` under the key `bearings-v1:inspector-tab` and re-hydrated on boot, falling back to the Agent tab when the value is absent or unrecognised. Persistence is best-effort: a `localStorage` exception (private-browsing mode, storage quota exceeded) is caught silently — the in-memory selection still flips for the lifetime of that page load. **State survives tab switches**: all seven subsection components stay mounted at all times (inactive ones hidden via the HTML `hidden` attribute); switching tabs never destroys a subtree, so per-tab transient state — expanded "Why this model?" panels, scroll positions, already-loaded fetch data — is intact when the user returns to a tab they visited earlier in the same session.

The shape the Inspector reads from the selected row mirrors the API's `SessionOut` envelope (the fields the conversation header band already summarises): `id`, `kind`, `title`, `description`, `session_instructions`, `working_dir`, `model`, `permission_mode`, `max_budget_usd`, `total_cost_usd`, `message_count`, `last_context_pct`, `last_context_tokens`, `last_context_max`, plus the housekeeping timestamps (`created_at`, `updated_at`, `last_viewed_at`, `last_completed_at`, `closed_at`) and flags (`pinned`, `error_pending`, `checklist_item_id`).

### Agent

Surfaces the executor-side configuration in a longer-form layout than the conversation header's compact row. The user sees a label/value grid with:

* **Executor model** — current executor, mapped to its user-facing label (`Sonnet 4.6`, `Haiku 4.5`, `Opus 4.7`) using the same string table the new-session dialog uses; an unknown wire name renders as itself.
* **Permission mode** — the SDK permission profile in force, or `(default)` when unset.
* **Working directory** — absolute path, monospace, wrapping on long paths.
* **Budget cap (USD)** — `max_budget_usd` formatted to two decimals, or `no cap` when unset.
* **Total cost (USD)** — `total_cost_usd` formatted to two decimals.
* **Messages** — the running message count.

The Agent subsection shows the executor wire name only today; the routing-spec fields (advisor, effort, fallback model, beta headers) live in **Inspector Routing** because their UI copy is governed by the routing spec.

### Context

Mirrors the context-window / cost data the header band carries, plus the title and description that the sidebar row truncates. The user sees:

* **Title** — full session title (no truncation).
* **Description** — the session "plug" body, rendered with preserved line breaks; renders `(no description)` when null/empty.
* **Last context-window pressure** — the most-recent turn's context-pressure as a whole-percent integer; `no turn observed yet` when the session has not yet completed an assistant turn.
* **Last context tokens** — the most-recent turn's context-token count, locale-formatted with thousands separators; same `no turn observed yet` empty state.
* **Context-window max** — the model's context-window cap for the most-recent turn, locale-formatted; same empty state.

Below the grid is an **Assembled context** section. Today it renders a placeholder paragraph noting that the system prompt, tag-default overlays, and vault attachments will surface here once the assembled-context API lands. (The structure is in place so the visual layout is stable when those fields are wired through.)

### Instructions

Exposes the per-session free-text instructions (`session_instructions` on `SessionOut`). When the value is a non-empty (post-trim) string, the body renders inside a monospace pre-block with whitespace-preserving wrap. When the value is null, empty, or whitespace-only, the user sees the empty-state copy `No per-session instructions set.` — the renderer treats whitespace-only as empty so a stray newline does not masquerade as content.

An **Edit…** button in the Instructions subsection header opens the SessionEdit modal with the instructions textarea focused (gap-cycle-10-001). The modal is the canonical editor surface for all four session-level fields (Title, Description, Budget, Instructions) — the Inspector body remains a read-only view.

## SessionEdit modal

The SessionEdit modal opens from two entry points:

* Right-click a sidebar session row → **Edit session…** (`session.edit` context-menu action).
* Click **Edit…** in the Inspector → Instructions subsection header — opens the modal with the instructions textarea scrolled into view and focused.

The modal presents five fields seeded from the current session row:

| Field | Type | Notes |
|---|---|---|
| Title | text input | Required; must be non-empty. |
| Description | multi-line textarea | Optional; blank clears the column. |
| Budget cap (USD) | number input | Optional; blank → no cap. Negative values are rejected inline. |
| Tags | chip list + text input | Attached tags render as chips with × to detach. Typing in the input filters the global tag pool; Enter on an existing-name match attaches it; Enter on a non-existent name creates then attaches the tag inline. |
| Session instructions | multi-line monospace textarea | Optional; blank clears the column. |

**Save** fires `PATCH /api/sessions/{id}` with all five fields. The server broadcasts an upsert via the sessions WebSocket so the sidebar row and conversation header update without a hard refresh. The modal closes on 2xx.

**Cancel**, **Esc**, and clicking the backdrop all discard changes and close the modal without firing a PATCH.

### SessionEdit modal — deferred features

* **AI-title-suggestion (✨)** — out of scope. The feature depends on a Claude API backend call that is not yet wired in v0.18.x (root cause: cycle 1 gap-020). The ✨ button is not rendered. This carve-out is documented here and in the component source.

### Files

Aggregated view of every file path the agent has touched in the active session (gap-cycle-09-003). The header strip shows **Files Touched** with a count badge (the number of distinct paths recorded so far).

**Data source**: `conversationStore.turns` — the in-memory turn list maintained by the conversation store reducer. No network call is made; the list updates reactively as new tool events arrive on the WebSocket.

**Path-key precedence** (applied to each `ToolCallView.inputJson`):
1. `file_path` — used by `Read`, `Write`, and `Edit`.
2. `notebook_path` — used by `NotebookEdit`.
3. `path` — used by `Grep`.

`Bash` and `Glob` tool calls are skipped entirely — they do not address a specific file path in a way that is meaningful for the file-touch log.

**Row shape**: each row shows:
* Home-shortened path in monospace (`/home/<user>/…` shortened to `~/…` for column fit; the full path is preserved in the `title` tooltip attribute).
* Last action verb (`Read` / `Write` / `Edit` / `NotebookEdit` / `Grep`).
* Touch count as `× N` when the same path was touched more than once; omitted when `N = 1`.
* Last-touch time formatted by `formatAbsolute` (respects the user's display-timezone preference).

Rows are sorted most-recent touch first. Entries with no recoverable timestamp (hydrated calls whose parent turn has no `createdAt` and whose `startedAt` is `0`) sort after all timestamped rows.

**Empty state**: when no file-touching tool calls have been recorded yet, the subsection shows the heading "No files touched yet" with a one-sentence explanation: "A row appears each time the agent reads, writes, edits, or greps a specific file path."

### Changes

Chronological list of every WRITE-side tool call the agent made in the active session (gap-cycle-09-004). The header strip shows **Changes** with a count badge (the number of change rows recorded so far).

**Data source**: `conversationStore.turns` — the same in-memory turn list used by the Files tab. No network call is made; the list updates reactively as new tool events arrive on the WebSocket.

**Verb mapping** — only three tool names produce rows:

| Tool name | Verb badge | Badge colour |
|---|---|---|
| `Write` | Created | Emerald |
| `Edit` | Edited | Amber |
| `NotebookEdit` | Notebook-edited | Indigo |

All other tool names (`Read`, `Grep`, `Glob`, `Bash`, …) are ignored.

**Path extraction**:
* `Write` / `Edit` → `file_path` key of `inputJson`.
* `NotebookEdit` → `notebook_path` key of `inputJson`.

**Excerpt extraction**: the excerpt shown beneath the path line is derived from the new-content field of the tool call's `inputJson`:
* `Write` → `content` field.
* `Edit` → `new_string` field.
* `NotebookEdit` → `new_source` field.

Processing: split on `\n`, take line 0, trim leading whitespace, clip to 120 characters. An empty excerpt (absent field, parse failure, or blank first line after trimming) suppresses the excerpt row entirely.

**Row shape**: unlike the Files tab (which deduplicates by path), the Changes tab records one row per individual tool call — each `Edit` or `Write` or `NotebookEdit` call is a discrete change event. Rows sorted most-recent first. Entries with no recoverable timestamp sort after all timestamped rows (same derivation as Files: `startedAt` first, `turn.createdAt` fallback, `null` when neither).

**Empty state**: "No changes yet" with the explanation: "A row appears each time the agent writes a new file, edits an existing file, or modifies a notebook cell."

### Metrics

Per-session token totals and tool-call counters (gap-cycle-09-005). Positioned between Changes and Routing to keep the per-session content tabs together; the app-wide rollups (Routing / Usage) remain at the end of the strip.

The subsection renders two cards.

**Card 1 — Token totals.** Four labelled cells in a 2×2 grid:

| Cell | Label | Data source | Accent |
|---|---|---|---|
| Input | "Input" | `conversationStore.sessionInputTokens` — accumulated from `message_complete` frames, reset on session-switch | default (`text-fg`) |
| Output | "Output" | `conversationStore.sessionOutputTokens` | default |
| Cache read | "Cache read" | `conversationStore.sessionCacheReadTokens` | emerald (`text-emerald-400`) |
| Cache write | "Cache write" | Not yet available — the v18 backend does not emit `cache_creation_tokens` | default — renders `—` until the backend surfaces this field |

All token values use the standard short-notation formatter: `< 1 000` → raw integer, `≥ 1 000` → `N.Nk`, `≥ 1 000 000` → `N.NM`.

**Card 2 — Tool calls.** Four labelled cells in a 2×2 grid, all derived from `conversationStore.turns`:

| Cell | Label | Value | Accent |
|---|---|---|---|
| Total | "Total" | Count of all `ToolCallView` entries across all turns | default |
| Running | "Running" | Count where `done === false` | amber (`text-amber-400`) when > 0; muted at 0 |
| Failed | "Failed" | Count where `done === true && ok === false` | rose (`text-rose-400`) when > 0; muted at 0 |
| Total elapsed | "Total elapsed" | Sum of `durationMs` for finished calls only (`done === true && durationMs !== null`) | default — renders `—` when no finished calls exist |

The elapsed formatter: `< 1 000 ms` → `Nms`; `< 60 000 ms` → `N.Ns`; `≥ 60 000 ms` → `Nm Ns`.

**Footer**: a link to `/analytics` with the label "View cross-session rollups →", so the user can navigate from per-session metrics to the app-wide Usage tab.

## CollapsibleBody

Long content areas — the assistant message body and the tool-output stream — are wrapped in a `CollapsibleBody` component (`common/CollapsibleBody.svelte`).

**Folded state (content height > threshold):**
* The wrapper clamps to the threshold height (default 320 px).
* The bottom 64 px of the visible area fades out via a CSS `mask-image` gradient, signalling to the user that content continues below.
* A **"Show full"** button appears beneath the clamped area.

**Expanded state:**
* Clicking "Show full" removes the clamp and mask, revealing the full content height.
* The "Show full" button is replaced by a **"Collapse"** affordance.
* Scrolling does not re-fold the wrapper — only clicking "Collapse" contracts it.

**Content under threshold:** No fold UI is rendered; the content displays normally.

**ResizeObserver lifecycle:** A `ResizeObserver` watches the inner content element (not the clamping wrapper). The inner element has no height constraint, so it always reports the content's natural height — even while the outer wrapper is clamped with `overflow: hidden`. This means streaming output that grows past the threshold triggers the fold UI smoothly without a full re-render, and theme-driven font swaps that change line height are re-evaluated automatically.

The threshold and fade-zone constants live in `config.ts` (`COLLAPSIBLE_BODY_THRESHOLD_PX`, `COLLAPSIBLE_BODY_FADE_PX`). The expand/collapse button strings are in `COLLAPSIBLE_BODY_STRINGS` in the same file.

## AccentCards

Two compact info cards render between the conversation header band and the message list. They surface always-on Bearings value-adds the user might not otherwise notice.

**Card 1 — Token cache savings.** Hidden until the session has accumulated at least one cache-read token. Once visible, it shows:

> Saved X% tokens — N vs M cached

where:
- *X%* = the percentage of total token cost avoided through prompt caching (`cache_read_tokens × 0.9 / (executor_input_tokens + cache_read_tokens) × 100`, rounded to the nearest integer).
- *N* = the actual token cost for this session after the 90 % cache-read discount (`executor_input_tokens + cache_read_tokens × 0.1`).
- *M* = what the token cost would have been without caching (`executor_input_tokens + cache_read_tokens`).

Both *N* and *M* are formatted using the standard short notation (`1.2k`, `3.4M`).

**Card 2 — Recovery armed.** Always rendered, regardless of cache activity:

> Recovery armed — Up to 5000 events buffered

The number (5000) is the per-session WebSocket reconnect ring buffer cap (`WS_RING_BUFFER_CAP` in `config.ts`, mirroring `RING_BUFFER_MAX` in the backend constants). This card communicates the reconnect guarantee without requiring the user to consult documentation.

Both cards are defined in `ACCENT_CARDS_STRINGS` (`config.ts`). Neither card has interactive elements.

## What the user does NOT see in chat

These belong to other subsystems:

* The execution chain that produced the routing decision — see the **Inspector Routing** subsection (per spec §6: current models + source + reason, per-message badge timeline, advisor totals, quota delta this session, "Why this model?" expandable evaluation chain).
* The full per-week token rollups — see the **Inspector Usage** subsection (per spec §10: 7-day headroom chart, by-model table, advisor-effectiveness widget, rules-to-review list).
* The autonomous driver progress for a paired chat — see [checklists](checklists.md).

## Session merge (gap-cycle-03-008)

**Trigger:** Sidebar context-menu on a session row → "Merge into…".

**Picker:** `SessionPickerModal` opens and lists all other sessions (excluding the source). The user can filter by title. Clicking a destination session row triggers the merge immediately.

**Inline create (gap-cycle-10-011):** A "+ Create a new session" affordance in the footer flips the modal body to an inline create form (Title + tag chip multi-select, ≥ 1 tag required). Submitting the form calls `POST /api/sessions` then immediately fires `POST /api/sessions/{src_id}/reorg/merge?target={new_id}` — both in one user gesture. "Back to list" returns to the session list without closing the modal. The `ReorgPicker` (move / split flows) has the same inline create affordance plus tag-filter chips above the session list that narrow candidates via server-side `tag_ids=` filtering.

**API contract:**

```
POST /api/sessions/{src_id}/reorg/merge?target={dst_id}
```

Atomic transaction:
1. All messages from `src_id` are re-parented to `dst_id` (preserving `created_at` order).
2. `message_count` on `dst_id` is updated.
3. A `reorg_audit` row is written (`id` prefix `rga_`), carrying `src_title`, `merged_at`, and `boundary_msg_id` (the id of the first message originally from the source — `NULL` when the source had no messages).
4. `src_id` is deleted (cascades to its checkpoints, tags, sdk entries, etc.).

Returns `200` with the `ReorgAuditOut` envelope on success.

**Error responses:**
- `409` — self-merge (`src_id == dst_id`).
- `404` — either session does not exist.

**After merge:** The frontend navigates to the destination session (`/sessions/{dst_id}`). The `reorg_audit` row serves as the audit trail for the operation.

**Divider:** The `boundary_msg_id` field returned by the API identifies the first message from the merged source. The frontend renders a `ReorgAuditDivider` row in the merged conversation transcript at the boundary point.

## Persistent reorg-audit contract (gap-cycle-03-009)

Reorg audit rows written by the merge endpoint survive page refresh.  On every conversation load the frontend calls `GET /api/sessions/{id}/reorg/audits`, which returns all `reorg_audit` rows for that destination session (oldest-first).  Dividers are hydrated from this response before the first render.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/sessions/{id}/reorg/audits` | List all merge-audit rows for session `id`. Returns `{"items": [...]}` with `ReorgAuditOut` objects. Returns `[]` when no merges exist. |
| `DELETE` | `/api/sessions/{id}/reorg/audits/{auditId}` | Undo the merge and delete the audit row. Returns `{"new_session_id": "ses_..."}` on success. |

### Undo semantics

The `DELETE` endpoint atomically:

1. Validates the audit row exists and belongs to `{id}`.
2. Stale-checks: if any message in the destination session has `created_at > merged_at`, or if the recorded `boundary_msg_id` no longer exists in the session, returns `409 Conflict` (operation cannot be safely reversed).
3. Creates a new session with the original source title.
4. Moves all messages in the destination whose `created_at ≥ boundary_msg.created_at` to the new session.
5. Removes the `reorg_audit` row.

**Error responses:**
- `404` — audit row absent or belongs to a different session.
- `409` — destination session has been mutated since the merge (stale audit).

### Divider Undo button

`ReorgAuditDivider` renders an inline **Undo** button for any entry with a `serverAuditId` when the conversation passes an `onUndo` callback (which calls `DELETE /api/sessions/{id}/reorg/audits/{auditId}`).  The button survives page refresh because audit rows are server-persisted.  On success the divider unmounts; on `409` the error propagates to the caller.

---

## Addendum — gap-cycle-13-002: unified reorg contract (split + move)

### New server endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/sessions/{src}/reorg/split?target={dst}&from_seq={n}` | Atomically re-parent all messages with `rowid >= n` from `src` to `dst`. Writes a `kind='split'` audit row. Returns `ReorgSplitOut` (`{audit, moved_message_ids}`). |
| `POST` | `/api/sessions/{src}/reorg/move?target={dst}&message_id={id}` | Atomically re-parent one message from `src` to `dst`. Writes a `kind='move'` audit row. Returns `ReorgAuditOut`. |

All three reorg endpoints (`merge`, `split`, `move`) share the same audit infrastructure: `GET /api/sessions/{id}/reorg/audits` returns all three kinds, and `DELETE /api/sessions/{id}/reorg/audits/{auditId}` reverses any of them.

### `dst_session_id` column semantics

For all three kinds, `dst_session_id` in the `reorg_audit` table is **the session that hosts the divider** (the one the user sees the boundary in):

- `merge`: content flowed INTO `dst_session_id`; divider marks where the import begins.
- `split`: content flowed OUT OF `dst_session_id`; divider marks the truncation point.
- `move`: content flowed OUT OF `dst_session_id`; divider marks where the message was.

`src_session_id` is always the "other" session (deleted for merge; still-live for split/move).

### Undo semantics by kind

The `DELETE` endpoint dispatches by `kind`:

- **merge**: creates a new session, moves messages back, returns `new_session_id` (freshly created).
- **split**: moves split messages from the target back to `dst_session_id` (original source), returns `dst_session_id`.
- **move**: moves the single message from the target back to `dst_session_id`, returns `dst_session_id`.

Stale checks for split: new messages added to the target session after the split timestamp → `409`.
Stale checks for move: the moved message no longer exists in the target session → `409`.

### Frontend store changes

- `commitMove` — replaced per-message `POST /api/messages/{id}/move` with `POST /api/sessions/{src}/reorg/move`. The returned audit row sets `serverAuditId` immediately; the undo toast uses the DELETE endpoint.
- `commitSplit` — replaced `listMessages` + per-message `moveMessage` loop with `POST /api/sessions/{src}/reorg/split`. Returns the audit row and `moved_message_ids` in one atomic call.
- `loadAudits` — now handles all three kinds from the server (not just `merge`).
- `undoReorg` (toast undo) — delegates to `undoMerge` (DELETE endpoint) when `serverAuditId` is present, which is always the case after this gap.

### Divider rendering

`ReorgAuditDivider` already renders all three kinds correctly. `Conversation.svelte` now passes `onUndo` for any entry with a `serverAuditId` (previously only for `kind === "merge"`).

---

## Addendum — gap-cycle-13-003: token totals hydration contract

### Problem

The Inspector Metrics tab and the header dollar/token meter derive their per-session input / output / cache-read token totals from `conversationStore.session*Tokens` counters that accumulate exclusively from `message_complete` WebSocket events received in the current page-life. On session open, `resetConversation()` zeros the counters; they grow as the WS ring-buffer replay delivers historical events. For sessions whose runner has been reaped or whose events are older than the 5 000-event ring-buffer cap, no replay arrives and the counters stay at zero — even though the complete token history is durably stored in the `messages` table.

### New server endpoint

`GET /api/sessions/{id}/tokens` returns `{input, output, cache_read, cache_creation}` — the `COALESCE(SUM(...), 0)` aggregate over all assistant-role rows for the session. `cache_creation` is always `0` in v18 (no `cache_creation_tokens` column); the field is reserved for when the backend surface lands. Returns `404` when the session is absent; returns all-zero totals when the session exists but has no completed assistant turns.

### Hydration contract

The conversation pane calls `GET /api/sessions/{id}/tokens` once on session open, sequentially after `listMessagesPage` / `hydrateToolCalls` / `hydrateTodos` and before `connectSession` (WS subscribe). `hydrateTokens(totals)` from `conversation.svelte.ts`:

1. Sets `sessionInputTokens`, `sessionOutputTokens`, `sessionCacheReadTokens`, `sessionCacheWriteTokens` from the response.
2. Sets an internal flag `_tokensHydratedPending = true`.

The flag suppresses accumulation in `applySessionTokens` while WS ring-buffer replay is in progress so that historical `message_complete` replay events do not double-count tokens already captured in the DB aggregate.

When the WS delivers the synthetic `runner_status` frame (emitted after ring-buffer replay is complete), `applyRunnerStatus` clears `_tokensHydratedPending`. From that point forward, `message_complete` events for genuinely new turns accumulate on top of the hydrated base.

**No double-counting**: WS replay fires before `runner_status`; accumulation is suppressed for that window. Live turns fire after `runner_status`; they accumulate normally.

**Failure handling**: If the `/tokens` fetch fails, `hydrateTokens` is never called, `_tokensHydratedPending` stays `false`, and the counters fall back to the previous WS-replay-only behaviour (starts at zero, grows with replay). Non-fatal.

**Session-switch**: `resetConversation()` zeros all four token counters and clears `_tokensHydratedPending`. The hydration flow runs fresh for each session selection.

---

## Addendum — gap-cycle-13-004: system-prompt layers contract

### Overview

The Inspector Instructions tab renders the **full assembled system
prompt** for the active session as a list of typed layer rows.  Each row
shows: the layer kind label, the optional filesystem source path, an
approximate token count, and a collapsed/expanded body toggle.

### Endpoint

`GET /api/sessions/{id}/system_prompt` returns:

```json
{
  "layers": [
    {
      "kind": "session_instructions",
      "body": "You are an executor.",
      "token_count": 5,
      "source_path": null
    },
    {
      "kind": "baseline",
      "body": "<CLOSE_SESSION_INSTRUCTION text>",
      "token_count": 42,
      "source_path": null
    },
    {
      "kind": "project_claude_md",
      "body": "<CLAUDE.md contents>",
      "token_count": 310,
      "source_path": "/home/user/project/CLAUDE.md"
    }
  ],
  "total_tokens": 357,
  "token_count_approximate": true
}
```

* `404` when the session is not found.
* `token_count_approximate` is always `true` — token counts use the
  `len(body) // 4` approximation (no tokenizer dependency).

### Layer kinds and display order

| Kind | Description | source_path |
|---|---|---|
| `session_instructions` | Per-session steering from the session row's `session_instructions` column. Omitted when null or empty. | null |
| `baseline` | Bearings core surface (`CLOSE_SESSION_INSTRUCTION`). Always present. | null |
| `project_claude_md` | One row per `CLAUDE.md` found walking up from the session's `working_dir` to the filesystem root. | Absolute path to the file |
| `tag_memory` | One row per tag whose `working_dir` yields a readable `CLAUDE.md`. Ordered lowest-precedence first (mirrors `resolve_claude_md_blocks`). | Absolute path to the file |
| `template_baseline` | Not emitted in v18 — the template baseline is baked into `session_instructions` at session creation. Reserved for API-shape stability. | null |

### Empty-state rules

Layers with no content are **omitted** from the `layers` array.  The
frontend (`InspectorInstructions.svelte`) renders a per-kind empty-state
row when no layers of that kind appear in the response.  The `baseline`
layer is always non-empty.

### Frontend behaviour

* `InspectorInstructions` fetches `GET /api/sessions/{id}/system_prompt`
  on mount and on session-id change via a `$effect`.
* Each kind appears as a collapsible section with its label.  The
  `session_instructions` section retains the `Edit…` button that opens
  `SessionEdit` scrolled to the instructions textarea.
* Body collapse default: layers whose body exceeds 500 chars are
  collapsed; shorter layers are expanded.
* After a `SessionEdit` save, the component re-fetches layers so the
  updated `session_instructions` is visible immediately.
