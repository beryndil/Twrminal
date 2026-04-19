# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.18] - 2026-04-19

### Added

- `{"type":"stop"}` frame on the agent WebSocket interrupts an
  in-flight stream. The server breaks out of `agent.stream`,
  synthesises a `MessageComplete`, and persists whatever text/tool
  calls streamed so far — the partial assistant message is not lost.
- Frontend `agent.stop()` sends the stop frame; Conversation header
  shows a red **Stop** button next to the connection badge while
  `conversation.streamingActive` is true.

### Changed

- WS handler refactor: a dedicated reader task drains inbound frames
  into an `asyncio.Queue`; the outer prompt loop pulls from it, and
  the streaming loop peeks non-blockingly between events. Keeps a
  single WS reader (no racing `receive_json` calls), lets any future
  mid-stream control frame follow the same pattern.
- Assistant-turn persistence extracted into a `_persist_assistant_turn`
  helper so natural-end and stop paths both write through the same
  code.

## [0.1.17] - 2026-04-19

### Added

- `SessionEdit.svelte` modal wired behind a ✎ button in the Conversation
  header. Edits `title` + `max_budget_usd` on an existing session via
  the v0.1.16 PATCH route. Cap is no longer create-time-only.
- `twrminal send --format=pretty` — human-readable output:
  - tokens stream inline with a flush,
  - `thinking` / `message_start` frames suppressed,
  - tool calls render as `↳ tool Name (input)` / `← ok: output` or
    `← error: message`,
  - each turn ends with a separator line + cost badge.
  Default `--format=json` stays one-event-per-line for scripting.

## [0.1.16] - 2026-04-19

### Added

- `PATCH /api/sessions/{id}` with `SessionUpdate` body — partial
  updates for `title` and `max_budget_usd`; unset fields leave the
  column untouched, explicit null clears. `updated_at` bumps on any
  real change. Returns 404 if the session is gone.
- `store.update_session(conn, session_id, fields)` — whitelists
  `title` / `max_budget_usd`, builds the SET clause dynamically.
- Frontend `api.updateSession(id, patch)` + `sessions.update(id, patch)`
  store method.
- Inline rename in the sidebar: double-click a session title →
  input; Enter / blur saves via PATCH, Esc cancels. Conversation
  header reflects the new title through normal reactivity.

## [0.1.15] - 2026-04-19

### Added

- `stores/prefs.svelte.ts` — reactive preferences persisted in
  `localStorage` (`defaultModel`, `defaultWorkingDir`, `authToken`).
- `components/Settings.svelte` — modal accessed via a ⚙ button in the
  Sessions panel header. Edits all three prefs + also lifts the auth
  gate when a token is entered here while the gate is up.
- SessionList new-session form pre-fills `working_dir` and `model`
  from saved prefs each time it opens; user edits within the open
  form still override. Create also falls back to the pref default if
  the user clears the field.

## [0.1.14] - 2026-04-19

### Added

- `messages.thinking` column (migration 0004). WS handler accumulates
  a `thinking_buf` alongside `buf` during the turn and passes the
  joined string (or `None` if empty) to `insert_message` at
  `MessageComplete`. Persisted thinking survives page reloads.
- `MessageOut.thinking` + frontend `Message.thinking` types.
- Conversation pane renders a `<details>` "thinking" block (closed by
  default) on any persisted message that has stored reasoning.

### Fixed

- `test_metrics.py::test_ws_counters_update` flake: the
  `messages_persisted` assistant counter is incremented in the
  MessageComplete branch after the last send, which can be truncated
  by TestClient context exit. Now polls the counter inside the WS
  context before asserting, matching the pattern used elsewhere.

## [0.1.13] - 2026-04-19

### Added

- `Thinking(type="thinking", session_id, text)` event. `AgentSession`
  now translates `ThinkingBlock.thinking` (emitted by the SDK when
  extended thinking is on) into a `Thinking` frame instead of silently
  dropping it.
- Frontend `AgentEvent` union picks up `ThinkingEvent`; conversation
  store accumulates `streamingThinking` alongside `streamingText`.
