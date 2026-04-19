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

## v0.1.4 — shipped

- [x] Shiki syntax highlighting in conversation code blocks.
- [x] Tool-call final duration after `tool_call_end`.
- [x] `localStorage` persistence for selected session.
- [x] WebSocket auto-reconnect with exponential backoff.
- [x] Inline two-click delete confirmation.

## v0.1.5 — shipped

- [x] Prometheus collectors + instrumentation for sessions, messages,
  tool calls, WS events and active connections.
- [x] `/api/history/export` + `/api/history/daily/{date}` routes.
- [x] CI frontend artifact check + `npm run check` gate.

## v0.1.6 — shipped

- [x] `/api/sessions/{id}/tool_calls` history route.
- [x] Frontend `listToolCalls` + `ToolCall` type.
- [x] Inspector renders persisted tool calls on session load.

## v0.1.7 — shipped

- [x] `MessageStart` event + `tool_calls.message_id` backfill via the
  new `attach_tool_calls_to_message` store helper.
- [x] Frontend `AgentEvent` union picks up `MessageStartEvent`.

## v0.1.8 — shipped

- [x] `max_budget_usd` per-session cap (column, API, ClaudeAgentOptions
  wiring, frontend form field).
- [x] `/api/history/export?from=&to=` range filter.

## v0.1.9 — next slice

- [ ] Frontend unit tests (vitest + @testing-library/svelte).
- [ ] Messages-endpoint pagination (limit + cursor) once conversations
  grow long.
- [ ] Show `max_budget_usd` in the Conversation header (+ a running
  cost once the SDK `ResultMessage.total_cost_usd` is surfaced).
- [ ] Graceful WS shutdown signal so `twrminal serve` under systemd
  stops cleanly with in-flight streams.
- [ ] Auth gate: enable `auth.enabled` path (currently no-op).

## v0.1.7+

- [ ] Auth gate: enable `auth.enabled` path (currently no-op).
- [ ] Kill switch / graceful shutdown signal in the WS handler so
  `twrminal serve` under systemd stops cleanly with in-flight streams.
- [ ] Rate-limit or soft-cap `max_budget_usd` per session via
  `ClaudeAgentOptions` so an agent loop doesn't burn unbounded tokens.

## Decisions pending

- [x] GitHub org for remote push: `Beryndil/Twrminal`.
- [ ] Partial-message semantics: confirm `include_partial_messages=True`
  emits token deltas as expected on first live agent run.
