# Twrminal — Open Tasks

## Scaffold reference

Full scaffold plan: `~/.claude/plans/here-are-the-architectural-ticklish-puppy.md`.
v0.1.1 slice plan: `~/.claude/plans/hazy-hatching-honey.md`.

## v0.1.1 — shipped

- [x] `AgentSession` wired to `claude-agent-sdk`.
- [x] WebSocket streaming in `src/twrminal/api/ws_agent.py`.
- [x] DB CRUD in `src/twrminal/db/store.py` (sessions + messages).
- [x] Real `/api/sessions` routes.
- [x] `api/models.py` Pydantic DTOs.
- [x] Lifespan wiring `init_db` → `app.state.db`.

## v0.1.2 — shipped

- [x] `GET /api/sessions/{id}/messages` history route.
- [x] `twrminal send` CLI subcommand.
- [x] `ToolCallEnd` event via `ToolResultBlock` translation.
- [x] Tool-call persistence (store CRUD + WS handler writes).

## v0.1.3 — shipped

- [x] Frontend three-panel shell wired end-to-end.
- [x] `api.ts` with `AgentEvent` union + CRUD helpers.
- [x] Svelte 5 stores for sessions + conversation + WS agent.
- [x] Markdown rendering (marked + typography plugin).
- [x] Browser-exercised: create session → WS connects → UI shows connected.

## v0.1.4 — shipped

- [x] Shiki syntax highlighting in conversation code blocks.
- [x] Tool-call final duration after `tool_call_end`.
- [x] `localStorage` persistence for selected session + auto-connect on boot.
- [x] WebSocket auto-reconnect with exponential backoff.
- [x] Inline two-click delete confirmation (no `window.confirm`).

## v0.1.5 — next slice

- [ ] Prometheus collectors for `/metrics` route (currently empty registry).
  Counters: sessions_created, messages_persisted, tool_calls_started; gauges
  for active WS connections.
- [ ] `routes_history.py` — implement `/api/history/export` (JSON dump of
  all sessions + messages) and `/api/history/daily/{date}`.
- [ ] CI frontend build artifact test — add a step that verifies
  `src/twrminal/web/dist/index.html` exists after `npm run build`.
- [ ] Wire `message_id` on tool_calls rows (currently always NULL on
  insert; backfill at `MessageComplete` time).

## v0.1.6+

- [ ] Frontend unit tests (vitest + @testing-library/svelte).
- [ ] Auth gate: enable `auth.enabled` path (currently no-op).
- [ ] Messages-endpoint pagination (limit + cursor) once conversations
  grow long.
- [ ] Render tool-call history in Inspector for loaded sessions (currently
  only live WS events populate it).

## Decisions pending

- [x] GitHub org for remote push: `Beryndil/Twrminal` (configured as
  `origin`).
- [ ] Partial-message semantics: confirm `include_partial_messages=True`
  emits token deltas as expected on first live agent run.
