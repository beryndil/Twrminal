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

## v0.1.39 — shipped

- [x] Housekeeping: tick stale TODO items that actually shipped in
  earlier v0.1.x slices (auth gate, graceful shutdown, budget cap).
- [x] README refreshed from v0.1.0 scaffold prose to current v0.1.x
  capability surface.

## v0.1.40 — shipped

- [x] Editable session descriptions: `description` column (migration
  0005), wired through SessionCreate/Update/Out, SessionEdit textarea,
  Conversation-header render, and the v0.1.30 export/import shape.

## Stale items resolved in earlier slices (ticked in v0.1.39)

- [x] Auth gate: enable `auth.enabled` path — opt-in bearer token
  wired in v0.1.11 (REST/WS/CLI/frontend) + AuthGate modal in v0.1.12.
- [x] Kill switch / graceful shutdown signal in the WS handler —
  shipped in v0.1.9 (lifespan-exit 1001 Going Away broadcast).
- [x] Rate-limit / soft-cap `max_budget_usd` per session via
  `ClaudeAgentOptions` — wired in `AgentSession.stream()`
  (`session.py:67-68`). Per-session column lands in v0.1.8.

## v0.2.0 — shipped

- [x] Migration `0006_tag_primitives.sql` — `tags` (id, name UNIQUE,
  color, pinned, sort_order, created_at) + `session_tags`
  (session_id, tag_id, created_at) + `idx_session_tags_tag`.
- [x] Tag store helpers (`create_tag` / `list_tags` / `get_tag` /
  `update_tag` / `delete_tag` / `attach_tag` / `detach_tag` /
  `list_session_tags`) with `session_count` rollup and canonical
  pinned-first / sort_order / id ordering.
- [x] Tag REST surface (`/api/tags/*` CRUD — 201/409 on create,
  204 on delete) + session-tag endpoints (`GET/POST/DELETE
  /api/sessions/{id}/tags[/{tag_id}]`). Attach/detach bumps
  `sessions.updated_at`.
- [x] `TagCreate` / `TagUpdate` / `TagOut` DTOs.
- [x] 25 pytest cases in `tests/test_tags.py` (store + API).
- [x] `db/schema.sql` back-filled with the v0.1.40
  `sessions.description` column that was missed in that slice.

## v0.2.1 — shipped

- [x] `Tag` type + `listTags` / `listSessionTags` helpers in
  `frontend/src/lib/api.ts`.
- [x] `tags.svelte.ts` store with `refresh()` mirroring sessions.
- [x] Tags section in `SessionList.svelte` (pinned-first, divider,
  session-count chip). Hidden during sidebar search. No filter
  behavior yet.
- [x] `+page.svelte` boot runs `sessions.refresh()` and
  `tags.refresh()` in parallel.
- [x] `tags.svelte.test.ts` store test (happy path + error path).

## v0.2.2 — shipped

- [x] Write helpers in `api.ts`: `createTag`, `updateTag`,
  `deleteTag` (handles 204), `attachSessionTag`, `detachSessionTag`.
- [x] `tags` store mutation methods + `bumpCount` for post-attach
  chip updates without a round-trip refresh.
- [x] SessionEdit modal Tags section: chips with ✕ to detach,
  inline input filters global tags; click-to-attach or Enter on
  novel name to create-and-attach.
- [x] `SessionEdit.test.ts` (3 cases: detach, suggestion-click
  attach, Enter-to-create) + extended `tags.svelte.test.ts`
  (7 cases).

## v0.2.3 — shipped

- [x] `GET /api/sessions?tags=&mode=any|all` filter + store support
  (`list_sessions(tag_ids=, mode=)`). 400 on bad tag ids.
- [x] `api.listSessions(filter?)` + sessions store caches last
  filter.
- [x] `tags` store `selected`, `mode`, `toggleSelected`,
  `clearSelection`, derived `hasFilter` + `filter`.
- [x] Sidebar: clickable tag buttons with emerald selection tint,
  Any/All toggle, "Filter: N tag(s) ✕" clear pill.
- [x] SessionList re-fetches sessions on filter change.
- [x] 5 new pytest cases + 3 new vitest cases.

## v0.2.4 — shipped

- [x] Migration `0007_projects_and_memories.sql` (projects table,
  `sessions.project_id` + `idx_sessions_project`, `tag_memories`,
  `sessions.session_instructions`).
