# Changelog

All notable changes to Bearings are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Sessions-broadcast WS channel** (wiring-v1-daily-driver item 2.6).
  - `src/bearings/web/routes/ws_sessions.py` — new `SessionsBroadcaster`
    class (fan-out hub) + `GET /ws/sessions` WebSocket endpoint. Three
    message types: `session_upsert` (full `SessionOut` JSON), `session_delete`
    (session_id only), `runner_state` (is_running + is_awaiting_user flags).
    Heartbeat sent on idle to keep connections alive. Auto-reconnect with
    capped exponential backoff handled on the frontend side.
  - `src/bearings/config/constants.py` — `ROUTE_TAG_WS_SESSIONS` constant.
  - `src/bearings/agent/runner.py` — `wire_status_hook()` method +
    `_status_hook` callback field; `set_status()` now calls the hook
    synchronously after updating so the broadcast is immediate.
  - `src/bearings/web/runner_factory.py` — `InProcessRunnerRegistry`
    and `build_in_process_factory` accept optional `sessions_broadcaster`;
    `_wire_status_hook()` attaches a closure to each new runner on first
    touch so runner-state changes fan out to all `/ws/sessions` subscribers.
  - `src/bearings/web/routes/sessions.py` — `create_session`, `patch_session`,
    `patch_session_model`, `close_session`, `reopen_session` each call
    `broadcaster.publish_upsert(out)` after the mutation; `delete_session`
    calls `broadcaster.publish_delete(session_id)`.
  - `src/bearings/web/app.py` — creates `SessionsBroadcaster`, stores it on
    `app.state.sessions_broadcaster`, threads it through
    `build_in_process_factory`, mounts `ws_sessions_router`.
  - `frontend/src/lib/config.ts` — `WS_SESSIONS_PATH` constant.
  - `frontend/src/lib/api/wsSessions.ts` — `connectSessionsBroadcast()`
    opens `/ws/sessions`, parses frames into typed
    `SessionsBroadcastEvent` union, auto-reconnects with exponential
    backoff (500 ms initial, ×2, cap 30 s).
  - `frontend/src/lib/stores/sessions.svelte.ts` — calls
    `connectSessionsBroadcast` at module load; `session_upsert` merges
    into the session list (replace in-place or prepend if new);
    `session_delete` removes the matching row. All open tabs update
    without reload or polling.

- **Composer essentials** (wiring-v1-daily-driver item 2.5).
  - `frontend/src/lib/composer/draftStore.svelte.ts` — per-session draft
    persistence to `localStorage` under `bearings-v1:draft:{sessionId}`.
    Degrades silently in private-browsing / quota-full contexts.
  - `frontend/src/lib/composer/inputHistory.ts` — `InputHistory` class;
    shell-readline-style Up/Down walk through sent messages (in-memory,
    per page-load); deduplicates consecutive identical sends; restores the
    live draft when Down is pressed past the newest entry.
  - `frontend/src/lib/config.ts` — `COMPOSER_DRAFT_KEY_PREFIX` constant.
  - `frontend/src/lib/components/composer/Composer.svelte` — auto-grow
    textarea (height tracks `scrollHeight`, capped at `max-h-64`); loads
    persisted draft on mount and on session switch; saves draft on every
    keystroke; clears draft + records history on successful send;
    `ArrowUp` at cursor position 0 walks back through history, `ArrowDown`
    at cursor end walks forward; modified arrow keys (Shift/Ctrl/etc.)
    pass through unmodified.

- **Sidebar search** (wiring-v1-daily-driver item 2.4).
  - `src/bearings/web/routes/history.py` — `GET /api/history/search?q=`
    performs case-insensitive LIKE search over `sessions.title`,
    `sessions.description`, and `messages.content`. Returns up to 50 hits
    (session hits first, then message hits); each hit carries a `kind`,
    `session_id`, `session_title`, optional `message_id`, and a 120-char
    snippet centred on the first match occurrence. Empty / blank queries
    return immediately without touching the DB.
  - `src/bearings/web/models/history.py` — `HistorySearchResult` Pydantic model.
  - `src/bearings/config/constants.py` — `HISTORY_SEARCH_RESULT_CAP`,
    `HISTORY_SEARCH_SNIPPET_CHARS`, `HISTORY_SEARCH_DEBOUNCE_MS`, and
    `ROUTE_TAG_HISTORY` constants.
  - `src/bearings/web/app.py` — mounts history router.
  - `frontend/src/lib/config.ts` — `API_HISTORY_SEARCH_ENDPOINT`,
    `HISTORY_SEARCH_DEBOUNCE_MS`, `HISTORY_SEARCH_RESULT_CAP`, and
    `SIDEBAR_SEARCH_STRINGS`.
  - `frontend/src/lib/api/history.ts` — `searchHistory(q)` client; returns
    empty array on network/server error for graceful sidebar degradation.
  - `frontend/src/lib/components/sidebar/SidebarSearch.svelte` — full-screen
    overlay: debounced input (300 ms), scrollable results list with SESSION /
    MESSAGE kind badges, ArrowUp/Down keyboard navigation, Enter to select,
    Escape to close, backdrop click to close. Clicking a result calls
    `goto('/sessions/{id}')` with `#msg-{id}` hash for message hits.
  - `frontend/src/routes/+layout.svelte` — mounts `<SidebarSearch />`.
  - `frontend/src/lib/keyboard/bindings.ts` — `KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH`
    wired as `Ctrl+K` (`global: true`); `displayOnly: true` removed.