- Streaming pane shows a `thinking` `<details>` block (open by default)
  above the token output when the agent is reasoning aloud.

## [0.1.12] - 2026-04-19

### Added

- `AuthGate.svelte` modal. When `/api/health` reports
  `auth: "required"` and no token is stored (or the stored token is
  rejected on any API 401 / WS 4401), the modal blocks the UI with a
  password-masked input. Save → token persists in
  `localStorage["twrminal:token"]` → boot proceeds.
- `stores/auth.svelte.ts` tracks `status`
  (`checking`/`open`/`ok`/`required`/`invalid`/`error`). `api.ts`
  exports `onAuthFailure(cb)` so the store flips itself to `invalid`
  on 401 without a circular import. `agent.svelte.ts` flips the same
  way on WS close 4401 and aborts reconnect (no infinite loop).
- Boot flow moved from `SessionList.onMount` to `+page.svelte`: auth
  check first, then `sessions.refresh` + auto-connect only after the
  gate clears.
- Budget pressure coloring in the Conversation header: amber at ≥80%
  of `max_budget_usd`, rose at ≥100%. Sessions with no cap render
  unchanged.

### Fixed

- `SessionList` budget parsing now handles `<input type="number">`
  binding variants (number / empty string / null) instead of assuming
  a string; previously the new-session form submitted
  `max_budget_usd: null` when the field had a value.

## [0.1.11] - 2026-04-19

### Added

- Opt-in bearer-token auth. Set `auth.enabled = true` +
  `auth.token = "..."` in `config.toml`:
  - `/api/sessions*` and `/api/history*` require
    `Authorization: Bearer <token>` (new `api/auth.py` dependency).
  - `/ws/sessions/{id}` requires `?token=<token>` (browsers can't set
    WS headers); closes with app code `4401 Unauthorized` on mismatch.
  - `/api/health` and `/metrics` stay open so monitoring can probe
    without creds.
  - Enabling auth with an empty token fails the first request with
    500 — fail closed rather than silently ship with no protection.
- `GET /api/health` now returns `{auth: "required"|"disabled", version}`
  so clients can tell whether they need to supply a token.
- `twrminal send --token <t>` flag; CLI also auto-pulls from
  `cfg.auth.token` when `auth.enabled`.
- Frontend `api.ts` reads `localStorage["twrminal:token"]` and injects
  `Authorization: Bearer` on fetches + `?token=...` on the WS URL. UI
  to enter the token lands in a later slice; for now set it via devtools
  (`localStorage.setItem('twrminal:token', '...')`).

## [0.1.10] - 2026-04-19

### Added

- `MessageComplete.cost_usd` — SDK-reported turn cost
  (`ResultMessage.total_cost_usd`) surfaced on the wire. `AgentSession`
  captures it before the `break` on ResultMessage.
- `sessions.total_cost_usd` column (migration 0003, `REAL NOT NULL
  DEFAULT 0`). `store.add_session_cost` accumulates it per turn; WS
  handler calls it on MessageComplete when cost is non-null.
- `SessionOut.total_cost_usd` on the API.
- Frontend `Session.total_cost_usd` + `MessageCompleteEvent.cost_usd`.
- Conversation store tracks `totalCost`: seeded from the DB row on load,
  incremented locally per MessageComplete. Conversation header shows
  `spent $Y.YYYY` and, when a cap is set, `/ $X.XX`.

## [0.1.9] - 2026-04-19

### Added

- Graceful WebSocket shutdown: FastAPI lifespan tracks active agent
  sockets in `app.state.active_ws`; on shutdown, each is closed with
  code `1001 Going Away` before the DB connection is torn down.
  Clients see a clean disconnect (and hit the v0.1.4 reconnect path)
  instead of `ConnectionReset` on `systemctl restart`.
- Conversation header shows `budget $X.XX` next to model + working_dir
  when the session has a `max_budget_usd` cap set; otherwise omitted.

## [0.1.8] - 2026-04-19

### Added

- `sessions.max_budget_usd` column (migration 0002) — optional per-session
  cap in USD. `POST /api/sessions` accepts it via body; `AgentSession`
  passes it to `ClaudeAgentOptions.max_budget_usd` when non-null. Stops a
  runaway agent loop from burning unbounded tokens.