- [x] `db/schema.sql` reconciled with the full applied shape
  (tags, session_tags, projects, tag_memories).
- [x] 4 new pytest cases (migration + cascade behavior).

## v0.2.5 — shipped

- [x] `src/twrminal/agent/prompt.py::assemble_prompt(conn,
  session_id)` — async, pure SQL, returns
  `AssembledPrompt(layers, text)`. Layer order: base → project →
  tag memories (canonical pinned/sort_order/id order; tag-without-
  memory skipped) → session_instructions.
- [x] `src/twrminal/agent/base_prompt.py::BASE_PROMPT` — short,
  deterministic base layer.
- [x] 8 pytest cases in `tests/test_prompt_assembler.py` covering
  layer order, empty-project skip, tag-without-memory skip,
  pinned/sort_order/id tiebreakers, session_instructions-last, and
  per-layer header verbatim.

## v0.2.6 — shipped

- [x] `store.create_project` / `list_projects` / `get_project` /
  `update_project` / `delete_project` with `session_count` rollup
  and canonical pinned-first / sort_order / id ordering.
- [x] `/api/projects` CRUD (201 on create, 409 on duplicate name,
  204 on delete, 404 on missing).
- [x] `ProjectCreate` / `ProjectUpdate` / `ProjectOut` DTOs.
- [x] `SessionCreate` + `SessionUpdate` + `SessionOut` all carry
  `project_id`. PATCH can set or clear the assignment.
- [x] `GET /api/sessions?project_id=<id>` filter;
  `project_id=none` matches `project_id IS NULL`. `store.NO_PROJECT`
  sentinel + `store.ProjectFilter` alias.
- [x] `list_sessions` refactored to one dynamic WHERE builder so
  project + tag filters compose without SQL-path explosion.
- [x] 23 pytest cases in `tests/test_projects.py`.

## v0.2.7 — shipped

- [x] `store.get_tag_memory` / `put_tag_memory` (ON CONFLICT
  upsert) / `delete_tag_memory`. Put returns None for missing tag.
- [x] `/api/tags/{id}/memory` CRUD (GET/PUT/DELETE) with
  `TagMemoryOut` + `TagMemoryPut` DTOs.
- [x] `PATCH /api/sessions/{id}` accepts `session_instructions`;
  `SessionOut` exposes it; `_SESSION_BASE_COLS` carries it.
- [x] `AgentSession(db=conn)` wires through `assemble_prompt`
  per turn as `ClaudeAgentOptions.system_prompt`. `ws_agent.py`
  passes the DB connection at construction.
- [x] 14 new pytest cases in `tests/test_tag_memories.py` (store +
  API + session_instructions round-trip) plus 2 agent-session
  cases pinning the system_prompt wire-through.

## v0.2.13 — shipped (closes v0.2)

- [x] `POST /api/sessions` requires `tag_ids: list[int]` with
  `len ≥ 1`. Unknown tag id → 400. Empty list → 400.
- [x] SessionList new-session form: tag chip input with attach /
  create-and-attach UX mirroring SessionEdit. Submit gated on ≥1
  attached tag.
- [x] Tag defaults pre-fill `working_dir` / `model` as tags are
  attached in the form (precedence matches tag-memory order).
- [x] Conversation header renders attached tag chips (pinned-first,
  ★ glyph).
- [x] README rewritten for the tags-only design: tags, memories,
  defaults, ≥1-tag rule, upgrade notes.
- [x] All test helpers auto-seed a default tag for the ≥1
  requirement. 2 new pytest cases pin the enforcement (empty tags
  → 400, unknown tag → 400).

## v0.2.12 — shipped

- [x] Inline session_instructions editor in the Inspector Context
  tab. Pre-hydrates from `sessions.selected.session_instructions`;
  draft lives in local state until Save.
- [x] Save calls `sessions.update` (PATCH). Empty content clears
  to null.
- [x] Dirty state surfaces a Reset button; Save disabled when
  clean.
- [x] Inspector auto-refetches system_prompt while pane is open
  and session's `updated_at` bumps — tag-memory edits now surface
  without close/reopen.
- [x] Dropped the dead `project` badge case from
  `layerBadgeClasses` (v0.2.9 teardown followup).

## v0.2.11 — shipped

- [x] `TagEdit.svelte` modal: name / pinned / sort_order,
  default_working_dir, default_model, markdown memory with
  live preview, delete button with two-click confirm.
