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

## v0.1.9 — shipped

- [x] Graceful WS shutdown on lifespan exit (1001 Going Away).
- [x] Budget display in Conversation header.

## v0.1.10 — shipped

- [x] `MessageComplete.cost_usd` + `sessions.total_cost_usd` column.
- [x] Conversation header shows running cost + optional cap.

## v0.1.11 — shipped

- [x] Opt-in bearer-token auth (REST + WS + CLI + frontend).
- [x] `/api/health` reports real auth state.

## v0.1.12 — shipped

- [x] Auth token modal (AuthGate) — no more devtools hack.
- [x] 401 + WS 4401 flip the store back to `invalid` and re-open the
  gate; reconnect loop stays out.
- [x] Budget pressure coloring (amber ≥80%, rose ≥100%).
- [x] SessionList budget form handles number-input value shape.

## v0.1.13 — shipped

- [x] `Thinking` event + `ThinkingBlock` translation in AgentSession.
- [x] Frontend renders streaming thinking in a collapsible block.

## v0.1.14 — shipped

- [x] `messages.thinking` column (migration 0004) + WS persistence.
- [x] Conversation renders persisted thinking blocks on reload.

## v0.1.15 — shipped

- [x] Settings modal (gear button) — edit auth token + default
  model + default working_dir without devtools.
- [x] SessionList new-session form pre-fills from prefs defaults.

## v0.1.16 — shipped

- [x] `PATCH /api/sessions/{id}` + `store.update_session`.
- [x] Frontend `updateSession` + inline double-click rename in the
  sidebar.

## v0.1.17 — shipped

- [x] `SessionEdit` modal — title + budget editable post-creation.
- [x] `twrminal send --format=pretty` — human-readable output mode.

## v0.1.18 — shipped

- [x] WS `{"type":"stop"}` frame — cancels in-flight stream, persists
  partial turn, synthesises MessageComplete.
- [x] Frontend Stop button in Conversation header.
- [x] WS handler: single-reader / queue-dispatched refactor.

## v0.1.19 — shipped

- [x] `/api/history/search` endpoint + `SearchHit` model.
- [x] Sidebar search input (debounced) with inline match previews.

## v0.1.20 — shipped

- [x] Vitest scaffold + `npm run test`, wired into CI.
- [x] First unit tests: `parseBudget` (extracted to `utils/budget.ts`).

## v0.1.21 — shipped

- [x] `highlightText` util + tests.
- [x] Sidebar search snippets render amber-highlighted matches.

## v0.1.22 — shipped

- [x] `highlight` Svelte action — DOM-walks text nodes and wraps
  case-insensitive matches in `<mark>`.
- [x] `conversation.highlightQuery` wire-up: sidebar result click →
  highlight + scroll in the Conversation body.

## v0.1.23 — shipped

- [x] `AgentSession.interrupt()` wired to SDK `client.interrupt()`.
- [x] WS Stop frame calls interrupt before breaking, so tools abort.

## v0.1.24 — shipped

- [x] Match pill + Esc clears active highlight.

## v0.1.25 — shipped

- [x] `⌘/Ctrl+K` focuses sidebar search; `Esc` inside search clears.

## v0.1.26 — shipped

- [x] `?` cheat-sheet modal listing shortcuts.

## v0.1.27 — shipped

- [x] Sidebar cost badges with live updates + pressure coloring.
- [x] `sessions.bumpCost` for cross-store cost propagation.
- [x] Sidebar timestamp uses `updated_at`.

## v0.1.28 — shipped

- [x] Sidebar sort by updated_at; insert_message touches the session
  row so active sessions float to the top.

## v0.1.29 — shipped

- [x] Messages pagination (`?before=&limit=`) with scroll-to-top
  lazy-load + viewport preservation.

## v0.1.30 — shipped

- [x] Per-session JSON export (`/api/sessions/{id}/export` + ⇣ button).

## v0.1.31 — shipped

- [x] Session.message_count (backend + live-bumped frontend).
- [x] Header shows `· N msg`.

## v0.1.32 — shipped

- [x] Component-test scaffold (jsdom + @testing-library/svelte) +
  CheatSheet tests.

## v0.1.33 — shipped

- [x] Settings component test + `$lib` alias fix in vitest config.

## v0.1.34 — shipped

- [x] AuthGate component test (5 cases).
- [x] Node-native `localStorage` shim in vitest setup.

## v0.1.35 — shipped

- [x] `POST /api/sessions/import` + ⇡ sidebar button.

## v0.1.36 — shipped

- [x] Drag-drop session import with emerald-ring drop-zone overlay.

## v0.1.37 — shipped

- [x] Multi-file drop / picker for session import.

## v0.1.38 — shipped (closes out v0.1)

- [x] Enter/Shift+Enter swap on prompt.
- [x] Inspector "Agent" disclosure with auto-follow scroll.
- [x] TESTING_NOTES.md for the v0.1.37–38 testing pass.

## v0.2.0 — next milestone

See `V0.2.0_SPEC.md`. First numbered step: tag primitives (tags
table, session_tags join, pinned/sort_order columns, basic CRUD).
Then projects + tag memories on top. Build order lives in the spec.

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