- Frontend: "Budget USD (optional)" field in the new-session form,
  persisted end-to-end. `Session` / `SessionCreate` TS types pick up the
  field.
- `/api/history/export?from=YYYY-MM-DD&to=YYYY-MM-DD` — either/both
  bounds supported; bad dates return 400. Store `list_all_*` helpers
  swap the old single `date_prefix` arg for `date_from` + `date_to`;
  `/history/daily/{date}` now passes the same date to both bounds.

## [0.1.7] - 2026-04-19

### Added

- New `MessageStart(session_id, message_id)` event emitted by
  `AgentSession.stream` as the first frame of each turn. The same
  `message_id` is reused for the turn's `MessageComplete`, giving the
  wire protocol a stable id for the assistant message before its
  content is known.
- `store.attach_tool_calls_to_message(message_id, tool_call_ids)` —
  backfills `tool_calls.message_id` after the assistant message row
  exists. The WS handler collects tool-call ids emitted during the
  turn and calls this helper at `MessageComplete`.
- `insert_message` accepts an optional `id` so the WS handler can
  persist the assistant row with the `MessageStart.message_id` — the
  same id the client already received over the wire.
- Frontend `AgentEvent` union gains `MessageStartEvent`; conversation
  store handles it as a no-op (rendering continues to hinge on
  `MessageComplete`).

### Why

Tool-call rows were landing with `message_id = NULL`. Attempting to
insert the link at `ToolCallStart` time tripped the FK (no message
row yet). The `MessageStart` → collect → backfill flow keeps the FK
enforced while still linking tool calls back to their assistant turn.

## [0.1.6] - 2026-04-18

### Added

- `GET /api/sessions/{session_id}/tool_calls` — list persisted tool-call
  rows, oldest-first. 404 on unknown session.
- `ToolCallOut` Pydantic model (matches DB columns 1:1, `input` stays as
  the stored JSON string).
- Frontend `api.ts` gains `ToolCall` type + `listToolCalls()` helper.
- `conversation.svelte.ts` now hydrates the `toolCalls` array from
  `/api/sessions/{id}/tool_calls` on session load (parallel with
  `listMessages`), converting ISO timestamps → ms and the stored JSON
  input string → `Record<string, unknown>`. Reloading a session now
  shows its tool-call history in the Inspector instead of an empty
  panel; live WS events continue to append/update on top.

## [0.1.5] - 2026-04-18

### Added

- Prometheus collectors in a dedicated `twrminal/metrics.py` using a
  private `CollectorRegistry`. Metrics exposed on `/metrics`:
  - `twrminal_sessions_created_total`
  - `twrminal_messages_persisted_total{role}`
  - `twrminal_tool_calls_started_total`
  - `twrminal_tool_calls_finished_total{ok}`
  - `twrminal_ws_active_connections` (gauge)
  - `twrminal_ws_events_sent_total{type}`
  Instrumentation lives at the route / WS-handler boundary; store.py
  stays side-effect-free.
- `GET /api/history/export` — full `{sessions, messages, tool_calls}`
  dump.
- `GET /api/history/daily/{YYYY-MM-DD}` — same shape filtered to one
  calendar day; 400 on bad date.
- `store.list_all_sessions`, `list_all_messages`, `list_all_tool_calls`
  with optional `date_prefix` filter.
- CI job verifies `src/twrminal/web/dist/index.html` + `_app/` exist
  after `npm run build` so a broken sync-dist step fails the build.
- CI frontend job now also runs `npm run check` (svelte-check) gating
  type errors in components.

## [0.1.4] - 2026-04-18

### Added

- Shiki syntax highlighting in conversation markdown code blocks
  (python, typescript, bash, json, yaml, rust, go, and more); wired via a
  custom marked renderer. Pre-initialized at module load via top-level
  await so `renderMarkdown` stays synchronous.
- Tool-call finish time: `LiveToolCall.finishedAt` set on
  `tool_call_end`; Inspector now shows final duration ("123ms" / "2.4s")
  after completion instead of ticking "running".
