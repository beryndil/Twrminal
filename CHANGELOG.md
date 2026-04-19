# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