- [x] Loads memory via `GET /api/tags/{id}/memory`; 404 = no
  memory yet. Save-path diffs: empty clears via DELETE,
  non-empty upserts via PUT.
- [x] Precedence hint rendered under the memory editor.
- [x] Sidebar tag rows grew a hover-reveal ✎ button.
- [x] `api.getTagMemory` / `putTagMemory` / `deleteTagMemory`
  helpers + `TagMemory` type.
- [x] 5 vitest cases in `TagEdit.test.ts`.

## v0.2.10 — shipped

- [x] Migration `0009_tag_defaults.sql` adds
  `tags.default_working_dir` + `tags.default_model` (both
  nullable).
- [x] `store.create_tag` / `update_tag` accept the new fields.
- [x] `TagCreate` / `TagUpdate` / `TagOut` expose them.
- [x] Frontend `Tag` / `TagCreate` / `TagUpdate` TS types match.
- [x] New-session form pre-fills working_dir / model from the
  highest-precedence filter-selected tag. Precedence matches
  tag-memory rules (last wins); falls back to user prefs.
- [x] 5 new pytest cases in `tests/test_tags.py`.

## v0.2.9 — shipped (teardown)

- [x] Migration `0008_drop_projects.sql` — wipes sessions, drops
  `idx_sessions_project`, drops `sessions.project_id`, drops the
  `projects` table.
- [x] Removed `routes_projects.py`, project DTOs, project store
  helpers, `NO_PROJECT` / `ProjectFilter`.
- [x] Removed `project_id` from Session DTOs + query filter +
  frontend TS.
- [x] Assembler is 3-layer (base → tag memories → session).
- [x] Deleted `tests/test_projects.py`, `tests/test_migration_0007.py`.
- [x] `V0.2.0_SPEC.md` rewritten to the tags-only design.
- [x] 161 backend + 34 frontend tests pass; ruff + mypy green.

## v0.2.8 — shipped

- [x] `GET /api/sessions/{id}/system_prompt` — `{layers,
  total_tokens}`. Same `assemble_prompt` path as the agent.
- [x] `agent.prompt.estimate_tokens` — 4-chars-per-token
  approximation (avoids tiktoken dep).
- [x] `SystemPromptLayerOut` / `SystemPromptOut` DTOs.
- [x] Frontend `getSystemPrompt` helper + `SystemPrompt` types.
- [x] Inspector **Context** disclosure above Agent, with color-
  coded kind badges and per-layer collapsibles. Refetches when
  selected session's `updated_at` changes.
- [x] Frontend `Session` / `SessionCreate` / `SessionUpdate`
  caught up to the v0.2.6 + v0.2.7 backend fields.
- [x] 3 estimate_tokens unit tests + 3 system_prompt API tests.

## v0.2 — closed

All 14 planned slices (0.2.0 → 0.2.13) shipped on 2026-04-19. v0.2
is feature-complete.

## Open follow-ups

### File-size audit (CLAUDE.md: max 400 lines)

- [x] `src/twrminal/db/store.py` split into
  `_common.py` / `_sessions.py` / `_messages.py` / `_tags.py`.
  `store.py` is now a 81-line re-export facade; largest new file
  is `_sessions.py` at 242 lines. All 168 backend tests pass
  unchanged.
- [x] `frontend/src/lib/components/SessionList.svelte` split into
  `NewSessionForm.svelte` (251), `SidebarSearch.svelte` (122),
  `TagFilterPanel.svelte` (94). `SessionList.svelte` is now 336
  lines.
- [ ] `frontend/src/lib/api.ts` is 447 lines — over the cap but
  it's all type declarations + thin fetch helpers. Splitting it
  before there's a second domain to peel off would be premature.
  Revisit if/when agent/session API expands significantly.

### Browser verification pending

Checklist lives in `TESTING_NOTES.md` §"Pending Dave's browser
walkthrough". Every v0.2 UI surface needs exercising; unit tests
cover shape, not feel.

### Other

- [ ] Partial-message semantics: confirm
  `include_partial_messages=True` emits token deltas as expected
  on first live agent run.
- [ ] Resizable / collapsible panes (raised during v0.2.13 review,
  out of scope). Candidate for v0.3.0.

## Decisions pending

- [x] GitHub org for remote push: `Beryndil/Twrminal`.