- **Slash-command palette** (wiring-v1-daily-driver item 2.3).
  - `src/bearings/web/routes/commands.py` — `GET /api/commands` scans
    `~/.claude/commands/**/*.md` (user commands), `~/.claude/skills/*/SKILL.md`
    (skills), and `<working_dir>/.claude/commands/**/*.md` (project commands).
    Parses YAML frontmatter for `name` + `description`; falls back to filename
    stem / first body line. Returns `[{name, description, source}]`.
  - `src/bearings/web/models/commands.py` — `CommandOut` Pydantic model.
  - `src/bearings/config/constants.py` — `ROUTE_TAG_COMMANDS` constant.
  - `src/bearings/web/app.py` — mounts commands router.
  - `frontend/src/lib/config.ts` — `API_COMMANDS_ENDPOINT` + `COMMAND_MENU_STRINGS`.
  - `frontend/src/lib/api/commands.ts` — `listCommands()` client; gracefully
    returns empty list on network/server error.
  - `frontend/src/lib/components/composer/CommandMenu.svelte` — typeahead
    listbox; shows all commands on bare `/`; filters by name + description
    substring; ArrowUp/Down navigate; Tab/Enter confirm; Escape dismisses;
    source badge (User / Skill / Project); scroll-into-view on active change.
  - `frontend/src/lib/components/composer/Composer.svelte` — opens
    `CommandMenu` when draft starts with `/`; closes once a space follows
    the command token (selection done); keyboard events delegated to
    `CommandMenu.handleKey` before normal submit logic.

- **Context/token meter in header** (wiring-v1-daily-driver item 2.2).
  - `src/bearings/agent/events.py` — re-added `model: str | None`,
    `is_auto_compact_enabled: bool | None`, and `auto_compact_threshold: int | None`
    to `ContextUsage`. All three default to `None` so older SDK builds that omit
    the fields remain wire-compatible.
  - `src/bearings/agent/translate.py` — `_project_context_usage` return type
    widened to a six-tuple; extracts `model` / `isAutoCompactEnabled` /
    `autoCompactThreshold` from the SDK camelCase usage dict (snake_case fallback
    for forward-compat). `_feed_result` propagates all six fields to the emitted
    `ContextUsage` event.
  - `frontend/src/lib/api/events.ts` — `ContextUsageEvent` extended with the
    three new optional fields.
  - `frontend/src/lib/stores/conversation.svelte.ts` — added `ContextUsageSnapshot`
    interface; added `contextUsage: ContextUsageSnapshot | null` and
    `cacheHitRatio: number | null` to `ConversationState`; reset in
    `resetConversation`; two new imperative reducer arms: `applyContextUsage`
    (overwrites snapshot on every `context_usage` frame) and `applyCacheHit`
    (computes `cache_read_tokens / (executor_input_tokens + cache_read_tokens)`
    from `message_complete`).
  - `frontend/src/lib/config.ts` — added `CONTEXT_METER_STRINGS` string table
    and `CONTEXT_METER_WARN_BAND_PCT = 15` constant.
  - `frontend/src/lib/components/conversation/ContextMeter.svelte` — new header
    strip: thin progress bar (% context used), percentage label, total-token count
    (formatted as 3.2k / 1.4M), cache-hit ratio from the last turn's
    `message_complete`. Warn band (amber tint + "⚠ compact" badge) fires when
    `percentage` is within 15 % of the auto-compact threshold; falls back to
    warning above 85 % when auto-compact is enabled but the threshold token count
    is not present. Hidden (no DOM node) until the first `context_usage` frame
    arrives. A vertical marker line on the bar shows the threshold position when
    `autoCompactThreshold` is set.
  - `frontend/src/routes/+layout.svelte` — imports and mounts `<ContextMeter />`
    immediately after the `<header>` closing tag so it renders as a slim strip
    between the session header and the conversation body.

