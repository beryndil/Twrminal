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

## v0.1.2 — next slice

- [ ] Frontend three-panel shell (`frontend/src/routes/+page.svelte`) —
  wire sessions list / conversation / inspector to the real backend.
- [ ] `frontend/src/lib/api.ts` — event type definitions + `listSessions`,
  `createSession`, `deleteSession` helpers; WS event parsing.
- [ ] `ToolCallEnd` event: correlate with next `AssistantMessage` turn or
  SDK tool-result block and emit from `AgentSession.stream`.
- [ ] Tool-call persistence CRUD in `store.py` and WS handler.
- [ ] Messages API: `GET /api/sessions/{id}/messages` for history playback.
- [ ] `cli.py send` subcommand — one-shot prompt against a session from the CLI.

## v0.1.3+

- [ ] Prometheus collectors for `/metrics` route (currently empty registry).
- [ ] `routes_history.py` — implement `/api/history/export` and
  `/api/history/daily/{date}`.
- [ ] CI frontend build artifact test — verify `npm run build` actually
  produces files under `src/twrminal/web/dist/`.
- [ ] Auth gate: enable `auth.enabled` path (currently no-op).

## Decisions pending

- [x] GitHub org for remote push: `Beryndil/Twrminal` (already configured as
  `origin`).
- [ ] Partial-message semantics: confirm `include_partial_messages=True`
  emits token deltas as expected on first live agent run.
