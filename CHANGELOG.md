# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