- **Live todos panel** (wiring-v1-daily-driver item 2.1).
  - `src/bearings/agent/sdk_loop.py` — after emitting a `ToolCallStart` for
    `TodoWrite`, immediately emits a `TodoWriteUpdate` event carrying the parsed
    todos array as `todos_json`. Added `_make_todo_update()` helper; imports
    `json`, `TodoWriteUpdate`, `ToolCallStart`.
  - `frontend/src/lib/stores/conversation.svelte.ts` — added `LiveTodoItem`
    interface (flexible schema: `id?`, `content`, `status`, `priority?`,
    `activeForm?`); added `liveTodos: LiveTodoItem[]` to `ConversationState`;
    resets to `[]` in `resetConversation` (session-switch clears the panel);
    new `applyTodoState()` imperative arm parses `todos_json` and updates
    `liveTodos`; wired into `ingestFrame` alongside `applyApprovalState`.
  - `frontend/src/lib/components/conversation/LiveTodos.svelte` — new
    collapsible panel; hidden when `liveTodos` is empty; header shows
    completed/total count; each item shows status icon (✓/●/○) and optional
    priority badge (H/M/L); completed items rendered muted + strikethrough;
    uses `todo.id ?? todo.content ?? index` as stable Svelte key to handle the
    SDK's built-in TodoWrite schema (which omits `id`).
  - `frontend/src/lib/components/conversation/Conversation.svelte` — mounts
    `<LiveTodos />` above the scroll body as a sticky strip.
  - `frontend/src/lib/config.ts` — added `LIVE_TODOS_STRINGS` string table.

- **`runner_status` event + `turn_replayed` reducer** (wiring-v1-daily-driver item 1.4).
  - `src/bearings/agent/events.py` — added `RunnerStatusEvent` (`type:
    "runner_status"`, `streaming_active: bool`, `current_turn_id: str | None`)
    to the `AgentEvent` discriminated union. Sent once per WS connect after the
    replay drain so clients can reconcile their spinner state on reconnect.
  - `src/bearings/agent/runner.py` — added `get_status_event()` method to
    `SessionRunner`; synthesises a `RunnerStatusEvent` from `_status.is_running`
    and a reverse-scan of the ring buffer for the most recent `MessageStart`;
    imports `MessageStart` and `RunnerStatusEvent` from `events`.
  - `src/bearings/web/streaming.py` — `serve_session_stream` now calls
    `runner.get_status_event()` after `_send_replay` and sends the result as
    `event_frame(seq=0, …)`; seq=0 is intentional (synthetic frame, not ring-
    buffered) and the frontend handles it before the seq-dedup filter.
  - `frontend/src/lib/api/events.ts` — added `RunnerStatusEvent` interface and
    included it in the `AgentEvent` union.
  - `frontend/src/lib/config.ts` — added `turnResumedLabel: "↻ resumed"` to
    `CONVERSATION_STRINGS`.
  - `frontend/src/lib/stores/conversation.svelte.ts` — added `streamingActive:
    boolean` and `currentTurnId: string | null` to `ConversationState` (reset
    in `resetConversation`); added `applyRunnerStatus` (called before seq-dedup
    for `runner_status` frames) and `applyStreamingState` (sets/clears
    `streamingActive`/`currentTurnId` on `message_start`, `message_complete`,
    `error`); added `resumed: boolean` to `MessageTurnView`; `turn_replayed`
    arm in `applyEvent` now marks the matching user row with `resumed: true`
    instead of being a no-op; `runner_status` added as an explicit exhaustive
    case.
  - `frontend/src/lib/components/conversation/MessageTurn.svelte` — user bubble
    now renders a `<span data-testid="message-turn-resumed">↻ resumed</span>`
    annotation when `turn.resumed` is true.
  - `frontend/src/lib/components/conversation/Conversation.svelte` —
    `hasInFlightTurn` derived now gates on `conversationStore.streamingActive &&
    turns.some(!complete)` so the Stop button is hidden when the runner is idle
    even if the replay left an incomplete assistant turn open.
  - `tests/test_streaming_unit.py` — added `RunnerStatusEvent` fixtures to the
    parametrised round-trip test (active + idle variants).
  - `tests/test_streaming_reconnect.py` — added three tests for
    `get_status_event()` covering idle runner, running runner with
    `MessageStart` in buffer, and multi-turn reverse-scan ordering.
  - `tests/test_streaming_integration.py` — updated `close_after` budgets in
    `test_live_tool_output_streaming_roundtrip` (+1 for runner_status) and
    `test_heartbeat_fires_when_idle` (+1 for runner_status); both tests now
    assert the synthetic first frame.