- Session selection persists in `localStorage`
  (`twrminal:selectedSessionId`); auto-connects on boot if the stored id
  still exists in the session list.
- WebSocket auto-reconnect with exponential backoff (1s/2s/4s/8s/…,
  capped at 30s); Conversation header shows `retrying in Ns`. Triggers
  on abnormal closes, skipped for `4404 session not found` and normal
  `1000` close. Resets on successful open; cancelled on explicit
  `agent.close()`.
- Inline two-click delete confirmation: first click on ✕ swaps to
  "Confirm?" for 3 seconds; second click deletes. No more `window.confirm`
  dialog — UI is fully scriptable.

### Changed

- `vite.config.ts` build target bumped to `es2022` so top-level await in
  `render.ts` (shiki WASM init) compiles cleanly.
- `SessionList` confirm state switched to `$state` object property
  (`confirm.id`) rather than a bare `$state` variable; event-handler
  closures see fresh values reliably.

## [0.1.3] - 2026-04-18

### Added

- Frontend three-panel shell: `SessionList`, `Conversation`, `Inspector`
  Svelte components wired through `+page.svelte`.
- `frontend/src/lib/api.ts` — typed `AgentEvent` discriminated union, session
  CRUD helpers (`listSessions`, `createSession`, `deleteSession`,
  `getSession`, `listMessages`).
- Svelte 5 runes-based stores: `sessions.svelte.ts` (list, selected id,
  CRUD) and `conversation.svelte.ts` (historical messages, in-flight
  streaming buffer, live tool calls).
- `agent.svelte.ts` — WebSocket connection manager dispatching events
  into the conversation store, with typed `ConnectionState`.
- `render.ts` — `marked`-backed Markdown → HTML with GFM + line breaks.
- `@tailwindcss/typography` plugin for markdown styling (`prose
  prose-invert`).

### Changed

- `frontend/package.json` version bumped to `0.1.3` (tracks Python pkg).

## [0.1.2] - 2026-04-18

### Added

- `GET /api/sessions/{session_id}/messages` — history playback endpoint
  returning `MessageOut[]`.
- `twrminal send --session <id> <prompt>` — CLI subcommand opens a WebSocket
  to a running server, streams events to stdout as JSON lines, exits 0 on
  `message_complete`, 1 on `error`.
- `ToolCallEnd` event: `AgentSession.stream` now translates
  `ToolResultBlock` (carried on `UserMessage.content`) into a `ToolCallEnd`
  event with `ok`/`output`/`error` derived from `is_error` + `content`.
- Tool-call persistence: `store.insert_tool_call_start`, `finish_tool_call`,
  `list_tool_calls`. WS handler writes rows as events stream.

## [0.1.1] - 2026-04-18

### Added

- DB CRUD in `db/store.py`: `create_session`, `list_sessions`, `get_session`,
  `delete_session`, `insert_message`, `list_messages`.
- `api/models.py` with `SessionCreate`, `SessionOut`, `MessageOut` DTOs.
- Real session CRUD routes at `/api/sessions` (`GET`, `POST`, `GET/{id}`,
  `DELETE/{id}`), replacing the 501 stubs.
- `AgentSession.stream()` wired to `claude-agent-sdk`'s `ClaudeSDKClient`;
  translates `AssistantMessage` text/tool-use blocks into `Token` /
  `ToolCallStart` / `MessageComplete` / `ErrorEvent`.
- `/ws/sessions/{id}` WebSocket bridge: accepts a `{"type":"prompt","content":"..."}`
  frame, streams events back, and persists user + assistant messages.
- FastAPI `lifespan` wiring `init_db()` at startup → `app.state.db`.

### Changed

- `init_db()` now sets `conn.row_factory = aiosqlite.Row` so CRUD can return
  column-keyed dicts.

## [0.1.0] - 2026-04-18

### Added

- Initial scaffold: FastAPI backend, SvelteKit frontend shell, SQLite/aiosqlite
  persistence layer, CLI entry point, systemd user unit, CI workflow.
- Health endpoint and placeholder REST/WebSocket routes (bodies return 501 until
  backing logic lands).
