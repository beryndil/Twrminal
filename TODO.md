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

## v0.1.3 — next slice (frontend)

- [ ] Frontend three-panel shell (`frontend/src/routes/+page.svelte`) —
  wire sessions list / conversation / inspector to the real backend.
- [ ] `frontend/src/lib/api.ts` — event type definitions, session CRUD
  helpers (`listSessions`, `createSession`, `deleteSession`,
  `listMessages`), WS event parsing with discriminated union.
- [ ] Token streaming renderer (markdown + shiki for code blocks).
- [ ] Tool-call inspector panel showing live tool_call_start/_end state.
- [ ] Exercise the full UI in a browser (per project CLAUDE.md) before
  shipping — dev server + golden-path + edge cases.

## v0.1.4+

- [ ] Prometheus collectors for `/metrics` route (currently empty registry).
- [ ] `routes_history.py` — implement `/api/history/export` and
  `/api/history/daily/{date}`.
- [ ] CI frontend build artifact test — verify `npm run build` actually
  produces files under `src/twrminal/web/dist/`.
- [ ] Auth gate: enable `auth.enabled` path (currently no-op).
- [ ] Wire `message_id` on tool_calls rows (currently always NULL on
  insert; could be backfilled at `MessageComplete` time).

## Decisions pending

- [x] GitHub org for remote push: `Beryndil/Twrminal` (configured as
  `origin`).
- [ ] Partial-message semantics: confirm `include_partial_messages=True`
  emits token deltas as expected on first live agent run.