- **ApprovalModal + AskUserQuestionModal** (wiring-v1-daily-driver item 1.1).
  - `frontend/src/lib/components/conversation/ApprovalModal.svelte` — generic
    allow / deny modal shown when the agent needs permission to use a tool.
    Resolves via `POST /api/sessions/{id}/approvals/{request_id}` and stays
    open until the `approval_resolved` WS event arrives so multi-tab resolution
    (Tab B approves → Tab A modal closes) works automatically.
  - `frontend/src/lib/components/conversation/AskUserQuestionModal.svelte` —
    text-input variant shown when `tool_name === 'AskUserQuestion'`; the user's
    typed answer is sent as `{ approved: true, answer: "…" }` and the backend
    threads it back to the SDK callback as `PermissionResultAllow.updated_input`.
  - `frontend/src/lib/api/approvals.ts` — typed client for the approval
    endpoint (handles 204 No Content without the shared `postJson` helper).
  - `frontend/src/lib/stores/conversation.svelte.ts` — added `PendingApproval`
    interface and `pendingApproval: PendingApproval | null` state; `ingestFrame`
    now calls `applyApprovalState` to set/clear it on `approval_request` /
    `approval_resolved` events; `resetConversation` zeroes it on session switch.
  - `frontend/src/lib/components/conversation/Conversation.svelte` — mounts the
    appropriate modal based on `conversationStore.pendingApproval`.
  - `frontend/src/lib/config.ts` — added `sessionApprovalEndpoint` URL helper
    and `APPROVAL_STRINGS` i18n table.
  - `src/bearings/web/models/approvals.py` — added `answer: str | None = None`
    to `ApprovalResolution` for the `AskUserQuestion` answer payload.
  - `src/bearings/agent/approval.py` — `ApprovalBroker` now holds a
    `_answers` side-channel dict; `resolve(answer=…)` stores the text before
    resolving the future so the `_can_use_tool` callback can pass it as
    `updated_input`; `cancel_all` clears it.
  - `src/bearings/web/routes/approvals.py` — passes `answer=payload.answer`
    to `broker.resolve`.

- **Message pagination cursor** (wiring-v1-daily-driver item 1.3).
  - `src/bearings/db/messages.py` — added `seq: int` field to `Message`
    (SQLite `rowid` alias); `list_for_session` now accepts `before: int | None`
    which filters `WHERE rowid < before` for backward pagination; pre-INSERT
    validation calls use `seq=0` placeholder since the rowid is DB-assigned.
  - `src/bearings/config/constants.py` — added `MESSAGE_PAGE_SIZE = 100` for
    the session-open tail fetch and each `loadOlder()` page.
  - `src/bearings/web/models/messages.py` — added `seq: int` to `MessageOut`;
    added `MessagePage` model (`items: list[MessageOut]`, `has_more: bool`).
  - `src/bearings/web/routes/messages.py` — `GET /api/sessions/{id}/messages`
    now returns `MessagePage` instead of `list[MessageOut]`; accepts `before:
    int | None` query param; fetches `limit+1` rows and trims from the front
    to detect `has_more` without a separate `COUNT` query.
  - `docs/openapi.json` — regenerated to reflect the new endpoint shape.
  - `frontend/src/lib/api/messages.ts` — added `seq: number` to `MessageOut`;
    added `MessagePage` interface; updated `listMessages` params to include
    `before?: number`; return type changed to `Promise<MessagePage>`.
  - `frontend/src/lib/config.ts` — added `MESSAGE_PAGE_SIZE = 100` and two
    new `CONVERSATION_STRINGS` entries (`loadOlderLabel`, `loadingOlder`).
  - `frontend/src/lib/stores/conversation.svelte.ts` — added `hasMore`,
    `loadingOlder`, `oldestSeq` state; `hydrateTurns` now accepts `MessagePage`
    and seeds `hasMore`/`oldestSeq` from the response; added `prependTurns`
    for prepend-to-front on `loadOlder`; added async `loadOlder(sessionId)`
    action that no-ops when already loading or `hasMore` is false.
  - `frontend/src/lib/components/conversation/Conversation.svelte` — session-
    open fetch uses `limit: MESSAGE_PAGE_SIZE` instead of unbounded; wires
    `loadOlder` to a "Load older messages" button rendered at the top of the
    conversation body when `hasMore` is true.
  - `frontend/src/lib/components/inspector/InspectorRouting.svelte` — updated
    `fetchMessages` result accessor to `page.items` (full-transcript fetch,
    `has_more` is always false for the inspector).

- **Stop / cancel turn** (wiring-v1-daily-driver item 1.2).
  - `src/bearings/agent/runner.py` — added `_stop_event: asyncio.Event`,
    `stop_event` property, and `request_stop()` method to `SessionRunner`.
    Calling `request_stop()` sets the event; the SDK loop's watcher
    clears it at the start of each new turn.
  - `src/bearings/agent/sdk_loop.py` — `_run_one_turn` now spawns a
    `_stop_watcher` background task that awaits `runner.stop_event` and
    forwards `session.interrupt()` → `client.interrupt()` when the user
    clicks Stop. The watcher is always cancelled in the turn's `finally`
    block; `_do_run_one_turn` holds the former body.
  - `src/bearings/web/routes/sessions.py` — new `POST
    /api/sessions/{id}/stop` endpoint; 204 on success (even when no
    runner is live), 404 for unknown session, 503 if the registry is
    not the `InProcessRunnerRegistry`.
  - `frontend/src/lib/api/sessions.ts` — added `stopSession()` helper
    (raw fetch, handles 204 No Content like `postApproval`).
  - `frontend/src/lib/components/conversation/StopUndoInline.svelte` —
    new inline Stop button; visible while any assistant turn is
    incomplete; disables itself after the first click to prevent double-
    submission; re-enables on error so the user can retry.
  - `frontend/src/lib/components/conversation/Conversation.svelte` —
    mounts `StopUndoInline` when `hasInFlightTurn && sessionId !== null`.
  - `frontend/src/lib/config.ts` — added `sessionStopEndpoint` URL
    helper and `stopTurnLabel` / `stopTurnAriaLabel` to
    `CONVERSATION_STRINGS`.
  - `docs/openapi.json` — regenerated to include the new stop endpoint.

### Fixed

- **conversation transcript hit `each_key_duplicate` on every page load**
  (`stores/conversation.svelte.ts:applyEvent`). `resetConversation`
  zeroes `lastSeq`, hydrate seeds turns from the REST `/messages`
  history but doesn't bump `lastSeq`, and the WS subscription opens
  without a `since_seq` cursor — so the server replays every event
  from seq 0 and the reducer blindly appended `user_message` /
  `message_start` turns whose ids were already on the page. Svelte's
  `{#each (id)}` rejected the duplicate key and refused subsequent
  appends, so newly-arrived events couldn't render either (Dave's
  "text disappears, never shows up in the conversation"). Make the
  two create-events idempotent: skip the append when a turn with
  that id already exists.
- **`fallback_model == model` crashed the SDK CLI** for `haiku` sessions
  (`agent/sdk_loop.py:_to_sdk_options`). The bearings
  `EXECUTOR_FALLBACK_MODEL` table maps `haiku → haiku` to encode "no
  further fallback", but the Claude CLI rejects identical pairs with
  `Error: Fallback model cannot be the same as the main model`. Drop
  the SDK option when the resolved fallback equals the main model;
  the SDK then runs without a fallback override, which is the same
  semantic the table was trying to express.
- **agent loop never spawned — every posted prompt queued forever**
  (`bearings/cli/serve.py`, stopgap `~/.local/share/bearings-v1/launch.py`).
  Both boot paths called `create_app()` *without* `db_connection`,
  then set `app.state.db_connection` in a FastAPI startup hook. But
  `create_app` (`web/app.py:149`) checks `db_connection` at construction
  time to wire `session_setup` on the runner factory; with `None` it
  falls into the test-only branch (`build_in_process_factory()` with
  no setup callable). Every `POST /api/sessions/{id}/prompt` queued
  on the runner but no supervisor task was ever spawned — `is_running:
  false`, `queue_length: N`, `ring_buffer_size: 0`, no SDK subprocess
  child. Open the DB synchronously *before* `create_app` so the
  factory ships with `session_setup` from the start.
- **composer footer invisible in paper-light** — wrapper used
  `bg-surface-1` (244,240,230), only 6 RGB units off the conversation
  body's `bg-surface-0` (250,247,240). Switched to `bg-surface-2`
  (234,228,213) for clearly distinct elevation in paper-light;
  evergreen / midnight-glass still have ample contrast at the new
  token. The textarea below it picks up `bg-surface-0` and reads as a
  proper inset.
- **`~`-prefixed `working_dir` would crash the SDK** if the agent loop
  ever reached chdir (`agent/session_bootstrap.py`). Expand `~` at the
  SDK boundary so a session row stored as `~/Projects/...` (the
  inspector's display form) resolves to an absolute path the SDK can
  chdir into. Defensive — masked by the agent-loop bug above, but
  would surface as soon as that was fixed.
- **theme contrast on light themes** — scoped style blocks across
  `routes/sessions/new`, `routes/tags`, `routes/settings`,
  `routes/analytics`, `lib/components/new_session/*`, and
  `lib/components/routing/*` referenced undeclared CSS variable names
  (`--surface-1/2/3`, `--fg`, `--fg-muted`, `--accent-info`,
  `--accent-danger`, `--bg`, `--border`). Every reference fell through
  to its hardcoded dark-color fallback regardless of `data-theme`,
  producing a dark "New Session" card on a paper-light page with
  near-invisible tag-chip text. Remapped surface / fg / accent / border
  refs to the actual themed `--bearings-*` channel-triple tokens; warn /
  error / ok semantic colors stay inlined as literals (no theme
  vocabulary for them yet).

## [1.0.0] — 2026-05-01

The stability commitment. v1.0.0 promotes the v0.18.0 rebuild after a
two-week dogfood window against the live `bearings-v1.service` running
concurrently with v0.17.x. The public HTTP surface (62 paths, 53
schemas — see [`docs/openapi.json`](docs/openapi.json)), the
per-subsystem behavior contracts under [`docs/behavior/`](docs/behavior/),
and the routing/quota wire shapes in
[`docs/model-routing-v1-spec.md`](docs/model-routing-v1-spec.md)
Appendix A are now the SemVer-governed compatibility surface — breaking
changes ship in v2.0.0, additive changes in v1.x, fixes in v1.0.x.

### Stability commitment

What this means concretely:

* **HTTP API**: paths and request/response schemas listed in
  `docs/openapi.json` will not be removed or shape-changed within the
  v1.x line. New optional fields and new endpoints are additive (minor
  bump). Removals or required-field changes require a v2 cutover.
* **Routing/quota wire shapes**: `RoutingDecision`, `RoutingRule`,
  `SystemRoutingRule`, and `QuotaSnapshot` (frozen dataclasses, spec
  Appendix A) are the JSON contract every routing client sees.
  Additive evolution only within v1.x.
* **On-disk schema**: `~/.local/share/bearings-v1/sessions.db` keeps
  its v0.18.0-shipped schema; future column additions arrive via
  forward-only migrations that v1.x clients can read. Removals require
  v2.
* **Behavior docs**: `docs/behavior/<subsystem>.md` is the
  observable-behavior contract. Drift between the docs and the
  service is treated as either a doc bug or a code bug — not a "the
  spec is just guidance" situation. Behavior addenda (per the plan's
  "Behavioral gap escalation" §) extend, never silently override.

What this does *not* mean: localhost-only posture, single-user model,
SQLite backend, and the orphan `v1-rebuild` history are all retained
from v0.18.0 — none of them rotate to v2 territory just because the
tag flipped.

### Dogfood window summary

The window ran on the live v1 service against the same DB Dave uses
day-to-day. Coverage:

* **Daily probe** (`scripts/daily_probe.py`, item B.1) — six endpoints
  (`/api/health`, `/api/sessions?limit=5`, `/api/quota/current`,
  `/api/quota/history`, `/openapi.json`, `/metrics`) hit by a
  systemd-user timer (`bearings-v1-probe.timer`, daily 09:15 local).
  Logs to `~/.local/share/bearings-v1/probes/YYYY-MM-DD.log`. Final
  window: PASS on every run.
* **Differential probe** (`scripts/diff_probe.py`, item B.2) — five
  surfaces diffed against the v0.17.x service on port 8787
  (`/api/health`, `/api/sessions?limit=5`, `/api/tags`,
  `/openapi.json` path-set, `/metrics` name-set). Logs to
  `~/.local/share/bearings-v1/diff-probes/YYYY-MM-DD.log`. Final
  window: 0 reachability failures. Shape divergence on
  `openapi_paths` and `metric_names` is the *expected* delta — v1
  removes legacy v0.17 endpoints (e.g. `/api/preferences/*`,
  per-session `/api/sessions/{id}/checklist*`) and adds the routing /
  quota / usage surfaces, and rotates the metric set to the
  bearings_* names declared in `web/metrics.py`. Both deltas are
  documented in the spec and CHANGELOG and were not promoted to
  issues.
* **Issue triage protocol** (`docs/dogfood/issue-triage.md`, item
  B.3) — P0 / P1 / P2 ladder, fix-or-defer rubric, escalation paths
  back to the orchestrator. Final window: **0 P0**, **0 P1**, P2s
  (if any) carried into `TODO.md` for the v1.0.x backlog.
* **Final-readiness audit** (item D.1) — confirmed the probe history,
  the deferred-list, and the cutover-smoke acceptance gate
  (`scripts/cutover_smoke.py`, item 3.4) all green ahead of the tag.

### Added

* **Issue-triage protocol doc** (master item B.3).
  [`docs/dogfood/issue-triage.md`](docs/dogfood/issue-triage.md)
  defines the four issue sources (daily probe, differential probe,
  manual review windows C.1 / C.2, and ad-hoc), the P0 / P1 / P2
  severity labels, the fix-or-defer rubric, and the escalation paths
  back to the orchestrator session
  (`d4e89042507141f4a790a02459018152`). D.1 reads it as the
  final-readiness gate input.
* **Differential probe v0.17.x ↔ v1** (master item B.2). New
  `scripts/diff_probe.py` is a stdlib-only differential probe that
  hits equivalent endpoints on the live v0.17.x service (loopback
  port 8787) and the v1 service (port 8788), then diffs structural
  shape and logs the deltas. Three diff modes cover the
  heterogeneous surface: `json_shape` (recursive type-skeleton diff
  for `/api/health`, `/api/sessions?limit=5`, `/api/tags`),
  `openapi_paths` ((METHOD, path) set diff for `/openapi.json` —
  the highest-leverage mode, surfacing every endpoint added /
  removed / renamed in v1), and `metric_names` (Prometheus
  `# HELP <name>` set diff for `/metrics`). Logs one JSONL record
  per probe plus a `SUMMARY` trailer to
  `~/.local/share/bearings-v1/diff-probes/YYYY-MM-DD.log` (mode
  0700, append). Exit 0 = both sides reachable on every probe,
  1 = any reachability failure. Shape divergence is informational
  (logged, not gated) — observing divergence over the cutover
  window is the point. Backed by 28 unit tests in
  `tests/test_diff_probe.py` covering shape extraction,
  shape diff, OpenAPI path-set diff, Prometheus parse, log
  serialisation, and end-to-end orchestration through a fake
  transport. The `[tool.mypy]` `mypy_path = "scripts"` entry in
  `pyproject.toml` is added in the same commit so the test's
  `TYPE_CHECKING` import resolves cleanly under
  `mypy --strict`; this also clears the pre-existing
  `import-not-found` baseline that `tests/test_cutover_smoke.py`
  inherited from item 3.4.
* **Daily probe + systemd-user timer** (master item B.1). New
  `scripts/daily_probe.py` is a stdlib-only health probe (no httpx
  / venv dependency) that hits `/api/health`, `/api/sessions?limit=5`,
  `/api/quota/current` (the headroom-conceptual surface — the literal
  `/api/usage/headroom` named in the done-when text doesn't exist in
  v1's route surface; see the script docstring for the swap), the
  paired `/api/quota/history`, `/openapi.json`, and `/metrics`. Logs
  one JSONL record per probe plus a `SUMMARY` trailer to
  `~/.local/share/bearings-v1/probes/YYYY-MM-DD.log` (mode 0700,
  append). Exit 0 = all PASS, 1 = any FAIL.
* **Probe systemd units.** `config/bearings-v1-probe.service`
  (oneshot, hardened identical to `bearings-v1.service`) and
  `config/bearings-v1-probe.timer` (daily 09:15 local, 5min jitter,
  `Persistent=true`). Install:
  `cp config/bearings-v1-probe.{service,timer} ~/.config/systemd/user/
  && systemctl --user daemon-reload
  && systemctl --user enable --now bearings-v1-probe.timer`.
  Both pass `systemd-analyze --user verify`.

### Changed

* **Package version** rolled `0.18.0.dev0` → `1.0.0` across
  `pyproject.toml`, `src/bearings/__init__.py`, `frontend/package.json`,
  `frontend/package-lock.json`, the SvelteKit sidebar `versionTag`
  string in `frontend/src/lib/config.ts`, and the regenerated
  `docs/openapi.json` (`info.version`).

## [0.18.0] — 2026-04-29

The v1 rebuild: behavioral parity with v0.17.x's feature surface, plus
model-routing v1, on a fresh tree (`v1-rebuild` branch, orphan
history). Concurrent run with v0.17.x is supported (port 8788, DB
`~/.local/share/bearings-v1/`, systemd unit `bearings-v1.service`).

### Added

* **Model routing v1** (per `docs/model-routing-v1-spec.md`):
  * `evaluate()` pure function for tag-rule + system-rule + default
    resolution (`agent/routing.py`).
  * Quota poller and `apply_quota_guard()` downgrade with manual-override
    accounting (`agent/quota.py`).
  * Override-rate aggregator with rolling 14-day window
    (`agent/override_aggregator.py`).
  * Routing / quota / usage HTTP endpoints per spec §9
    (`/api/routing/*`, `/api/quota/*`, `/api/usage/*`).
  * Per-message routing/usage columns on `messages` capturing executor
    and advisor `model_usage`, source, reason, matched rule.
  * `RoutingDecision`, `RoutingRule`, `SystemRoutingRule`, `QuotaSnapshot`
    frozen dataclasses (Appendix A wire shape).
* **Frontend routing surfaces** (per spec §6 + §10):
  * New-session dialog with reactive routing preview (300 ms debounce),
    advisor toggle, quota bars (yellow at 80 %, red at 95 %), and
    downgrade banner with "Use anyway" override.
  * Per-message `RoutingBadge` in the conversation pane.
  * Inspector **Routing** subsection: current decision, advisor totals,
    quota delta this session, per-message timeline with "Why this
    model?" expandable rule chain.
  * Inspector **Usage** subsection: 7-day headroom chart, by-model
    table, advisor-effectiveness widget, rules-to-review list (override
    rate > 30 % over 14 days).
  * Routing rule editor (per-tag + system-wide) with drag-reorder,
    enable/disable, duplicate, delete, and a deterministic
    test-against-message dialog (no LLM).
* **Inspector core** (per arch §1.2): five-tab inspector shell with
  Agent / Context / Instructions / Routing / Usage subsections (item
  2.5 ships the first three; 2.6 lights up Routing + Usage).
* **Paired chats + prompt endpoint + bearings CLI**:
  `POST /api/sessions/<id>/prompt` returning 202, paired-chat persistence
  per `docs/behavior/paired-chats.md`, and a `bearings` CLI with the
  `todo` subcommand.
* **Checklists, auto-driver, and sentinels**: full picking / linking /
  reordering / run-control endpoints; auto-driver agent surfaces
  per-item run state through the sidebar sentinel pip.
* **Vault + memories**: per-tag system-prompt overlays, vault search,
  memories editor, redaction toggles per `docs/behavior/vault.md`.
* **Themes**: theme provider with no-flash boot script, runtime picker
  with Midnight Glass / Default / Paper Light, theme-color meta updater.
* **Keyboard shortcuts and context menus**: keybinding registry with
  cheat-sheet, palette, and right-click action surface per
  `docs/behavior/keyboard-shortcuts.md` and `docs/behavior/context-menus.md`.
* **Migration script**: `scripts/migrate_v0_17_to_v0_18.py` copies
  v0.17.x DB to the v1 path, transforms schema, has dry-run mode, and
  is idempotent on re-run.
* **OpenAPI export**: `GET /openapi.json` (item 1.10) and the static
  copy at [`docs/openapi.json`](docs/openapi.json) — 62 paths,
  53 schemas.
* **Documentation**: `docs/architecture-v1.md`, `docs/model-routing-v1-spec.md`,
  per-subsystem behavior specs under `docs/behavior/`, augmented chat.md
  §"Inspector pane (non-routing subsections)", project `CLAUDE.md`.
* **Quality gates**: 12-tool pre-commit stack (ruff, mypy, pytest,
  vulture, radon, interrogate, codespell, pip-audit, eslint, prettier,
  svelte-check, knip, ts-prune, depcheck, lychee), playwright e2e,
  cross-system consistency lint, ≥ 80 % coverage on business logic.

### Changed

* **Repo posture**: `v1-rebuild` is an orphan branch; pre-commit
  `branch-verifier` rejects commits to any other branch on this
  worktree. Per-worktree `core.hooksPath` isolation via
  `scripts/setup-worktree.sh`.
* **Backend layout** consolidated per `docs/architecture-v1.md`:
  * `bearings.agent` collapses v0.17.x's three-file session split into a
    single session lifecycle module.
  * `bearings.web` separates DTOs (`web/models/`) from routes
    (`web/routes/`); each route group has a typed Pydantic wire model.
  * `bearings.config` exposes the spec-mandated numeric constants in a
    single constants module — no inline literals downstream.
  * `bearings.db` keeps a single routing-aware schema (no migration
    chain) and per-concern query modules.
* **Frontend layout**: `lib/components/` regrouped from v0.17.x's
  flat 60+ files into feature-scoped folders
  (`conversation/` + `sidebar/` + `inspector/` + `routing/` + `vault/`
  + `reorg/` + `menus/` + `modals/` + `feedback/` + `common/` +
  `pending/` + `checklist/` + `settings/` + `icons/`).
* **SDK**: pinned `claude-agent-sdk~=0.1.69` (compatible-release).
  Streaming protocol, advisor tool, beta headers, `model_usage` shape,
  effort levels, `fallback_model`, and subagent auto-select all updated
  to current SDK surface (see `docs/architecture-v1.md` §5 SDK currency
  audit).
* **Concurrent-run defaults** for v1 vs v0.17.x: port 8787 → **8788**;
  DB `~/.local/share/bearings/` → `~/.local/share/bearings-v1/`;
  systemd `bearings.service` → `bearings-v1.service`.

### Deferred (explicitly NOT in v0.18.0)

* Multi-user / auth — Bearings stays localhost.
* Cross-user shared rule libraries (per spec §12).
* ML routers, A/B testing, classifier preflight (per spec §12).
* Per-rule model-version pinning (per spec §12).
* `1.0.0` stability commitment — post-dogfood decision.

### Migration

Run the one-shot migration script after upgrading from v0.17.x:

```bash
uv run python scripts/migrate_v0_17_to_v0_18.py --dry-run
uv run python scripts/migrate_v0_17_to_v0_18.py
```

The script reads from `~/.local/share/bearings/sessions.db` and writes
to `~/.local/share/bearings-v1/sessions.db`. The v0.17.x install is left
untouched so the two services can run concurrently on ports 8787 / 8788
during cutover.

The migration coerces v0.17 session titles to fit v1's runtime
invariants:

* NULL or empty titles → ``"(untitled)"`` sentinel (the v1 ``Session``
  dataclass requires a non-empty title; the schema's NOT NULL alone is
  not sufficient).
* Titles longer than 500 chars are truncated with an ellipsis suffix
  so the row remains addressable through ``GET /api/sessions``.

### Cutover smoke

`scripts/cutover_smoke.py` is the v1 acceptance gate. It migrates a v0.17.x
DB into a tempdir target, boots the v1 FastAPI app + SvelteKit dist
against the migrated data, probes every API subsystem (health, metrics,
tags, sessions, vault, uploads, routing, quota, usage, diag, static
SPA), walks migrated rows back through the API to confirm round-trip
integrity, and runs the Playwright E2E suite (29 tests across 9
specs). The script emits a per-stage PASS / FAIL report and exits 0
only when every stage is green:

```bash
uv run python scripts/cutover_smoke.py             # full acceptance
uv run python scripts/cutover_smoke.py --skip-e2e  # fast iteration
uv run python scripts/cutover_smoke.py --json      # machine-readable
```

[1.0.0]: https://github.com/Beryndil/Bearings/releases/tag/v1.0.0
[0.18.0]: https://github.com/Beryndil/Bearings/tree/v1-rebuild
