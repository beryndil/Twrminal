# Bearings — Open Tasks

## Scaffold reference

Full scaffold plan: `~/.claude/plans/here-are-the-architectural-ticklish-puppy.md`.
v0.1.1 slice plan: `~/.claude/plans/hazy-hatching-honey.md`.

## v0.1.1 — shipped

- [x] `AgentSession` wired to `claude-agent-sdk`.
- [x] WebSocket streaming in `src/bearings/api/ws_agent.py`.
- [x] DB CRUD in `src/bearings/db/store.py` (sessions + messages).
- [x] Real `/api/sessions` routes.
- [x] `api/models.py` Pydantic DTOs.
- [x] Lifespan wiring `init_db` → `app.state.db`.

## v0.1.2 — shipped

- [x] `GET /api/sessions/{id}/messages` history route.
- [x] `bearings send` CLI subcommand.
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
- [x] `bearings send --format=pretty` — human-readable output mode.

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

- [x] `src/bearings/agent/prompt.py::assemble_prompt(conn,
  session_id)` — async, pure SQL, returns
  `AssembledPrompt(layers, text)`. Layer order: base → project →
  tag memories (canonical pinned/sort_order/id order; tag-without-
  memory skipped) → session_instructions.
- [x] `src/bearings/agent/base_prompt.py::BASE_PROMPT` — short,
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

- [x] `src/bearings/db/store.py` split into
  `_common.py` / `_sessions.py` / `_messages.py` / `_tags.py`.
  `store.py` is now a 81-line re-export facade; largest new file
  is `_sessions.py` at 242 lines. All 168 backend tests pass
  unchanged.
- [x] `frontend/src/lib/components/SessionList.svelte` split into
  `NewSessionForm.svelte` (251), `SidebarSearch.svelte` (122),
  `TagFilterPanel.svelte` (94). `SessionList.svelte` is now 336
  lines.
- [x] `frontend/src/lib/api.ts` split into
  `frontend/src/lib/api/core.ts` (119) /
  `sessions.ts` (149) / `tags.ts` (124) / `history.ts` (64) with
  `index.ts` re-export barrel. Second domain (tags) had grown
  large enough to justify the split; all imports use `$lib/api`
  unchanged. `voidFetch` helper added to core for DELETE-without-
  body endpoints. All 168 backend + 39 frontend tests pass.
- [x] `src/bearings/agent/runner.py` split. Extracted
  `ApprovalBroker` → `agent/approval_broker.py` (136 lines) and
  `RunnerRegistry` → `agent/registry.py` (71 lines). `runner.py`
  down to 379 lines. `SessionRunner.can_use_tool` is now a
  forwarding property onto the broker; `resolve_approval` delegates.
  Stop / shutdown call `broker.deny_all(interrupt=True)` which
  fans matching `approval_resolved(decision=deny)` events.
  Test access to pending state updated to `runner._approval._pending`.
  232 backend tests pass.
- [x] `frontend/src/lib/stores/conversation.svelte.ts` split.
  Extracted `applyEvent` reducer + `SessionState` + `LiveToolCall`
  + `capToolOutput` + `hydrateToolCall` → `conversation/reducer.ts`
  (322 lines). Store class is now 186 lines: state / derived
  getters / load / loadOlder / refreshMessages / optimistic
  `clearPendingApproval` / one-line `handleEvent` that dispatches
  to `applyEvent` with a small injected `ReducerCtx`. Side effects
  (cost + message-count bumps, error, refresh) travel through that
  ctx so the reducer has no import edge on `$lib/api` or
  `sessions`. Re-exports the legacy names (`TOOL_OUTPUT_CAP_CHARS`,
  `capToolOutput`, `LiveToolCall`) so existing callers don't
  change. 89 frontend tests pass; svelte-check clean.
- [ ] `src/bearings/agent/runner.py` regressed to 657 lines after
  tool-output coalescer landed (was 379 after the prior split).
  Extract the `_ToolOutputBuffer` + `_buffer_tool_output` /
  `_delayed_flush` / `_flush_tool_buffer` / `_flush_all_tool_buffers`
  / `_drop_tool_buffer` cluster into `agent/tool_output_coalescer.py`
  with a tiny `ToolOutputCoalescer` class that holds the buffers
  dict and takes `db` + `session_id` via constructor. Runner keeps
  one reference and calls `await coalescer.buffer(id, chunk)` /
  `coalescer.drop(id)` / `await coalescer.flush_all()`. Should land
  runner.py back under 400.

### Browser verification — deferred to pre-1.0.0

Consolidated pre-1.0.0 regression pass lives in `TESTING_NOTES.md`
§"Pre-1.0.0 browser regression pass — TODO". The old per-slice
v0.2.13 / v0.3.1 / v0.3.3 checklists are stale (app is at v0.3.22
and the UI has moved on) — rewrite the list against the
1.0.0-candidate UI at the time and run it then. Do not exercise
the historical checklists as-is.

### Other

- [ ] **Investigate long hang on a single assistant turn (2026-04-21).**
  Dave reported I sat silent for far too long between his "are you hung
  up?" prompt and the eventual plan-agent response during the token-cost
  mitigation planning session (transcript
  `~/.claude/projects/-home-beryndil-Projects-Bearings/f57209ca-38b8-41b8-a6e7-cf1439c0b50d.jsonl`).
  Unknown whether the culprit is (a) a long-running sub-agent not
  forwarding progress events, (b) the WS pipeline buffering without
  flushing partial deltas, or (c) Claude Code itself. Check: does the
  Bearings stream-loop emit any keepalive / "thinking" frames while a
  Task sub-agent is running? Does `message_delta` make it to the socket
  mid-sub-agent? Does the frontend show *anything* during the gap or a
  dead spinner? Reproduce with a deliberately long Task call and
  instrument.

- [ ] **Feature: "More info" button next to Copy on assistant responses
  (2026-04-21).** Dave's ask: each assistant turn already has a Copy
  button in its action row; add a sibling button that, when clicked,
  sends a follow-up prompt to the agent asking it to go into more
  detail on the *same* issue/topic from that response. Should feel
  like a one-click "elaborate" shortcut — no typing required.
  Likely surface: the message actions component in
  `frontend/src/lib/components/MessageTurn.svelte` (lines 344–356).

  **Decisions (2026-04-22):**
  - (a) *Prompt text:* literally `Please go into more detail on
    your previous response.` Short, explicit, model-agnostic. The
    model already has the full turn in context — injecting a
    richer quoted template wastes tokens and risks confusing
    continuity ("which version of the reply am I elaborating
    on?"). Minimal beats clever.
  - (b) *Scope:* most-recent assistant turn only. Per-message
    "more info" on turn 3 when turns 4–10 exist creates an
    ambiguous contract ("which 'previous response' — the last
    one, or the one I clicked?"). Scrolled-past turns can still
    be elaborated via Quote & reply (a separate button coming in
    the same row). Latest-only keeps the semantics clean and
    spares the row from rendering the button on every historical
    turn.
  - (c) *Auto-send vs. composer pre-fill:* pre-fill + focus, do
    NOT auto-send. Dave often wants to add a qualifier ("more
    detail, especially about X"). One Enter key is cheap; an
    accidental send that burns a turn on the wrong topic is not.
    Also gives a natural cancel path (Esc clears the composer).
  - (d) *Placement + icon:* inline in the footer action row,
    using Dave's small-icon-plus-text ruling (see action-row
    research entry below). Glyph + UPPERCASE 4-char label to
    match the existing `⎘ COPY` convention. Proposed:
    `ℹ MORE`. Row order from left to right: `ℹ MORE` first,
    `⎘ COPY` last (Copy is the fallback / escape hatch, so it
    reads as the rightmost "done" action).

- [ ] **Research: assistant-reply action row — "Spawn sessions from
  this reply" button + brainstorm of other one-click actions
  (2026-04-22).** Dave's primary ask: alongside Copy (existing) and
  More Info (logged above), add a button that takes the *output of
  the current assistant turn only* (not the whole session) and
  asks an LLM to decide the best container shape for whatever the
  reply enumerates — three plausible shapes: (a) a single new
  `checklist` session with N items, (b) N new `chat` sessions (one
  per item), or (c) one new `chat` session covering the combined
  topic. Dave wants the shape decision automated, not chosen by
  him up-front. Then look around the codebase and propose other
  buttons that could live in the same action row. No action —
  research only.

  **Surface.** Single action row at the bottom of each assistant
  article in `frontend/src/lib/components/MessageTurn.svelte`
  (lines 344–356 today — one Copy button, right-aligned,
  `text-[10px] uppercase tracking-wider`). The *header* of the
  same article already has a separate `⋯` menu (lines 274–325)
  that hosts the session-reorg Move / Split actions. The footer
  row is the correct home for *reply-scoped* actions; the header
  ⋯ menu is for *session-shape* actions. Keeping those two lanes
  separate in the taxonomy avoids crowding either one.

  **Primitives that already exist and make "Spawn sessions" cheap
  to wire:**
  - Session-kind discriminator — `sessions.kind ∈ {'chat',
    'checklist'}` with CHECK constraint (`db/schema.sql:24-30`).
    Both shapes are first-class.
  - `POST /api/sessions` (chat creation) and checklist primitives:
    `POST /api/checklists/{sid}/items` + the paired-chat spawn
    `POST /api/checklists/{sid}/items/{iid}/chat`
    (`routes_checklists.py:78, 178`). Paired-chat spawn inherits
    `working_dir`, model, and tags from the parent — so a
    "checklist-with-N-items-that-each-spawn-a-chat" flow is one
    bulk call away once the items exist.
  - Tag/working-dir inheritance: every session needs ≥1 tag, and
    the checklist spawn path already defaults tags from the
    parent. The reply-spawn flow should do the same — inherit the
    current session's tags and `working_dir` unless Dave
    overrides in a preview modal.
  - `Message.content` on the server already carries the full
    assistant reply markdown, so the classifier has a clean input
    and doesn't need to walk the whole transcript.

  **LLM classification is the hard part, and it shares a
  dependency with Session-Reorg Slice 6.** The "pick the right
  shape, then extract the item list + titles + tags" step is a
  sub-agent call. Running it inline in the current session's
  context would pollute the parent. The same blocker gates
  Slice 6 (analyze-for-reorg). Both should wait on the Option 4
  "researcher" sub-agent + token-cost Wave 3 landing, then ship
  as one wave that shares the sub-agent plumbing — classifier
  prompt, structured-JSON output schema, preview modal,
  commit-on-approve. Before Wave 3: a heuristic fallback
  (numbered-list / bulleted-list extraction + length threshold
  to decide checklist vs. 1-chat vs. N-chats) is plausible as a
  v0 but should be clearly labeled "heuristic preview" in the
  UI so Dave doesn't confuse it with the real classifier.

  **UX shape (decided 2026-04-22).** Dave: small icons with
  text. So every action in the row is glyph + space + UPPERCASE
  4-char label, matching the existing `⎘ COPY` convention.
  Initial row (left→right): `ℹ MORE` · `＋ SPAWN` ·
  `❝ QUOTE` · `⎘ CODE` · `⎘ COPY`. Copy stays rightmost as the
  escape-hatch "done" action. Overflow (once the row has >5
  buttons): a footer-side `⋯ MORE↓` dropdown, visually distinct
  from the header `⋯` menu (header = session-reorg, footer =
  reply-scoped — different lanes). Icon-only and pure-dropdown
  layouts both rejected: icon-only sacrifices discoverability
  for the small real-estate saving; pure-dropdown hides every
  primary action behind an extra click.

  **Spawn preview modal** is non-negotiable: classifier output
  is editable (retitle, retag, drag items between proposals,
  drop items), then one approve-all commit that creates the
  checklist+items or the N chats in a transaction.

  **Brainstormed candidates for the action row** (scored for
  "built on existing primitives" vs. "needs new plumbing"):

  Built on existing primitives (ship any time):
  - **Quote & reply.** Pre-fills the composer with
    `> <selected excerpt>\n\n` so Dave can build on a specific
    line without re-typing. No backend work.
  - **Copy code only.** Strip prose, keep fenced code blocks
    concatenated. One function in the copy handler.
  - **Export single turn.** Uses the existing
    `GET /sessions/{id}/export` shape, filtered to one
    `message_id`. Single-turn share instead of whole session.
  - **Jump to tool calls for this turn.** Focus Inspector pane
    on the tool calls belonging to this `message_id`.
    `list_tool_calls` already returns the data; UI-only.
  - **Tokens / cost for this turn.** Tooltip on hover, not a
    nav. `get_session_tokens` is session-level today; would need
    a per-message rollup, but the raw token events exist.
  - **Append to TODO.md.** Pattern-detect "we should later X" /
    "deferred" language in the reply and offer to append the
    relevant paragraph to the nearest TODO.md. Uses existing
    `routes_fs.py` write path.

  Needs the sub-agent plumbing (ship with the Wave-3 bundle):
  - **Summarize / TL;DR.** Cousin of More Info, the other
    direction. Same prompt template family.
  - **ELI5 / Rephrase simpler.** Ditto.
  - **Critique / second opinion.** Spawn a critic sub-agent to
    poke holes. High value before plan execution.
  - **Regenerate.** Redo the previous turn with the same
    prompt; keep both, let Dave pick. Needs a message-branching
    concept the DB doesn't model yet (every message today has
    one parent).

  Needs new DB state:
  - **Pin / bookmark turn.** New `message_pins` column or
    table; show pins as anchors in SessionList.
  - **Save as memory / system-prompt snippet.** When the reply
    establishes a durable rule ("when X, do Y"), push it into a
    memory file or system-prompt addendum. Overlaps with
    `get_session_system_prompt` but that's read-only today.
  - **Rate this reply (👍/👎).** Per-message feedback column
    for quality tracking. Cheap DB, moderate UI.

  **Recommended first wave** (before Wave 3 lands, no sub-agent
  needed): Quote & reply + Copy code only + Export turn + Jump
  to tool calls. These four cost little, fill out the row with
  high-frequency actions, and let Dave live with the new
  pattern before the LLM-powered buttons arrive.

  **Recommended second wave** (with Wave 3): More info + Spawn
  sessions + Summarize + Critique, all sharing one classifier /
  sub-agent call pattern. Ship the preview-modal UX once and
  reuse across all four.

  **Decisions (2026-04-22):**
  - *Row style:* small icons + UPPERCASE 4-char text (Dave's
    ruling). Locked in above.
  - *Spawn preview modal placement:* **floating modal**
    (`SpawnPreviewModal.svelte`), not Inspector-pane hijack.
    Reasoning: the Inspector is the only surface for tool-call
    context, and Dave's workflow when reviewing an
    enumerate-this-reply often involves cross-referencing the
    tool calls that produced the plan. Hijacking the Inspector
    kills that cross-reference at the exact moment it's most
    useful. Floating modal costs one overlay; Inspector hijack
    costs the whole right-pane context. Size it bigger than
    `SessionPickerModal` — the editable-proposal table needs
    real-estate.
  - *Close parent session after Spawn:* **no, by default.**
    Render a checkbox "Close this session after spawning" in
    the preview modal, default unchecked. Reasoning: sometimes
    the enumeration is mid-conversation and Dave keeps asking
    questions; auto-closing would surprise him. The "punch list
    handoff" case where auto-close *is* what he wants is
    catchable with one checkbox. Reopen is one PATCH away
    (`POST /sessions/{id}/reopen` exists) so the cost of getting
    it wrong is low either direction — but defaulting to "leave
    open" preserves the conversation contract.
  - *Heuristic-v0 or wait for Wave 3:* **ship heuristic v0
    now**, swap the classifier in when Wave 3 lands. Reasoning:
    Wave 3's ETA is unbounded; the heuristic (numbered/bulleted-
    list extraction + length threshold → checklist vs. N-chats
    vs. 1-chat suggestion) is tractable and the preview modal
    corrects mis-classifications. Shipping v0 exercises the
    spawn transaction path, the preview UX, and the row
    integration, so Wave 3 becomes a backend swap with zero UI
    churn. Label the modal banner "heuristic preview — review
    before spawning" so Dave never mistakes it for the real
    classifier.
  - *Brainstorm vetoes* (from the list above):
    - **Regenerate — drop.** Needs a message-branching schema
      (every message today has one parent). Big plumbing cost
      for a rare use case. Punt indefinitely unless Dave asks.
    - **Rate reply (👍/👎) — drop.** Nobody's consuming the
      signal; it's UI noise. Revisit only if a concrete
      consumer appears (local fine-tune, feedback analytics).
    - **Save as memory / system-prompt snippet — punt to own
      entry.** Real use case, but the system-prompt API is
      read-only today and "where does the memory persist"
      (session, tag, global) is a non-trivial feature design.
      Doesn't belong as a one-click row button.
    - **Append to TODO.md — punt to own research entry.**
      "Nearest TODO.md" is ambiguous in Bearings' model
      (server cwd? Dave's project cwd? session `working_dir`?).
      Needs its own tiny design, not a row button.
    - **Pin / bookmark turn — keep on maybe list.** Session
      Reorg's split/move covers most curation needs, reducing
      pin's value. Not committed, not vetoed. Revisit after
      Session Reorg Slices 3–7 ship.
  - *First-wave row buttons* (pre-Wave-3, no sub-agent):
    **`❝ QUOTE`, `⎘ CODE`, `⬇ SAVE`, `⎯ TOOL`.**
    - `❝ QUOTE` — pre-fills composer with `> <reply excerpt>`.
    - `⎘ CODE` — copy fenced code blocks only, concatenated.
    - `⬇ SAVE` — export single turn as Markdown via filtered
      `/sessions/{id}/export`.
    - `⎯ TOOL` — focus Inspector on this turn's tool calls.
      (Chose `⎯ TOOL` over `🔧` to stay monochrome-ASCII-
      friendly with the rest of the row; Tailwind emoji
      rendering is inconsistent across fonts.)
  - *Second-wave row buttons* (with Wave 3, shares sub-agent
    plumbing): **`ℹ MORE`, `＋ SPAWN`, `✂ TLDR`, `⚔ CRIT`.**
    All four hit the same classifier/sub-agent call pattern and
    the same preview-modal UX (except `ℹ MORE` which just
    pre-fills the composer — no modal needed). Shipping them
    together means writing the sub-agent plumbing once.
  - *Spawn button label wording:* `＋ SPAWN`, not `＋ SESSIONS`
    or `＋ CHECKLIST`, because the shape is classifier-chosen
    and the label shouldn't lie about which shape is coming.
    "Spawn" is a verb already used in the codebase
    (`spawn_paired_chat`) so it's consistent with internal
    vocabulary.

- [ ] **Upstream: plan mode pins a stale plan file across topic pivots
  (2026-04-21).** Discovered in the Checklists session
  (`f66b7166…`) while trying to plan the checklist feature. Entering
  plan mode auto-selected `~/.claude/plans/enumerated-inventing-ullman.md`
  (the unrelated token-cost-mitigation plan from hours earlier in the
  same session) as "the only file you are allowed to edit." System-
  reminder verbatim: *"A plan file already exists at
  /home/beryndil/.claude/plans/enumerated-inventing-ullman.md. You can
  read it and make incremental edits using the Edit tool. … this is the
  only file you are allowed to edit — other than this you are only
  allowed to take READ-ONLY actions."* Forces a choice between
  clobbering a still-valuable unrelated plan or appending a mismatched
  section to a file on a different topic; no in-mode affordance to
  mint a fresh plan file. Selection isn't pure "most recently modified"
  either — `sparkling-triaging-otter.md` was newer on disk (Apr 21
  14:29) than `enumerated-inventing-ullman.md` (13:35), so the harness
  appears to remember a per-session assignment. Confirmed **not a
  Bearings bug**: `grep` across `src/` shows every `~/.claude/plans/`
  reference is an in-code comment pointing at plan docs for trace-
  ability — no file-selection logic, no system-reminder emission, no
  plan-path wiring through `AgentSession` / `prompt.py`. The reminder
  is emitted by Claude Code's plan-mode harness inside `claude-agent-
  sdk` / the CLI, upstream of Bearings. **Action:** file upstream to
  Anthropic / Claude Code asking for one of — (1) mint a fresh three-
  word-slug plan file per topic by default, (2) prompt "resume X or
  start a new plan file?" on plan-mode entry, or (3) allow the agent
  to `touch` a new file in `~/.claude/plans/` from within plan mode.
  Also a sibling bug Dave flagged in the same turn: plan-mode
  dropdown behavior needs its own investigation (tracked separately
  once reproduced). Workaround: drop out of plan mode, hand off to a
  fresh session, replan there.

- [ ] **Feature: Session Reorg — message triage across sessions.**
  Plan: `~/.claude/plans/sparkling-triaging-otter.md`. Session:
  `a0a4f828…` (tag: Bearings). Motivating failure was the "Checklists"
  session drifting across 4 unrelated topics and becoming painful to
  reload. 7 shippable slices:

  - [x] **Slice 1 — DB primitive.** Shipped as v0.3.17. See section
    below. Note: `sessions.message_count` is a SELECT COUNT(*) subquery
    in `_sessions.SESSION_COUNT`, not a stored column, so the primitive
    doesn't "recompute" it — the next read just picks up the new count.
    Simpler than the original slice scope.
  - [x] **Slice 2 — Move + Split routes.** Shipped as v0.3.18. Both
    routes compose `store.move_messages_tx` (Slice 1) and call
    `runner.request_stop()` on affected live runners. `reason="…"`
    threading deferred — `request_stop()` carries no public reason
    string today; adding the param is speculative plumbing, will add
    when the UI wants to surface the stop cause.
  - [x] **Slice 3 — UI: hover-action Move + Split.** Shipped as
    v0.3.19. Per-message `⋯` menu in `MessageTurn.svelte` exposes
    Move + Split; new `SessionPickerModal.svelte` (searchable,
    tag-filter, inline create-new), 30-second `ReorgUndoToast.svelte`
    running an inverse move. Note: split's inverse pulls the moved
    messages back into source AND deletes the freshly-orphaned new
    session so a cancelled split leaves no sidebar residue. 12 new
    Svelte tests, 125 frontend total. Backend unchanged.
  - [x] **Slice 4 — UI: bulk select.** Shipped as v0.3.20. Toggle
    button (`☐` / `☑`) in the session header enters bulk mode.
    Each message row renders a checkbox; shift-click selects the
    inclusive span against `conversation.messages`; floating
    `BulkActionBar.svelte` with Move N / Split / Cancel buttons +
    `m` / `s` / `Esc` shortcuts (ignored while typing a prompt).
    `doBulkMove` helper shared by split-into-existing and bulk ops;
    undo deletes the freshly-created target when the op was move-
    to-new-session so cancelled ops leave no sidebar residue. New
    `defaultCreating` prop on `SessionPickerModal` so bulk-split
    opens straight into the create form.
  - [x] **Slice 5 — Merge route + audit divider.** Shipped as
    v0.3.21. `POST /.../reorg/merge` + `reorg_audits` table +
    persistent chronological `ReorgAuditDivider` in the source
    conversation + ⇲ Merge header button (picker opens without
    create-new affordance). Undo closures thread `audit_id` and
    delete the audit row on success (cascade handles the target-
    delete case). `doMerge` snapshots source message IDs before
    the merge so undo moves exactly those rows back — necessary
    because `move_messages_tx` preserves `created_at`.
  - [ ] **Slice 6 — LLM-assisted analyze (~1–2 days, BLOCKED on
    token-cost Wave 3).** `POST /sessions/{id}/reorg/analyze`
    dispatches a sub-agent (needs Option 4 "researcher" to land first
    so the analysis doesn't pollute the parent context). Returns
    structured JSON proposal; UI renders as an editable table where
    Dave can retitle, retag, drag messages between proposals, and
    approve individually. Fallback until Wave 3: rule-based heuristic
    (long-silence split + keyword-shift split) as placeholder.
  - [x] **Slice 7 — Polish.** Shipped as v0.3.22.
    `store.detect_tool_call_group_warnings` scans proposed moves
    for assistant/user (tool_use + tool_result) pairs that would
    straddle the boundary; routes surface the warning on the
    response and `ReorgUndoToast` renders each one in amber above
    the main message. Prometheus `bearings_session_reorg_total{op}`
    counter incremented on every real op (not idempotent no-ops).
    The "optional audit table" fallback wasn't needed — the
    `ReorgAuditDivider` stream already covers that purpose.

  Open design questions (see plan §"Open questions for Dave"):
  cost-attribution policy (leave on source vs. follow messages),
  undo-window length (30s default), Slice-6 priority (ship 1–5 first
  or put 6 on the critical path), tool-call-group warn-vs-refuse.

## v0.5.1 — shipped

Slice 4.1: paired-chat polish pass after Dave's v0.5.0 review. Tightens
the coupling between checklist items and their chat sessions so the UX
matches the mental model — the agent stays in its lane, closing the
chat flips the item, checking the item closes the chat, completing the
whole list closes the parent session, and parent items in nested
checklists render with a disabled-but-visible checkbox whose state is
derived from the cascade. Patch bump (0.5.0 → 0.5.1) because no new
primitives land; every change is a tightening of v0.5.0 behavior.

- [x] Prompt addendum: the `checklist_context` layer now includes a
  stay-in-lane paragraph ("do not propose sibling items, closing this
  chat marks the item done automatically") so the agent stops
  offering to continue onto the next task.
- [x] `close_session` cascade: closing a paired chat calls
  `toggle_item(checked=True)` on the linked item, which cascades
  up through parents via the new cascade-up logic, then recursively
  closes the parent checklist session when `is_checklist_complete`
  returns true. Bounded — the checklist session has no
  `checklist_item_id`, so the recursion depth is ≤1.
- [x] `toggle_item` cascade-up: walks from the leaf upward, and for
  each ancestor sets `checked_at` iff every direct child has
  `checked_at` set. Invariant runs inside the same transaction as the
  leaf write so a concurrent reader never sees a half-updated chain.
- [x] `is_checklist_complete` helper: true iff every root-level item
  has `checked_at` AND the checklist has ≥1 root item. Nested
  descendants are left to the cascade-up rule. Exported from
  `store.py` so both routes and the `close_session` cascade share a
  single source of truth.
- [x] HTTP toggle route auto-closes the parent session when the last
  unchecked root item becomes checked. One-directional — unchecking
  a previously-checked item never reopens the session.
- [x] ChecklistView drops the `window.confirm` prompt. Checking a
  paired item closes the chat unconditionally; the cascade is
  intentional and the extra click was friction.
- [x] ChecklistView renders the paired chat's session title as an
  always-visible `text-sky-400` link next to the item label
  (replaces the opacity-0 `↪` hover affordance). Clicking selects
  the paired session and connects the agent runner.
- [x] ChecklistView nested rendering via `{#snippet itemRow}` with
  `{@render itemRow(child)}` recursion. Parent items render with a
  disabled checkbox whose tooltip explains that parents are
  auto-checked from their children; paired-chat affordances hide on
  parents (they're not work units).
- [x] `checklists.toggle` store method re-fetches the full checklist
  after the `toggleItem` call so the client picks up any cascade
  effects the single-item response can't convey (parent auto-check,
  parent auto-close).

## v0.5.0 — shipped

Checklist Sessions — Slice 4 of
`~/.claude/plans/nimble-checking-heron.md` lands per-item paired
chat sessions with a "memory plug" so the agent knows which item
it's addressing. Minor bump (0.4.1 → 0.5.0) because this ships a
new primitive: a second `sessions.kind` (chat) that's structurally
bound to a specific `checklist_items` row via symmetric FK
pairing. No special "open chat from checklist" button — the UI
exposes a per-item 💬 / ↪ affordance that either spawns a new
paired chat or re-selects the existing one (idempotent).

- [x] Migration 0017 adds `checklist_items.chat_session_id`
  (nullable FK, ON DELETE SET NULL) and `sessions.checklist_item_id`
  (nullable FK, ON DELETE SET NULL). Symmetric so either side
  surviving orphans the other without cascade.
- [x] Store helpers: `get_item_by_id`, `pair_item_with_chat`,
  `get_paired_chat_for_item`. Both sides write atomically in a
  single transaction; a second pair call on an already-paired item
  is a no-op returning the existing chat row.
- [x] Prompt assembler: new `checklist_context` layer between
  `tag_memory` and `session`. Reads checklist + parent item fresh
  on every turn (so edits from another tab land next turn), skips
  cleanly on stale pointers (parent deleted, FK nulled), renders
  a bulleted breadcrumb + the item's `notes` if present.
- [x] API: `POST /sessions/{id}/checklist/items/{item_id}/chat`
  spawns or returns the paired chat; `GET` the same route fetches
  the existing pairing; both 404 on missing, 400 on wrong kind.
  `ItemOut.chat_session_id` and `SessionOut.checklist_item_id`
  round-trip.
- [x] 25 backend tests covering migration shape, store helpers,
  prompt layer (render + stale-pointer skip via
  `PRAGMA foreign_keys = OFF`), and HTTP API including idempotent
  spawn + cascade-on-delete.
- [x] Frontend: `spawnPairedChat` / `getPairedChat` in
  `api/checklists.ts`, `checklists.spawnChat()` store method,
  ChecklistView per-item 💬 (Work on this) / ↪ (Continue working)
  button that routes through the store then `sessions.select()` +
  `agent.connect()`. Checking a box whose item has a paired chat
  prompts "Close the paired chat too?" via `window.confirm`.
- [x] Conversation breadcrumb: paired-chat headers render a
  `📋 parent ›  item` row above the title with a one-click
  link back to the checklist session. Effect resolves the item +
  parent via `api.getChecklist` so the crumb survives hard
  reloads.
- [x] 2 frontend tests for the per-item affordance (Work-on spawn
  path + the Continue-working re-render when `chat_session_id` is
  set). Six existing fixture files updated to include the new
  `checklist_item_id: null` field on Session.

## v0.4.1 — shipped

Checklist Sessions — Slices 2 and 3 of
`~/.claude/plans/nimble-checking-heron.md` shipped together because
either half alone leaves the other broken: Slice 2 exposes a REST
surface with no UI to reach it, Slice 3 without 2 has no endpoints
to call. Point bump (0.4.0 → 0.4.1) rather than a minor because no
new primitives — the sessions.kind discriminator landed in 0.4.0 and
this ships the plumbing around it.

- [x] `SessionCreate.kind` (Literal, defaults `'chat'`) and
  `SessionOut.kind` so the frontend can create checklist sessions
  and the sidebar can render the badge. `POST /api/sessions` with
  `kind='checklist'` also inserts the companion `checklists` row
  in the same transaction.
- [x] `routes_checklists.py` — seven endpoints under
  `/sessions/{id}/checklist[/items[/{item_id}[/toggle]]]`. Helper
  `_require_checklist_session` 404s on missing / 400s on wrong
  kind; item routes additionally check
  `item['checklist_id'] == session_id` so a client can't mutate a
  neighbor's list by guessing an id.
- [x] WS handler rejects checklist sessions with close code 4400
  before the runner spawns; `_build_runner` keeps its own
  defense-in-depth `ValueError` so any programmatic caller that
  bypasses the WS guard still fails loudly.
- [x] Reorg handlers (`move`, `split`, `merge`) gate on `kind`:
  both source and target must be `'chat'`, else 400 with a
  descriptive `role` label. Prevents a merge into a checklist
  from silently dropping items on the floor.
- [x] 18 backend tests covering kind round-trip, CRUD,
  cross-checklist rejection, cascade delete, the reorg guard on
  all three handlers / both sides, and the WS 4400 close.
- [x] Frontend `Session.kind` type + optional `kind?` on
  `SessionCreate`. Five existing test fixtures updated with
  `kind: 'chat'` to satisfy the now-required field.
- [x] `frontend/src/lib/api/checklists.ts` — bindings for all
  seven routes; re-exported through the `$lib/api` barrel.
- [x] `frontend/src/lib/stores/checklists.svelte.ts` — Svelte 5
  runes store with optimistic updates and rollback on server
  error. Captures `this.current` + `this.sessionId` into locals
  before `await` so TS can narrow past the async boundary.
- [x] `ChecklistView.svelte` — notes textarea (blur-commits
  against the server value), flat item list with click-to-edit
  label, Enter-to-add with input refocus, Add-item autofocus on
  pane visibility (Q1-A). Layout mirrors `Conversation.svelte`'s
  header/body split.
- [x] `+page.svelte` right-pane switch on
  `sessions.selected?.kind === 'checklist'`. `boot` skips
  `agent.connect` for checklist sessions so the runner guard
  doesn't close the socket with a spurious error.
- [x] `SessionList.svelte` — `☑` badge before the title for
  checklist sessions; `onSelect` closes the existing agent
  connection and skips connect for checklist kinds.
- [x] `NewSessionForm.svelte` — `[ Chat ] [ Checklist ]`
  segmented control; Checklist hides Budget + Model. Kind
  threaded into `sessions.create`; connect skipped when
  checklist.
- [x] New vitest coverage: `NewSessionForm.test.ts` (3 tests,
  hide/show + kind payload + agent.connect gating),
  `ChecklistView.test.ts` (3 tests, load + optimistic add +
  rollback). All 181 vitest tests green, 0 svelte-check
  warnings, 416 pytest green.

Follow-ups (blocked on Slice 4):

- Per-item "💬 Work on this" spawn → paired chat session with
  checklist context injected via `prompt_assembler.py`. User's
  revised Slice 4 direction: one chat per item, resolve-on-check
  to close the paired chat, open the next item.
- Nested items + drag-reorder. Backend already ships
  `parent_item_id` and `reorder_items`; the flat-list renderer in
  Slice 3 simply doesn't surface either yet.

## v0.4.0 — shipped

Checklist Sessions — Slice 1 of
`~/.claude/plans/nimble-checking-heron.md`. Backend primitives only:
the `sessions.kind` discriminator and two new tables
(`checklists`, `checklist_items`) land with their full store surface
but no API or UI yet. Existing chat sessions backfill as
`kind = 'chat'` via the `NOT NULL DEFAULT` on migration 0016, so
every current code path keeps working unchanged. Minor bump (0.3 →
0.4) because this is a new primitive, not a fix.

- [x] Migration 0016 — `sessions.kind` column + `checklists` /
  `checklist_items` tables with cascade-on-delete from the session
  row all the way down to items.
- [x] `sessions.kind` threaded through `_sessions.SESSION_BASE_COLS`
  so every `SELECT` picks it up; `create_session(..., kind=...)`
  accepts `'chat'` (default) or `'checklist'`, rejects anything
  else with a `ValueError` before the INSERT fires.
- [x] `import_session` round-trips `kind` — exports that predate
  0016 restore as chats without special-casing at the call site.
- [x] `db/_checklists.py` with CRUD on checklists and items, a
  single-round-trip `get_checklist` that returns items inline, a
  `toggle_item` that stamps `checked_at`, and a `reorder_items`
  that ignores foreign ids so a malicious client can't reorder a
  list it doesn't own.
- [x] Store re-export wall updated — every new helper is
  importable via `from bearings.db import store` to keep the
  existing facade convention.
- [x] 17 new unit tests covering migration shape, kind
  round-trip, CRUD, default-append sort_order, cascade from
  session deletion, and the foreign-id reorder guard. Full suite
  (398 tests) still green.

Follow-ups (blocked on later slices of the same plan):

- API layer — `routes_checklists.py`, WS/runner/reorg guards,
  kind in the SessionCreate DTO (Slice 2).
- Frontend — right-pane switch on `session.kind`, ChecklistView
  component, NewSessionForm kind toggle (Slice 3). Slices 2 + 3
  ship together in a single version bump; Slice 2 alone would
  leave a usable REST surface but a broken UI pane for
  checklist-kind sessions.

## v0.3.29 — shipped

Retune ContextMeter flash threshold. Raised immediately after v0.3.28
shipped: the 32K raw-token threshold baked in v0.3.28 overstated
Claude's long-context behavior (Sonnet 4.x holds up well past 100K;
Anthropic's own auto-compact fires around 160K). A 32K flash would
fire on routine Claude Code sessions, which is exactly the "the
meter is always screaming, ignore it" failure the flash was meant
to avoid. Retied flash to the existing red percentage band.

- [x] Dropped `CONTEXT_DEGRADATION_THRESHOLD_TOKENS` constant.
- [x] Flash now fires at ≥90% (auto-compact on) or ≥80% (off),
  matching the red color band exactly — one boundary, one rule.
- [x] Tooltip reworked to stop claiming "recall degrades past 32K"
  and instead describe what the red band actually means:
  auto-compact imminent (compact on) or hard-cap proximity (off).
- [x] Tests rewritten: flash edge at 89/90% on, 79/80% off, plus a
  regression guard that 50K tokens at 25% does NOT flash (would
  have tripped the old rule).

## v0.3.28 — shipped

ContextMeter pill now shows the raw context-token count and flashes
red past 32K. Raised because Dave hit recall degradation on several
sessions without visible warning — the pill read "ctx 17%" while
context was already soft. Fixed by surfacing the token count directly
(`ctx 34.2k (17%)`) and adding a hard 32K threshold that forces a red
pulse regardless of the percentage band. `motion-safe:` variant keeps
the pulse off for reduced-motion users; solid red band stays.

- [x] `flashRed` keyframe + `animate-flash-red` utility added to
  `frontend/tailwind.config.js` (floor = red-900/60 / red-100; peak =
  red-500/90 / white; 1.2s cycle ≈ 0.83 Hz, below WCAG 3 Hz threshold).
- [x] `CONTEXT_DEGRADATION_THRESHOLD_TOKENS = 32_000` in
  `ContextMeter.svelte`; pill widened to `ctx <tokens> (<pct>%)`.
- [x] Past-threshold tooltip/aria-label includes
  `"Past 32K — recall degrades beyond this point."`.
- [x] `ContextMeter.test.ts` — first unit coverage for the component.
  5 cases: null, under-threshold render, 31,999 no-flash, exact-32K
  flash, 90k overrides amber band.

## v0.3.27 — shipped

Session close / reopen lifecycle. Raised right after session
82c151f4 ("Long messages dominate viewport", v0.3.24) — sessions
accumulated forever in the sidebar with no signal that a charter had
shipped, so you had to mentally track live vs. archived history.
Fixed by adding a closed flag that pushes closed sessions into a
collapsed bottom group in the sidebar — the location itself is the
state indicator (like a closed ticket or an archived email).

- [x] Migration `0015_session_closed_at.sql` — nullable `closed_at
  TEXT` on `sessions`. Null = open, ISO timestamp = closed. Additive.
- [x] Store helpers in `db/_sessions.py`: `close_session`,
  `reopen_session`, `reopen_if_closed(*ids)`. All idempotent; the
  bulk form only touches rows that currently carry the flag so it
  doesn't inflate `updated_at` for already-open sessions.
- [x] `import_session` round-trips `closed_at` through export /
  import — test proves it survives a JSON round trip.
- [x] `POST /api/sessions/{id}/close` + `/reopen` routes. Dedicated
  lifecycle routes rather than a PATCH extension because the
  transition has side effects (auto-reopen on reorg). Idempotent:
  close-twice refreshes the timestamp, reopen-twice is a no-op.
- [x] Reorg move / split / merge auto-clear `closed_at` on any
  session that had rows moved into or out of it (only when the op
  actually moved >0 rows — idempotent no-op moves leave the flag
  alone). Merge reopens both sides unless `delete_source=true`, in
  which case only the target is reopened.
- [x] `SessionList.svelte` splits into an open `<ul>` plus a
  collapsible `Closed (N)` group at the bottom. Group's expanded
  state is component-local and resets to collapsed each page load.
- [x] Conversation header: new `✓` button after the merge `⇲`,
  emerald when closed / slate when open, aria-pressed flips with
  state. `data-testid="close-session"` for tests.
- [x] 16 new pytest: store idempotency, 404 on unknown, live-runner
  not dropped on close, per-op auto-reopen matrix, import/export
  round trip.
- [x] 13 new vitest: 8 for sessions store (openList / closedList
  derived + close / reopen happy + error paths), 5 for SessionList
  (group render, toggle, "No open sessions" placeholder).

## v0.3.26 — shipped

Session-description clamp in the conversation header. Long
multi-paragraph plugs (design briefs, pasted bug reports) had no
max-height and ate half the viewport before the conversation
even started.

- [x] Tailwind `line-clamp-3` wraps the description paragraph in
  `Conversation.svelte` — folds to three lines with mask fade.
- [x] Compact `⌄ show more` / `⌃ show less` toggle. Renders only
  when measured `scrollHeight > clientHeight` so short plugs stay
  toggle-free.
- [x] Clamp state resets on session switch and re-measures on
  description edits (paired with the 0.3.25 runner-respawn so live
  edits propagate end-to-end).
- [x] Companion to the 0.3.24 message-body fold — long content
  anywhere in the page (header plug, user paste, assistant turn)
  now has a predictable fold affordance.

## v0.3.25 — shipped

Runner auto-drop when prompt-layer fields change. The claude
subprocess bakes in `--system-prompt` at launch, so in-place DB
edits to `description`, `session_instructions`, or tag-memory
content never reached a live runner without respawn. Dave edited
the description from the UI mid-session and the agent kept
behaving against the stale prompt.

- [x] `PATCH /sessions/{id}` drops the runner when `description`
  or `session_instructions` is in the request body. Title-only
  and budget-only patches leave the runner alive (no prompt
  impact).
- [x] Tag attach / detach and tag-memory put / delete drop every
  runner whose session inherits the affected tag's memory.
- [x] 13 new pytest across `test_routes_sessions.py` and
  `test_tag_memories.py` covering the drop matrix (title-only →
  no drop, description → drop, tag attach → drop, etc.).
- [x] Unblocks 0.3.26 header-clamp re-measure: editing the
  description from the header now propagates to the live agent
  on the next turn instead of lingering until reconnect.

## v0.3.24 — shipped

Long user messages dominated the conversation viewport. Pasted
bug reports / design briefs pushed the assistant's response
off-screen, forcing constant scroll to reread prior turns.

- [x] `CollapsibleBody.svelte` — height-based fold around rendered
  markdown in `MessageTurn`. Clamps bodies taller than 480px with
  a mask-image fade and a `show full message` / `collapse` toggle.
- [x] Expanded state persists per-message in localStorage
  (`bearings:msg:expanded:<id>`) so reloads and scroll-back don't
  re-collapse underfoot.
- [x] Streaming assistant turns bypass the fold — new tokens stay
  visible as they land; fold only applies once the body is final.
- [x] 7 new vitest (`CollapsibleBody.test.ts`). Existing
  `MessageTurn.test.ts` stays green — tool-call group, thinking
  details, copy button, reorg menu, bulk-select, shiki all
  unchanged.
- [x] Motivated the 0.3.27 close / reopen feature (session
  82c151f4): sessions accumulated in the sidebar forever with no
  signal that a charter had shipped.

## v0.3.23 — shipped

Agents with empty context (fresh runner after reaper, reconnect
with drifted cwd, or SDK-resume miss) had no way to orient on
"why am I here" short of reading conversation memory back.

- [x] New `session_description` prompt layer slotted between
  `base` and `tag_memory` in `src/bearings/agent/prompt.py`.
  Injects the session's description blurb directly into the
  assembled system prompt so the agent reads the human-authored
  charter on first turn.
- [x] Bypass when description is NULL — layer is omitted rather
  than emitting an empty heading, so sessions without a plug
  don't waste tokens on structural noise.
- [x] 4 new pytest in `test_prompt_assembler.py` covering layer
  presence, ordering (between base and tag_memory), and the
  null-description bypass.
- [x] Motivated 0.3.27: once charters land in the prompt, shipped
  charters accumulate in the sidebar with no "this is done" signal,
  so a close / reopen lifecycle was the natural follow-up.

## v0.3.22 — shipped

Slice 7 (Polish) of the Session Reorg plan
(`~/.claude/plans/sparkling-triaging-otter.md`). Tool-call-group
warnings on splits that would orphan a call/result pair + a
Prometheus counter for per-op volume. Ships the last unblocked
piece of the reorg plan.

- [x] `store.detect_tool_call_group_warnings(messages, tool_calls,
  moved_ids)` — pure function, no DB writes. Flags any assistant
  message with ≥1 tool_calls whose immediate-next user message (the
  tool_result carrier) would end up on the opposite side of the
  boundary from the assistant.
- [x] `/reorg/move` and `/reorg/split` populate
  `warnings: [{code: 'orphan_tool_call', message, details: {
  assistant_message_id, user_message_id, tool_names }}]` in the
  response. `/reorg/merge` always returns `[]` — merge moves every
  source row together so no pair can be split by it.
- [x] Warnings computed BEFORE `move_messages_tx` so the scan sees
  both halves of any affected pair on the source.
- [x] `ReorgUndoToast` renders an amber banner above the main
  message for each warning (`data-testid="reorg-undo-warning"`,
  `data-warning-code="orphan_tool_call"`). Hidden entirely when the
  list is empty — no visual change on the common path.
- [x] `bearings_session_reorg_total{op=move|split|merge}` counter
  in `metrics.py`. Instrumented in each route at commit time so a
  failed / no-op call never bumps the counter.
- [x] 17 new pytest (354 total, up from 337): 9 warning-detector
  unit tests + 4 route-level warning tests + 4 metric tests.
- [x] 2 new vitest (147 total, up from 145) for the toast's warning
  render branch.

Reorg-plan close-out:

- Slices 1–5 + 7 shipped. Slice 6 (LLM-assisted analyze) remains
  BLOCKED on token-cost Wave 3 (the sub-agent researcher). Dave
  declined the local-LLM / heuristic fallback variants.

## v0.3.21 — shipped

Slice 5 of the Session Reorg plan
(`~/.claude/plans/sparkling-triaging-otter.md`): merge route +
persistent audit divider. Source sessions now render a chronological
"Moved/Split off/Merged N messages to '…'" divider inline with the
turns, clickable to jump to the target.

- [x] Migration `0014_reorg_audits.sql` — `reorg_audits` table with
  cascade-on-source-delete, set-null-on-target-delete. Index on
  `source_session_id` + `created_at` for fast per-session listing.
- [x] `store.record_reorg_audit` / `list_reorg_audits` /
  `delete_reorg_audit` helpers; all three write routes
  (move/split/merge) record an audit after commit and return its
  id in the response.
- [x] `POST /api/sessions/{id}/reorg/merge` — drains every message
  from source into target in insertion order, optional
  `delete_source` flag. Response mirrors move/split:
  `{ moved, target_session_id, warnings, audit_id }`.
- [x] `GET /api/sessions/{id}/reorg/audits` + `DELETE
  /api/sessions/{id}/reorg/audits/{audit_id}` for frontend
  listing + undo cleanup.
- [x] `ReorgAuditDivider.svelte` — inline chronological divider,
  verb per op (Moved / Split off / Merged), clickable target label
  with deleted-session fallback, `data-audit-id` / `data-audit-op`
  for test queries.
- [x] `⇲` Merge button in `Conversation.svelte` header. Opens
  `SessionPickerModal` with `allowCreate={false}` — merge always
  targets an existing session.
- [x] `TimelineItem` discriminated union interleaves turns + audit
  dividers sorted by ISO timestamp so dividers land in the exact
  chronological slot.
- [x] All undo closures (`doMove`, `doBulkMove`, `doSplit`,
  `doMerge`) thread `audit_id` + call `deleteAuditSafe` on
  successful undo. Cascade handles the target-delete case so that
  path skips the explicit audit delete. `doMerge` snapshots source
  message IDs before the merge so undo moves exactly those rows
  back — `move_messages_tx` preserves `created_at`, so "newest N
  on target" isn't safe.
- [x] 23 new pytest (337 total) + 7 new vitest (145 total). All
  quality gates green: ruff + format + mypy strict + pytest +
  vitest.
- [x] Browser smoke verified: merge picker opens with title
  "Merge this session into…", 21 candidate sessions, no create-
  new toggle.

Deferred to later slices (intentional):

- [ ] LLM-assisted analyze (Slice 6) still BLOCKED on token-cost
  Wave 3 (sub-agent researcher). Revisit once that lands.
- [ ] Tool-call-group warnings on split boundaries (Slice 7).
  Currently the response's `warnings: []` arrives but is never
  shown. The toast needs to render them before the Undo button.
- [ ] Prometheus `bearings_session_reorg_total{op}` counter
  (Slice 7).

## v0.3.20 — shipped

Slice 4 of the Session Reorg plan
(`~/.claude/plans/sparkling-triaging-otter.md`): bulk-select mode for
triaging 4+ messages at once. Pure frontend — no backend changes.

- [x] `☐` / `☑` toggle in the session header next to the existing
  ✎/⇣/⎘ trio. Only rendered when a session is selected. Click to
  enter bulk mode; click again (or Esc, or Cancel in the action
  bar) to exit. Exiting clears the selection.
- [x] `MessageTurn.svelte` picks up optional `bulkMode`,
  `selectedIds: ReadonlySet<string>`, and `onToggleSelect(msg,
  shiftKey)` props. When `bulkMode` is true, each article renders
  a checkbox in the header (instead of the per-message `⋯` menu)
  and selected rows get an emerald border + tinted background.
  Checkbox click intercepts default so the parent's shift-aware
  toggle runs first.
- [x] `BulkActionBar.svelte` — fixed bottom-center floating bar
  with `{count} selected`, "Move N…", "Split into new session…",
  and "Cancel". Move/Split disable at `count === 0`; Cancel stays
  live so the user can always exit the mode. Keyboard: `m` fires
  move, `s` fires split, `Esc` fires cancel. Handlers check
  `document.activeElement` against INPUT/TEXTAREA/contentEditable
  and bail if so — typing a prompt doesn't trigger a move. Modifier
  keys (Cmd/Ctrl/Alt) fall through to the browser unchanged.
- [x] Shift-click range selection in `Conversation.svelte`:
  `onBulkToggleSelect(msg, shiftKey)` tracks `lastSelectedId`; if
  shift is held and the anchor is still in `conversation.messages`,
  selects the inclusive `[lo, hi]` slice; otherwise single-toggles.
  Stale anchor (message scrolled out of the window) falls back to
  single-select.
- [x] Picker-op type extended to `'move' | 'split' | 'bulk-move' |
  'bulk-split'`. `pickerBulkIds` snapshots the selection at open
  so the op is stable if the user tweaks selection mid-picker.
  Title + confirm label adapt to the op: "Move 4 selected messages
  to…" / "Split here" etc. `bulk-split` passes `defaultCreating={true}`
  so the picker opens straight into the create-new-session form.
- [x] New `doBulkMove(sourceId, msgIds, targetId, label,
  deleteTargetOnUndo=false)` helper in `Conversation.svelte`.
  Replaces the bespoke move+undo closure in split-into-existing;
  shared by bulk-move and bulk-split flows. `deleteTargetOnUndo`
  cleans up the freshly-created target when an undo cancels a
  move-to-new-session. On success, clears bulk mode + selection
  so the user isn't stuck selecting rows that just vanished.
- [x] `defaultCreating?: boolean` prop added to
  `SessionPickerModal.svelte`. Resets to the flag's value on each
  open. Back button from the create form still works since
  `creating` is a local `$state` var.
- [x] 13 new frontend tests across
  `BulkActionBar.test.ts` (8 — count display, disabled states,
  click callbacks, m/s/Esc shortcuts, modifier passthrough,
  input-focus ignore) and `MessageTurn.test.ts` (5 — menu-vs-
  checkbox render branch, click with shift flag, selected-row
  highlight, checkbox check state). 138 frontend total (up from
  125). Backend untouched — 314 pytest + ruff + mypy strict still
  green.

Deferred to later slices (intentional):

- [ ] Merge route + audit divider (Slice 5): persistent "N messages
  moved to X · Undo" line in the source after a move; undo button
  deactivates at 30s but the divider stays as audit trail.
- [ ] Tool-call-group warnings on split boundaries (Slice 7).
  Currently the response's `warnings: []` arrives but is never
  shown. The toast needs to render them before the Undo button.
- [ ] LLM-assisted analyze (Slice 6) still BLOCKED on token-cost
  Wave 3 (sub-agent researcher). Revisit once that lands.

## v0.3.19 — shipped

Slice 3 of the Session Reorg plan
(`~/.claude/plans/sparkling-triaging-otter.md`): the UI half of the
triage flow. Pure frontend — no backend changes.

- [x] `reorgMove()` + `reorgSplit()` API client functions in
  `frontend/src/lib/api/sessions.ts` with matching
  `ReorgMoveResult` / `ReorgSplitResult` / `NewSessionSpec` /
  `ReorgWarning` types. `warnings` is surfaced now even though it's
  always `[]` pending Slice 7 — keeps the type plumbing work
  one-shot.
- [x] `SessionPickerModal.svelte` — searchable (title / working_dir
  / model), tag-filterable candidate list; inline
  "create-new-session" sub-form with title + tag selection. Arrow
  keys + Enter select; Esc cancels. Callbacks split into
  `onPickExisting(sessionId)` and `onPickNew({title, tag_ids})` so
  the parent dispatches to the right backend route without
  re-parsing the draft.
- [x] `ReorgUndoToast.svelte` — 30-second grace window with a live
  countdown. Runs the caller's inverse-op closure on click;
  auto-dismisses on timeout or explicit ×. Kept the setInterval
  cadence at 250ms so the shown seconds don't drift.
- [x] `MessageTurn.svelte` picks up optional `onMoveMessage` /
  `onSplitAfter` callbacks. When present, a hover-revealed `⋯`
  button on each user / assistant article opens a small popover
  with Move + Split entries; outside-click dismisses. Tests using
  old `MessageTurn` props keep working since the new callbacks are
  optional.
- [x] `Conversation.svelte` orchestrates the full flow:
  * Menu click → opens `SessionPickerModal` in move vs. split mode.
  * `onPickExisting` for move → `reorgMove` with just the one id.
  * `onPickExisting` for split → `reorgMove` with all ids after
    anchor (the existing-session "split into" path).
  * `onPickNew` for split → `reorgSplit` creates the new session
    atomically server-side.
  * `onPickNew` for move → `api.createSession` first (without
    calling `sessions.create` to avoid flipping the selected
    session out from under the user), then `reorgMove`.
  * `reconcileAfterReorg` refreshes the sidebar + active
    conversation so moved rows disappear immediately.
  * Undo closure captures the inverse op and is handed to the
    toast; split's undo also deletes the freshly-orphaned target.
- [x] 12 new tests across `SessionPickerModal.test.ts` (7) and
  `ReorgUndoToast.test.ts` (5). Exercises row exclusion + search
  narrowing + Enter/Escape + inline create validation, and undo
  timer arithmetic + in-flight disable + no-double-dismiss.
- [x] 125 frontend tests pass (up from 113). Backend untouched —
  314 pytest + ruff + mypy strict still green.

Deferred to later slices (intentional):

- [ ] Bulk-select mode (Slice 4): toggle + checkbox per message +
  shift-click + floating action bar. The per-message menu feels
  right for 1–3 row triage, but a session that drifts across 4
  topics (the Checklists failure) wants bulk.
- [ ] Merge route + audit divider (Slice 5): persistent "N messages
  moved to X · Undo" line in the source after a move; undo button
  deactivates at 30s but the divider stays as audit trail.
- [ ] Tool-call-group warnings on split boundaries (Slice 7).
  Currently the response's `warnings: []` arrives but is never
  shown. When Slice 7 ships, the toast needs to render them before
  the Undo button — plumbing for that will be a 2-line Conversation
  change.
- [ ] LLM-assisted analyze (Slice 6) still BLOCKED on token-cost
  Wave 3 (sub-agent researcher). Revisit once that lands.

## v0.3.18 — shipped

Slice 2 of the Session Reorg plan
(`~/.claude/plans/sparkling-triaging-otter.md`): the first user-
facing reorg surface. Two routes, both composed on the Slice 1
`move_messages_tx` primitive.

- [x] `POST /api/sessions/{id}/reorg/move` — body
  `{target_session_id, message_ids[]}`, returns `ReorgMoveResult`
  with `moved` / `tool_calls_followed` / `warnings`. Validates
  non-empty `message_ids` (400), source != target (400), source
  exists (404), target exists (404) before touching the primitive.
- [x] `POST /api/sessions/{id}/reorg/split` — body
  `{after_message_id, new_session: {title, description?, tag_ids[],
  model?, working_dir?}}`, returns 201 with
  `{session: SessionOut, result: ReorgMoveResult}`. Creates the new
  session row inheriting `model` + `working_dir` from source unless
  overridden, validates tag ids (≥1, each must exist), computes the
  move set as every message chronologically after the anchor, and
  420s if nothing is after the anchor (split-at-last is a no-op
  mistake, not a silent success).
- [x] Runner-stop side effect: both routes call
  `runner.request_stop()` on any live runner on affected sessions so
  the SDK's in-memory context rebuilds against the new DB state
  next turn. Move stops both sides; split stops source only (new
  session has no runner yet). Idle runners no-op. The `reason=`
  threading the plan envisioned is deferred — `request_stop` has no
  public reason surface today.
- [x] New Pydantic shapes in `api/models.py`: `ReorgWarning`,
  `ReorgMoveRequest`, `ReorgMoveResult`, `NewSessionSpec`,
  `ReorgSplitRequest`, `ReorgSplitResult`. `warnings` is always `[]`
  in this slice; Slice 7 will populate it with tool-call-group
  split detection without changing the shape.
- [x] Router registered in `server.py` with `/api` prefix so routes
  land at `/api/sessions/{id}/reorg/move` etc. Sits in the APIRouter
  table right after `routes_sessions` since it shares the `/sessions`
  prefix.
- [x] 15 new tests in `tests/test_routes_reorg.py`: move happy-path +
  counts verify, empty-ids 400, same-source/target 400, missing
  source 404, missing target 404, move stops both runners; split
  happy-path + counts + defaults inherit, overrides, tag attach,
  missing source 404, anchor not in session 404, no-messages-after
  400, no tag_ids 400, bad tag_id 400, split stops source runner.
- [x] Seeds messages via a helper that opens a separate aiosqlite
  connection to the same DB file (WAL mode). First `test_routes_*`
  test pattern that needs pre-seeded messages and no WS plumbing;
  kept local to `test_routes_reorg.py` for now — promote to
  `conftest.py` if a second test file wants the same thing.
- [x] 314 backend tests pass (up from 299). Ruff + mypy strict green.

## v0.3.17 — shipped

Slice 1 of the Session Reorg plan
(`~/.claude/plans/sparkling-triaging-otter.md`): the transactional DB
primitive underpinning move / split / merge / archive. No API, no UI
— purely the shared `store.move_messages_tx` helper so Slice 2 (routes)
can compose the user-facing ops on top without re-deriving atomicity.

- [x] New `src/bearings/db/_reorg.py` (101 lines) with
  `MoveResult` (frozen dataclass: `moved`, `tool_calls_followed`) and
  `async def move_messages_tx(conn, *, source_id, target_id,
  message_ids)`. Single-transaction: UPDATE messages, UPDATE tool_calls
  (only anchored — orphan calls with null `message_id` stay on source),
  UPDATE both sessions' `updated_at`, one `conn.commit()` on the happy
  path, `conn.rollback()` on any exception.
- [x] Idempotent by design: the `WHERE session_id = source_id` guard
  means a second call on already-moved ids returns `moved=0` without
  error. `updated_at` only bumps when `moved > 0`, so a no-op retry
  doesn't perturb the sidebar sort order.
- [x] `ValueError` on `source == target` or missing target session.
  Source-missing is tolerated (returns zero counts — no-op). Unknown
  ids in the input set are silently skipped (partial input is fine).
- [x] Observation that supersedes the original plan framing:
  `sessions.message_count` is a `SELECT COUNT(*)` subquery
  (`_sessions.SESSION_COUNT`), not a stored column, so the primitive
  doesn't need a recompute step — next `list_sessions` read picks up
  the new count automatically. Plan notes + Slice 1 TODO item updated.
- [x] Re-exported from `src/bearings/db/store.py` as
  `move_messages_tx` + `MoveResult`.
- [x] 10 new tests in `tests/test_db_reorg.py`: happy-path +
  message_count verify, tool_calls follow anchored message, orphan
  tool_call stays, idempotent re-run, unknown-id skip, empty-input
  noop, `source == target` rejection, missing-target rejection,
  updated_at bump on both sides, no-bump on noop retry. 299 backend
  tests pass (up from 289). Ruff + mypy strict green.

## v0.3.16 — shipped

Wave 1 of the token-cost-mitigation plan
(`~/.claude/plans/enumerated-inventing-ullman.md`): context-pressure
meter + pre-submit budget gate. Addresses the two failures Dave hit
in the session that prompted the plan — (1) research-context-loss
from silent auto-compaction, (2) cost creep from a session that kept
growing past the configured cap. The meter is the "eyes" every later
wave builds on; the budget gate is a cheap blast-radius cap that
refuses a turn *before* it burns tokens instead of after.

- [x] Migration `0013_session_context_usage.sql` adds three cached
  columns — `last_context_pct REAL`, `last_context_tokens INTEGER`,
  `last_context_max INTEGER`. Reason: the SDK only exposes
  `get_context_usage()` while a `ClaudeSDKClient` is alive, so without
  a cache the meter would flicker to blank between turns / on reload.
  `db/schema.sql` back-filled to match.
- [x] `agent/events.py` gains a `ContextUsage` Pydantic event
  (literal discriminator `"context_usage"`) carrying
  `total_tokens`, `max_tokens`, `percentage`, `model`,
  `is_auto_compact_enabled`, `auto_compact_threshold`. Added to the
  `AgentEvent` union so WS serialization and reducer dispatch pick
  it up without bespoke plumbing.
- [x] `agent/session.py` — new `_capture_context_usage(client)` calls
  `client.get_context_usage()` *inside* the `async with
  ClaudeSDKClient()` block (the SDK subprocess tears down on exit,
  so the call has to happen before we leave the context) and
  swallows any SDK exception — an advisory meter must never kill
  a successful turn. The captured event is yielded **before**
  `MessageComplete` because `SessionRunner` breaks its receive
  loop on MessageComplete; yielding after would silently drop the
  snapshot.
- [x] `agent/runner.py` — `submit_prompt()` now checks the session
  row's `total_cost_usd` vs. `max_budget_usd` before queueing. If
  the cap is already met, emits an `ErrorEvent("budget cap
  reached…")` and returns without putting the prompt. This
  complements the SDK's in-turn `max_budget_usd` advisory (which
  only fires after tokens are spent). A new `ContextUsage` branch
  in the turn loop persists the snapshot via
  `store.set_session_context_usage` as the event flows through.
- [x] `db/_sessions.py` — `SESSION_BASE_COLS` extended with the three
  new columns; `set_session_context_usage(conn, session_id, *, pct,
  tokens, max_tokens)` clamps `pct` to `[0, 100]` before the UPDATE.
  Re-exported from `db/store.py`.
- [x] `api/models.py` — `SessionOut` grows `last_context_pct`,
  `last_context_tokens`, `last_context_max` so the cached snapshot
  rides on every session GET without a second round-trip.
- [x] Frontend: `ContextUsageEvent` added to `AgentEvent` union in
  `lib/api/core.ts`; `Session` type grows the three cached fields in
  `lib/api/sessions.ts`. Reducer (`conversation/reducer.ts`) gains a
  `ContextUsageState` slot + `case 'context_usage'` handler. Store
  (`conversation.svelte.ts`) exposes `contextUsage` via `$derived`
  and seeds it from the session row on load so the meter paints
  immediately on first render, not after the next turn.
- [x] New `ContextMeter.svelte` compact pill rendered in the
  Conversation header. Threshold bands shift one earlier when
  auto-compact is off (50/75/90% → 40/60/80%) since there's no
  safety net catching an overflow. Slate / amber / orange / red
  tailwind classes, `aria-label` + `title` carry the full
  `X/Y tokens (Z%)` breakdown on hover.
- [x] Backend tests: 3 new in `test_agent_session.py` pinning
  ContextUsage ordering (before MessageComplete), SDK-exception
  tolerance, and missing-field defaulting; 4 new in `test_runner.py`
  covering persistence on event pass-through, the budget-gate refuse
  path, under-cap allow-through, and the no-cap always-allow path.
  289 backend tests pass (up from 282). Ruff + mypy strict green.
  Frontend: 113 vitest cases pass, svelte-check clean.

## v0.3.15 — shipped

First-turn context priming on fresh runners. Belt-and-suspenders
backup for the SDK's `resume=<sdk_session_id>` path, which is supposed
to rehydrate conversation history on the CLI side but fails silently
when the session file is gone, the cwd has drifted, or the system
prompt has changed. Dave hit this live: came back to a mid-research
session with "hello?", got a "how can I help?" blank slate. Resume
hint still rides along for the cases where it works; the priming
preamble guarantees the immediate context is present regardless.

- [x] `AgentSession` gains `_primed: bool` flag (False at construction,
  True after the first `stream()` call). Ensures the preamble is a
  one-shot per instance — subsequent turns within the same runner
  rely on the SDK's own context chain so we don't duplicate history
  every turn.
- [x] `_build_history_prefix(prompt)` queries the last 10 persisted
  messages (`_HISTORY_PRIME_MAX_MESSAGES = 10`), truncates each
  content field to 2000 chars (`_HISTORY_PRIME_MAX_CHARS`), and
  renders a `<previous-conversation>…</previous-conversation>`
  preamble. Returns None when there's nothing to prime. Dedupes the
  runner's own just-persisted user row so the current turn's prompt
  isn't echoed back inside the preamble.
- [x] Flag is flipped `True` *before* building the prefix so a
  transient DB error can't trap the runner in a re-prime loop — worst
  case is a single missed priming, not infinite retry.
- [x] 5 new pytest cases in `tests/test_agent_session.py` covering:
  preamble prepended on first turn when DB has prior messages; no
  preamble when only the current turn's own user row is in the DB;
  second turn on the same instance gets no preamble; no-db path
  short-circuits; long-message truncation fires with visible marker.
- [x] 282 backend tests pass; ruff + mypy strict green.

## v0.3.14 — shipped

Permission-mode persistence across reconnects and reloads. Closes a
gap where a user in plan / acceptEdits / bypassPermissions mode would
silently drop back to `default` the moment their WS reconnected or
their browser reloaded — the runner's in-memory mode was never
written to SQLite, so the rebuild path couldn't restore it.

- [x] Migration `0012_session_permission_mode.sql` adds
  `sessions.permission_mode TEXT` (nullable; NULL means `default`).
  `db/schema.sql` back-filled to match.
- [x] `_sessions.py` — `SESSION_BASE_COLS` grew the new column;
  `set_session_permission_mode(conn, session_id, mode)` upserts with
  a frozen-set validator (`default` / `plan` / `acceptEdits` /
  `bypassPermissions`) that raises `ValueError` on anything else.
- [x] `SessionOut` DTO exposes `permission_mode: str | None`.
  Frontend `Session` TS type adds the matching union literal.
- [x] `SessionRunner.set_permission_mode` now persists the choice
  after forwarding to the SDK and the approval broker. Non-string
  truthy inputs (malformed wire frames) leave the DB untouched so a
  bad frame can't clobber a good persisted value; invalid strings
  hit the store's ValueError and get logged, not re-raised.
- [x] `ws_agent._build_runner` reads `row.get("permission_mode")` and
  passes it to `AgentSession(permission_mode=...)` so a fresh runner
  picks up where the last one left off.
- [x] `conversation.load()` now returns the session object; the WS
  agent store uses it to hydrate `permissionMode` on connect
  without a second round-trip.
- [x] 4 new pytest cases (2 for the store helper's validator +
  2 for the runner's DB persistence) + frontend test fixture
  updated to carry `permission_mode: null`. All tests pass.

## v0.3.13 — shipped

Desktop/tray notification when an agent turn completes. Opt-in via
Settings; fires only while the Bearings tab is hidden or unfocused so
it stays quiet for the common "watching the reply stream" case. Uses
the browser `Notification` API (localhost counts as a secure context
in Chromium and Firefox), which the DE forwards to KDE Plasma /
mako / GNOME Shell notifications — same path any other app's tray
notifications take.

- [x] `frontend/src/lib/utils/notify.ts` — thin wrapper around
  `Notification` with `notifySupported`, `notifyPermission`,
  `requestNotifyPermission`, and `notify(title, options)`. Handles
  unsupported browsers, un-granted permission, and constructor
  failures silently so callers never have to re-check. Click handler
  focuses the Bearings window and closes the notification.
- [x] `prefs.svelte.ts` — added `notifyOnComplete: boolean` persisted
  to `localStorage` key `bearings:notifyOnComplete` (`'1'` / absent).
  All `prefs.save()` callers updated to pass the new field.
- [x] `Settings.svelte` — new checkbox "Notify when Claude finishes
  replying". Toggling on kicks `requestNotifyPermission()` in the
  same click (not deferred to Save) so the browser's OS-level prompt
  appears while the modal is still open — one less round-trip for
  "I turned it on, why nothing?". Hint copy reflects the live
  permission state (unsupported / blocked / on / off); a browser
  `denied` state disables the checkbox with a "re-allow in browser
  settings" hint.
- [x] `agent.svelte.ts` — WS `message` listener snapshots a
  `fresh` flag BEFORE handing the event to the reducer. For
  `message_complete`, freshness is derived from
  `conversation.completedIdsFor(session_id).has(message_id)` — the
  reducer mutates that set synchronously, so checking after the
  call can't distinguish a real completion from a replayed frame.
  Fresh + opted-in + hidden/unfocused tab → `notify(...)` with the
  session title in the body and a `bearings:complete:<session_id>`
  tag so rapid-fire completions on the same session replace rather
  than stack.
- [x] `conversation.svelte.ts` — exposed `completedIdsFor(id)`
  returning `ReadonlySet<string>` (empty for unknown sessions).
  Read-only API; the reducer remains the sole writer.
- [x] `utils/notify.test.ts` — 7 vitest cases covering: unsupported
  branch for `notifySupported` / `notifyPermission` / `notify` /
  `requestNotifyPermission`, permission short-circuit on granted,
  prompt path on default, no-op on denied, constructor options
  (title/body/tag/icon) on granted, and the click → `window.focus()`
  + `n.close()` handler.
- [x] `Settings.test.ts` — updated `prefs.save` callers to pass
  `notifyOnComplete`.
- [x] `agent.svelte.test.ts` — added mocks for `prefs`, `sessions`,
  and `notify`, a `completedIdsFor` stub on the conversation mock,
  and 3 new cases: fires on fresh + opted-in + hidden; stays silent
  when opt-in off; stays silent on replayed frame (id already in
  `completedIds`).
- [x] 109 frontend tests + 251 backend tests pass; ruff + mypy +
  svelte-check green.

## v0.3.12 — shipped

Selector-vs-modal race fix. Closes the v0.3.11 scope cut: flipping
the header permission selector to `bypassPermissions` /
`acceptEdits` while a `can_use_tool` approval is already parked now
retro-applies the new mode to the pending Future instead of leaving
the modal on screen. The user's "dismiss this wholesale" intent is
honored on the current tool call, not just the next one.

- [x] `approval_broker.py` — `_pending` shape changed from
  `dict[str, Future]` to `dict[str, tuple[str, Future]]` so the tool
  name travels with the Future. New `resolve_for_mode(new_mode)`
  applies the matrix: `bypassPermissions` → allow all parked,
  `acceptEdits` → allow parked edits only (`Edit`, `Write`,
  `MultiEdit`, `NotebookEdit` — `EDIT_TOOLS` frozenset matches the
  SDK), `plan` / `default` → leave parked. Fans
  `ApprovalResolved(decision=allow)` per cleared id so mirroring
  tabs drop their modals. Snapshots the target id list before
  mutating because `can_use_tool`'s finally-clause pops entries the
  moment the Future resolves.
- [x] `runner.py` — `set_permission_mode` is now async and also
  calls `self._approval.resolve_for_mode(mode)`. Forwarding to the
  SDK alone isn't enough: the SDK only consults the new mode on the
  *next* `can_use_tool` call, so without this the user would still
  be stuck clicking through the modal that just became moot.
- [x] `ws_agent.py` — the `set_permission_mode` WS handler now
  `await`s `runner.set_permission_mode` so any `approval_resolved`
  fan-out lands on the wire before the handler returns to the read
  loop.
- [x] 3 new pytest cases in `tests/test_approval.py`:
  `bypassPermissions` clears every parked approval (edit + non-edit);
  `acceptEdits` clears only the edit-class ones and leaves Bash
  parked; `default` / `plan` leave everything parked (regression
  guard against a naive "always resolve" implementation).
- [x] All three existing `_pending` consumers (`resolve`,
  `deny_all` / `_deny_sync`) unpack the new tuple shape. Existing 5
  approval tests still pass; total 8 approval tests, 235 backend +
  94 frontend, mypy + ruff + svelte-check green.

Dave's directive: "there are no preexisint edge cases... You wrote
the entire app if there is a problem you made it. fix it." Done.

## v0.3.11 — shipped

Permission-mode UI correction. Retires the `/plan` slash-command
hijack and the single-mode badge that were shipped in v0.3.5 /
v0.3.10 — both were second-class paths that only ever exposed `plan`,
leaving `acceptEdits` and `bypassPermissions` unreachable from the UI
even though backend + WS + frontend types all supported them. A user
who got stuck under a broken approval prompt had literally no in-app
way to waive further prompts and keep working.

- [x] `PermissionModeSelector.svelte` — header-mounted `<select>` with
  all four modes (`Ask` / `Plan` / `Auto-edit` / `Bypass`). Tone
  escalates slate → sky → amber → rose so Bypass is unmissable. Hint
  copy per mode surfaced via `title` for hover-explainability.
- [x] `Conversation.svelte` — replaces the conditional sky pill with
  the selector; the `nextPermissionMode` intercept in `onSend()` is
  gone so `/plan` no longer eats prompts.
- [x] `conversation-ui.ts` — `nextPermissionMode` and its slash-
  command regex deleted; `PermissionMode` re-export dropped (no
  external importers).
- [x] `agent.svelte.ts` — reconnect persistence. The server-side
  runner resets to `default` on every fresh WS attach, so a drop →
  reconnect used to silently downgrade a user from `bypassPermissions`
  back to `default` and their next tool call would surface an approval
  they thought they'd waived. The new socket's `open` handler re-
  sends the remembered mode as its first frame. `connect()` still
  resets to `default`, so session-switch stays a clean slate.
- [x] 6 new vitest cases in `PermissionModeSelector.test.ts` (renders
  four modes, reflects current mode as selected, tone class per mode,
  dispatches `setPermissionMode` on change, disabled when socket not
  open, hint surfaces in `title`). 2 new vitest cases in
  `agent.svelte.test.ts` cover reconnect persistence (re-sends
  `bypassPermissions`; no-op for `default`). Old
  `nextPermissionMode` describe block deleted.
- [x] 94 frontend tests + 232 backend tests pass; ruff + mypy +
  svelte-check green.

Deliberate scope cuts:
- The badge-vs-modal race noted in v0.3.10 follow-ups: addressed in
  v0.3.12 (see above entry).

## v0.3.10 — shipped

Tool-use approval UI for plan-mode (and any gated tool).

- [x] Backend `can_use_tool` callback wired through
  `ClaudeAgentOptions`. `SessionRunner.can_use_tool` emits an
  `ApprovalRequest` event, parks an `asyncio.Future` per pending
  id, and returns `PermissionResultAllow` / `PermissionResultDeny`
  when resolved. `ws_agent._build_runner` late-binds it to the
  agent so the session stays ignorant of the runner.
- [x] New event types `ApprovalRequest` and `ApprovalResolved` in
  `agent/events.py`. Resolved fans out after each decision so a
  second tab mirroring the same session can drop its stale modal.
- [x] WS `approval_response { request_id, decision, reason? }`
  frame in `api/ws_agent.py`. Unknown / already-resolved ids are
  a no-op so two tabs racing on the same modal is safe.
- [x] Stop + shutdown paths deny every pending approval with
  `interrupt=True` so the SDK unblocks and the stream loop
  reaches its wind-down check. Without this, a park on a pending
  approval would hang the worker indefinitely on stop.
- [x] Ring-buffer replay covers reconnect-mid-approval for free —
  the `ApprovalRequest` event sits in `_event_log` and re-emits
  to any subscriber that reconnects with `since_seq`. No extra
  persistence needed.
- [x] Frontend `ApprovalRequestEvent` / `ApprovalResolvedEvent`
  types in `api/core.ts`, added to the `AgentEvent` union.
- [x] `ConversationStore.pendingApproval` per-session state;
  reducer cases for `approval_request` / `approval_resolved`;
  `clearPendingApproval` for optimistic dismissal after the user
  clicks a button.
- [x] `AgentConnection.respondToApproval(id, decision, reason?)`
  sends the WS frame and clears the modal optimistically.
- [x] `ApprovalModal.svelte` — non-dismissable overlay with
  Approve / Deny. ESC is swallowed at capture-phase so no other
  handler can accidentally resolve the gate. Disabled state +
  "Reconnecting…" hint when the socket is down.
- [x] 5 new pytest cases in `tests/test_approval.py` (round-trip,
  deny-with-reason, unknown-id no-op, stop denies pending,
  shutdown denies all). 7 new vitest cases for the modal + 4 for
  the reducer (`approval_request` sets, matching `approval_resolved`
  clears, mismatched id ignored, `clearPendingApproval` id-gate).
- [x] 232 backend tests + 89 frontend tests pass; ruff + mypy green.

Deliberate scope cuts (follow-ups):
- Badge-vs-modal race: if the user clicks the sky `/plan off`
  badge while an `ExitPlanMode` approval is pending, the mode
  flip does NOT auto-resolve the modal. User has to click
  Approve / Deny. Considered surprising UX but simpler than
  wiring a permission-mode-change → pending-approval canceller
  with the right semantics for non-ExitPlanMode gated tools
  (Edit, Bash) that the badge shouldn't resolve.
- "Deny and stop" single button: today the Stop button already
  denies pending approvals via `request_stop`, so the two-button
  modal + Stop button covers the intent without a third button.

## v0.3.0 — shipped

- [x] StreamEvent handling in `agent/session.py`: `content_block_delta`
  with `text_delta` / `thinking_delta` payloads now surface as live
  `Token` / `Thinking` wire events. `TextBlock` / `ThinkingBlock` in
  the trailing `AssistantMessage` are skipped when deltas already
  fired for that message, so the UI receives real token streaming
  without duplication. 4 new cases in `test_agent_session.py`
  (172 backend tests total).

## v0.3.1 — shipped

- [x] Resizable / collapsible side panes in `+page.svelte`: drag
  handles between sidebar/conversation and conversation/inspector,
  200px minimum with snap-to-collapse below that, max 50% of
  viewport, 16px / 48px (+Shift) keyboard-arrow nudges, Enter / Space
  toggles collapse. Widths + `lastLeft` / `lastRight` (pre-collapse
  restore values) persisted to `localStorage` key `bearings:panes`.
  +page.svelte is 244 lines (under the 400-line cap). Browser
  walkthrough entry added to `TESTING_NOTES.md`.

## v0.3.2 — shipped

- [x] Headless-window support, two paths. **PWA**: new
  `frontend/static/` dir with `manifest.webmanifest`,
  `icon.svg` + `icon-192.png` + `icon-512.png` (rsvg-convert from
  the SVG), `favicon.png`. `app.html` links the manifest, icons,
  and `theme-color`. Chromium install button creates a standalone
  dock-docked window. **CLI**: new `bearings window` subcommand
  autodetects Chromium-flavored browsers on PATH
  (google-chrome-stable, chromium, brave, edge) and spawns
  `BROWSER --app=URL` detached. `--browser PATH` override. 6 new
  tests in `test_cli_window.py` (178 backend tests total).

## v0.3.3 — shipped

- [x] **TagEdit + NewSessionForm polish**. "Sort" relabeled to
  "Order" with a hint tooltip. Default-model free-text input
  replaced with a `<ModelSelect>` dropdown (claude-opus-4-7 /
  sonnet-4-6 / haiku-4-5-20251001 + "Custom…" escape-hatch for
  dated or future IDs). Default-working-dir replaced with a
  `<FolderPicker>`: text field + Browse toggle that opens an
  inline tree browser (breadcrumb, ⬆ parent, toggle hidden, "Use
  this folder"). New `GET /api/fs/list?path=&hidden=` endpoint
  backs it — absolute-path only, resolves symlinks, 404 on
  missing/file targets. 8 new backend tests + 9 new frontend
  tests (186 backend / 48 frontend total).

## v0.3.4 — shipped

- [x] **FolderPicker → display + modal dialog**.
  `FolderPicker.svelte` rewritten: the text input + "Browse" button
  became a single clickable path (placeholder `click to choose…`
  when empty). Clicking opens a modal overlay matching
  `Settings.svelte`'s style — same breadcrumb / parent / hidden
  toggle / subdirectory grid, plus a Cancel button so closing
  without applying no longer requires toggling Browse twice. ESC
  also closes. `Use this folder` writes the current path back to
  the trigger and closes. Applies to TagEdit and NewSessionForm
  alike (no caller changes — the component's prop API
  (`bind:value`) is unchanged). 1 new test case (Cancel preserves
  value), 4 existing cases rewritten for the button-trigger surface.
- [x] **Default model → `claude-opus-4-7` everywhere the frontend
  falls through.** `NewSessionForm.svelte` initial state and the
  final fallback (when both attached-tag defaults and
  `prefs.defaultModel` are empty) now land on opus-4-7, matching
  the backend `config.py` default and the README. Settings modal
  placeholder + `_sessions.py`'s imported-session fallback updated
  for consistency.

## v0.3.5 — shipped

- [x] **Project rename Twrminal → Bearings.** Package, CLI, env prefix,
  XDG paths, systemd unit, repo URL, localStorage keys, frontend
  package name, icon (ball-bearing SVG across 192/512 PNG). Live
  cutover: old systemd unit disabled, data moved
  `~/.local/share/twrminal` → `~/.local/share/bearings` with DB
  preserved, new unit serving on 127.0.0.1:8787. GitHub repo
  renamed; `origin` updated.
- [x] **Patina dashboard button.** Ball-bearing SVG at
  `~/Projects/Patina/assets/icons/bearings.svg`, `bearings` added to
  Patina's `ALLOWED_COMMANDS`, button inserted between Firefox and
  Kitty in `content.json`. `~/.local/share/applications/bearings.desktop`
  registered via `update-desktop-database`. Root cause of the
  "clicked three times, nothing happened" bug: Patina's systemd
  service `PATH` didn't include `~/.local/bin`; fixed by adding
  `Environment=PATH=%h/.local/bin:…` to `patina.service`.
- [x] **Inspector pane collapsed by default.** `+page.svelte`
  fallback seeds `right: 0, lastRight: DEFAULT_RIGHT_PX` so first
  handle-click opens to the default width.
- [x] **Turn-grouped rendering.** User prompt → collapsed-by-default
  `thinking` block (live while streaming) → collapsed-by-default
  `tool work · N` block (live while streaming) → final assistant
  reply (always expanded, not collapsible). Extracted
  `buildTurns` (`$lib/turns.ts`) + `MessageTurn.svelte`;
  `Conversation.svelte` back under the 400-line cap.
- [x] **Copy buttons.** Small `⎘ copy` under each assistant reply,
  copy-session-as-markdown button beside the JSON download icon in
  the conversation header.
- [x] **Plan mode as a first-class slash command.** `/plan` toggles
  permission_mode; `/plan on|off` sets explicitly. Sky badge in the
  header mirrors active mode; click to exit. WS gains a
  `set_permission_mode` message type that routes to
  `ClaudeSDKClient.set_permission_mode`.
- [x] **SDK session continuity.** `AgentSession` captures
  `AssistantMessage.session_id` and passes it back as `resume=` on
  every subsequent `stream()`, so a fresh SDK client per turn
  inherits the CLI-side conversation. Migration 0010 adds
  `sessions.sdk_session_id` so this survives WS reconnects.
- [x] **Frontend icon fix.** `frontend/static/icon.svg` was left
  showing "Tw" after the sed rename; redesigned to the ball-bearing
  mark. `icon-192.png`, `icon-512.png`, `favicon.png` regenerated
  via `rsvg-convert`.

## v0.6.x — Directory Context System (open)

**Version retargeted 2026-04-22.** The original `v0.4.x` label was
drafted before Checklist Sessions claimed `v0.4.0` / `v0.4.1` and
Slice 4 + polish took `v0.5.0` / `v0.5.1`. Directory Context System
now lands as the next new-primitive minor bump, `v0.6.0`. Section
body otherwise unchanged from the v0.4 draft.



Per-directory ground truth on disk so any session that lands in a
directory can read `.bearings/` and know what's happening here
instead of relying on ephemeral chat memory. Diagnosis the design
leans on: an agent's claims about the world should never be
trusted over what's actually written down. Directly addresses the
class of bug the Twrminal transcript demonstrated — a session
opening blind and improvising.

### Scope (from the v0.4 spec Dave drafted)

Each tracked directory gets a `.bearings/` folder:

```
.bearings/
├── manifest.toml     # identity — slow-changing
├── state.toml        # per-session belief about current state
├── pending.toml      # operations in flight (THE key file)
├── history.jsonl     # append-only session log
└── checks/on_open.sh # optional user-written health probe
```

### Decisions resolved 2026-04-22

- [x] **CLI namespace** → namespace the new one: `bearings here
  init` / `bearings here check`. Renaming the existing `init`
  would break muscle memory and systemd/docs references.
- [x] **"Session" vocabulary** → `history.jsonl.session_id` is the
  **Bearings row id**. Stable across reconnects, visible in the DB;
  the SDK session id churns and directory-history ids would be
  circular.
- [x] **Directory-session boundary** → WS connect/disconnect
  lifecycle. Clean hook points already exist in `ws_agent.py`.
- [x] **Confirmation UX for onboarding** → brief is the first
  assistant message; user replies "yes" or edits; agent writes on
  confirm. TTY `[Y/n]` prompt doesn't fit the browser UI.
- [x] **Claude-Code-terminal awareness** → Bearings WebUI only for
  v0.6.x. Shell-init hooks are a rabbit hole; terminal sessions can
  read `.bearings/*.toml` manually. Revisit post-v0.6.
- [x] **Version sequencing** → phased across v0.6.0 / v0.6.1 /
  v0.6.2 / v0.6.3+. Each slice is independently revertable.

### v0.6.0 — foundation (shipped 2026-04-22)

- [x] **Pydantic schemas** for all five file shapes
  (`Manifest`, `State`, `Pending`, `HistoryEntry`, plus the
  `PendingOperation` sub-model) in `bearings_dir/schema.py`.
  Validators cap field lengths (`description` ≤ 500, history
  `summary` ≤ 200, notes/commits/operations lists ≤ 64). Invalid
  files moved to `.bearings/corrupted-YYYYMMDDHHMM-<name>` with a
  `.reason` sidecar and treated as missing so the next session re-
  onboards instead of crashing.
- [x] **Atomic read/write helpers** in `bearings_dir/io.py`:
  tempfile + `os.replace` (same filesystem, `fsync` before rename)
  so a crash mid-write can't corrupt the target. File-level
  `fcntl.flock` on Unix (shared for reads, exclusive for writes);
  Windows documented as single-session-only — the lock functions
  no-op there so dev on Windows still works.
- [x] **Onboarding ritual** in `bearings_dir/onboard.py` — all
  seven steps: identify (primary-marker scan + README head),
  git state (status/stashes/merge-rebase markers), environment
  (venv + `uv sync --locked --dry-run` + language pins), related
  (sibling clones under `$HOME/{Projects,code,dev,src}`),
  unfinished (TODO grep + narrative heads + the **naming-
  inconsistency grep** that surfaces the Twrminal case as a note,
  not a defect), tag-match (prefix match against caller-supplied
  tag rows — no DB coupling in v0.6.0), and `render_brief()` for
  human-readable output. The ritual is pure-read; the CLI/WS
  handler owns the confirm-and-write.
- [x] **`bearings here init`** — runs the ritual and writes
  manifest + state + empty pending.
- [x] **`bearings here check`** — re-runs steps 2/3/5 and bumps
  `state.toml.environment.last_validated`.
- [x] **`bearings pending` CRUD** — `add <name>`, `resolve <name>`,
  `list`, idempotent on name (preserves `started` across re-
  notices so 30-day stale-op detection in v0.6.1 stays
  meaningful). Full Python API in `bearings_dir/pending.py` + CLI
  in `cli.py`.
- [x] **Tests** — 45 new tests across `test_bearings_dir_{schema,
  io,pending,onboard,cli}.py`. Covers the schema caps, corrupt-
  file quarantine, a concurrent-writer test (20 rewrites from two
  threads — final file still parses), the Twrminal naming-
  inconsistency false-positive, `run_check` idempotence, and the
  full CLI surface. All 509 pytest tests green, ruff/mypy clean.

### v0.6.1 — session-layer integration

- [ ] **`history.jsonl` session lifecycle writer.** Session-start
  appends a marker (`started`, `session_id`, `branch`); session-end
  updates with `ended`, `commits`, `summary`. If the end hook never
  fires (crash), the start marker stays on disk so the next session
  can see the prior one ended unclean.
- [ ] **Prompt pipeline layer.** New `LayerKind = "directory_bearings"`
  inserted between `tag_memory` and `session` in
  `assemble_prompt()`. Sourced from manifest summary, state
  environment block, all pending ops, last 10 history lines. Size
  cap ~800 tokens. Per-turn filesystem reads (same cadence as tag
  memories today).
- [ ] **Stale-state detection.** At session start, read
  `state.toml.environment.last_validated`. If > 24h, re-run the
  cheap checks (step 3). If > 7 days, re-run steps 2+3+5. If a
  pending operation's `started` > 30 days old, flag in the brief
  as "stale, may already be resolved."

### v0.6.2 — automatic onboarding

- [ ] **Auto-trigger on WS-open.** When a Bearings session opens in
  a directory without `.bearings/`, generate and present the brief
  as the first assistant message. User confirms in chat prose.
  Agent writes the files on confirm.
- [ ] **Dogfood against `~/Projects/Bearings` itself.** First
  `.bearings/` ever written lives here. The test case that matters:
  the step-5 grep finds "Twrminal" in `CHANGELOG.md` and the brief
  reports it as *historical record, not a rename in progress* —
  not as a problem. This false-positive copy ships in the test
  fixture.

### v0.6.3+ — polish

- [ ] **`checks/on_open.sh` execution framework.** Spawn with
  timeout, capture stderr, attach exit code + stderr snippet to
  the brief. No plugin system; shell script is the API.
- [ ] **`bearings status` / `bearings log` / `bearings pending list`
  polish.** Color, terminal-aware formatting, `--last N`.
- [ ] **Read-only filesystem graceful degrade.** If `.bearings/`
  can't be written, onboarding succeeds and presents the brief but
  skips the write with a warning. Brief still reaches the session
  prompt; only persistence is lost.

### Explicit non-goals (deferred)

- Cross-directory state; each `.bearings/` is independent. Shared
  knowledge lives in Bearings' tag memories.
- Remote sync of `.bearings/`. Local only. User can `git add` it
  or `.gitignore` it.
- GUI editor for bearings files; TOML is editable enough.
- Plugin system for `checks/`; shell scripts are the API.
- Encryption; the files carry no secrets.
- Versioning of bearings files; git covers history when the
  directory is a repo.

## Decisions pending

- [x] GitHub org for remote push: `Beryndil/Bearings`.

## Intra-call tool output streaming (flagged, scoped)

Goal: in the terminal-style tool-work pane, have each call's stdout land
line-by-line as it's produced — not dumped whole at `tool_call_end`.
Matters for long-running `Bash` (e.g. `npm run build`, large searches)
where today the user stares at amber `●` for 30s, then a wall of output
appears. Frontend (MessageTurn.svelte, Inspector.svelte) already reacts
to `tc.output` reactively and auto-scrolls; no component change needed
downstream.

### Blocking investigation (do first)

- [ ] **Verify SDK custom-tool registration in `claude-agent-sdk` 0.1.63.**
  Grep `.venv/lib/python3.12/site-packages/claude_agent_sdk/` for a way
  to register an in-process Python callable as a tool the model can
  invoke. If present, this unlocks Path B (below) without a fork.
- [ ] **Protocol trace of `subprocess_cli.py`.** Dump the raw JSON the
  Claude CLI sends over stdout during a long Bash call to confirm
  whether partial tool output is ever emitted on the wire. If the CLI
  only sends complete `ToolResultBlock`s, Path A gets you nothing —
  the limitation is in the closed-source CLI.

### Paths

- **Path C — Synthetic-delta spike (2–3h).** Add `ToolOutputDelta`
  event + reducer + fake backend emission (split final output into
  chunks with setTimeout). Proves frontend + event schema end-to-end.
  De-risk step before committing to A or B.
- **Path B — Bearings-owned Bash tool via SDK custom tool (6–10h).**
  Register an in-process Bash implementation; run the subprocess
  locally; stream chunks to the WS event bus; return final combined
  output to the SDK synchronously. No fork. Cleanest path *if SDK
  exposes custom-tool registration*.
- **Path A — SDK fork + subprocess stream parsing (8–16h + merge tax).**
  Fork `claude-agent-sdk`, modify `_internal/transport/subprocess_cli.py`
  to emit partial chunks as the CLI streams bytes. Only viable if the
  protocol trace confirms the CLI actually sends partial output.

### Files that change (shared across paths)

- `src/bearings/agent/events.py` — add `ToolOutputDelta` Pydantic model
  + extend event union.
- `src/bearings/agent/session.py` or `runner.py` — emit deltas (source
  differs by path).
- `frontend/src/lib/api/core.ts` — add `ToolOutputDeltaEvent` + union.
- `frontend/src/lib/stores/conversation.svelte.ts` — new case appending
  `event.delta` to the matching `tc.output`; ignore deltas when
  `tc.finishedAt !== null` (guard against out-of-order).
- No change to `MessageTurn.svelte` / `Inspector.svelte` / `schema.sql`.

### Gotchas (must be handled, not just listed)

- **Reconnect mid-tool**: WS drop loses unseen chunks. Persist the
  cumulative `output` to DB on each delta (idempotent update) so
  history endpoint stays authoritative.
- **Chunk boundaries**: split-mid-UTF-8 corrupts multibyte characters;
  split-mid-ANSI-escape breaks color. Backend buffers until a newline
  (or complete codepoint minimum) before flushing.
- **Memory cap**: pathological 1GB tool output shouldn't balloon the
  browser store. Cap `tc.output` to e.g. 5MB in the reducer, mark
  `truncated: true`.
- **Event ordering**: rely on the ring buffer's `_seq`. Reducer drops
  deltas whose target call is already finished.

### Decision

Path C first (proves the pipe). Then Path B if SDK supports it. Path A
only if B is unavailable and the protocol trace justifies it. If
protocol trace shows the CLI itself buffers, kill the feature with a
dated note in this TODO explaining why — genuine upstream limit, not a
Bearings shortcoming.

## Ops / service

### 2026-04-21 — bearings.service went offline, did not auto-recover

- **What happened:** Service received a clean SIGTERM at 15:45:19 CDT and
  shut down gracefully. Not OOM (system had 15Gi free, no dmesg OOM
  events, process peaked at 2.2G). Not `systemctl --user stop` (journal
  has no "Stopping bearings.service" line). Not shell-initiated (no
  `kill`/`pkill`/`stop` in `~/.config/zsh/.zsh_history`). Signal source
  unidentified — something outside the systemd cgroup signaled PID
  3025759 directly. No restart because `Restart=on-failure` treats clean
  TERM as success.
- **Fix shipped:** Unit at `~/.config/systemd/user/bearings.service`
  changed to `Restart=always`, `RestartSec=3`, with
  `StartLimitIntervalSec=60` / `StartLimitBurst=5` to prevent flap loops,
  and `SuccessExitStatus=143` so a clean TERM still counts toward the
  burst budget. Backup at `bearings.service.bak`. Reloaded, restarted,
  verified `/api/health` 200.
- **Still to do:**
  - [ ] Identify the TERM sender next time it happens. Add an `ExecStopPost`
        hook that dumps `/proc/self/status` + `last` + `loginctl` state,
        or enable audit rule `-a always,exit -F arch=b64 -S kill -F
        a1=15 -k bearings_term` so the sender is captured.
  - [ ] Consider `MemoryMax=4G` (soft guard; current peak 2.2G leaves
        headroom, but Slice-5+ reorg work could grow the footprint).

### 2026-04-21 — slice 5 frontend shipping a request the backend doesn't serve

- `GET /api/sessions/{id}/reorg/audits` returned 404 in the logs right
  before the outage (unrelated to the shutdown — process was healthy
  after). The `ReorgAuditDivider.svelte` component expects that route.
- Needs: register the audits route in `src/bearings/api/routes_reorg.py`
  and back it with the `0014_reorg_audits.sql` table, or feature-gate
  the frontend fetch until the route lands.

## Performance optimization

### 2026-04-21 — Audit: frontend timeline re-derivation

**Static analysis (Conversation.svelte + turns.ts + reducer.ts):**

- Per WS event the reducer mutates one of `streamingText`, `streamingThinking`,
  or replaces `state.toolCalls` with `.map()` (every `tool_output_delta` /
  `tool_call_end`). All three feed `$derived` getters on `ConversationStore`.
- `Conversation.svelte` has two stacked `$derived` blocks downstream:
  1. `turns = $derived(buildTurns({...}))` — O(messages + toolCalls) per fire:
     allocates a fresh `Map<messageId, LiveToolCall[]>`, walks every message,
     allocates a new `Turn[]`.
  2. `timeline = $derived.by(...)` — O(turns + audits) plus an O(n log n)
     **sort** by ISO timestamp. Allocates a new `TimelineItem[]`.
- Highest-frequency triggers: `token`, `thinking`, `tool_output_delta`,
  `tool_call_end`. On a typical streaming turn (~30 tok/s plus tool deltas),
  worst case is ≥30 buildTurns + timeline rebuilds per second.
- Open question: Svelte 5's `$derived` is lazy + memoized within a microtask,
  so rapid back-to-back state mutations may collapse to a single recompute
  per frame. **This is the question the instrumentation answers** — without
  numbers, we can't tell whether the rewrite is worth the risk.

**Instrumentation in place:**

- `frontend/src/lib/components/Conversation.svelte` now has two
  `console.count` calls (DEV only) on the `turns` and `timeline` derivations,
  tagged `bearings:audit:buildTurns` and `bearings:audit:timeline`.

**Reproduction:**

1. `cd frontend && npm run dev`
2. Open the UI, pick a session, send a prompt that produces a long
   tool-heavy reply (e.g. a Bash command with streaming output).
3. Watch the DevTools console. Compare counter increments against:
   - WS event count (Network tab → WS frames),
   - approximate token rate from the model.
4. If counters track WS events ~1:1 → confirmed hot, proceed to refactor.
   If counters fire ≪ WS events (batched per frame) → close the audit, the
   `$derived` scheduler already mitigates it.

**Measured 2026-04-21 (one tool-heavy turn: 3 bash commands + summary
paragraph; estimated ~200–300 WS frames):**

- `bearings:audit:buildTurns`: **224 fires**
- `bearings:audit:timeline`:  **227 fires**

Ratio to estimated WS frames is essentially 1:1. Svelte's `$derived`
scheduler is **not** batching these — every WS event walks the full
message + tool-call list in `buildTurns` and rebuilds + resorts the
whole `timeline`. The 3-fire gap is `timeline` reacting to the
`audits` array fetched on session load, which `buildTurns` doesn't
see. **Audit verdict: hot. Refactor is justified.**

**Refactor sketch (only if confirmed hot, and only after sibling
`Profile event frequencies before deeper work` lands real numbers):**

- Promote `turns` and `timeline` from `$derived` to `$state` arrays held
  inside `ConversationStore`, keyed by session id.
- Build the full array once on `load(sessionId)` and `loadOlder()`.
- Mutate the **tail turn** in place during streaming: push tokens into
  `tail.streamingContent`, append tool calls to `tail.toolCalls`. Push a
  new tail on `message_complete`.
- Insert audits at their sorted position only on `refreshAudits()` —
  audit timestamps don't shift mid-stream, so no per-event resort.
- Keying via `{#each timeline as item (item.key)}` already in place; just
  needs the underlying array to mutate-in-place rather than re-allocate.

**Cleanup ticket:** remove the two `console.count` calls before merging
the refactor (or sooner if the audit closes inconclusive — they're noise
in DevTools either way).

### 2026-04-21 — Profile event frequencies (wire + DB)

Pulled `/metrics` and queried SQLite to confirm which event types
dominate and whether historical volume justifies FTS5 and/or timeline
virtualization before we build them.

**Wire event mix** (one process lifetime: 40 assistant turns, 299 tool
calls; captured `bearings_ws_events_sent_total` via
`curl /metrics`). Share of total = 2369 events emitted:

| type              | count | share  | per assistant turn |
|-------------------|------:|-------:|-------------------:|
| token             |  1561 | 65.9%  |              39.0  |
| tool_call_start   |   300 | 12.7%  |               7.5  |
| tool_call_end     |   299 | 12.6%  |               7.5  |
| thinking          |    88 |  3.7%  |               2.2  |
| message_start     |    41 |  1.7%  |               1.0  |
| context_usage     |    40 |  1.7%  |               1.0  |
| message_complete  |    40 |  1.7%  |               1.0  |
| tool_output_delta |     0 |  0.0%  |               0.0  |

- `token` dominates at 2/3 of all frames — this is the wire-volume
  bottleneck.
- `tool_call_*` pairs are the second-biggest block at 25% combined.
- Average turn = ~60 wire events. The frontend re-derivation audit
  measured 227 fires on one tool-heavy turn, so heavy-turn fan-out is
  roughly 4× the average (variance is real, tail is long).
- `tool_output_delta` never fired in this sample. Either streaming tool
  output is rare in Dave's actual usage or the translator in
  `session.py` doesn't currently emit it for any observed tool shape.
  Worth a follow-up but not a blocker — it can only increase the token
  dominance, not flip the verdict.

**DB / historical scale** (read directly from SQLite):

| metric                                   | value |
|------------------------------------------|------:|
| db.sqlite size                           |  15MB |
| sessions                                 |    41 |
| messages                                 |   518 |
| tool_calls                               | 4 146 |
| avg msgs / session                       |  14.0 |
| avg tool_calls / session                 | 105.5 |
| sessions with >100 timeline items        |    15 |
| sessions with >300 timeline items        |     3 |
| largest session (msgs + tool_calls)      |   580 |

**Verdicts:**

- **Timeline virtualization: justified, schedule after frontend
  re-derivation refactor.** Three of 41 sessions already exceed 300
  timeline items and the largest is 580. Combined with the sibling
  audit's 1:1 re-derivation finding, opening a large session walks
  every item on every WS frame — hundreds of nodes × hundreds of
  frames. Virtualization is only worthwhile *after* the re-derivation
  fix promotes `turns`/`timeline` to `$state` arrays that mutate in
  place; until then, virtualization optimizes rendering of a structure
  that's also being needlessly rebuilt per event. Sequence matters.
- **FTS5 search: stop.** 518 messages and 4146 tool calls in a 15MB DB
  is inside "LIKE scans in milliseconds" territory. Revisit if total
  messages cross ~50k or if a search UX ships and profiling shows
  query latency above ~50ms. Noting the decision here so a future
  session doesn't re-open it without new data.
- **Token event reduction: out of scope for this pass, but flag it.**
  66% of wire frames is token streaming. If the re-derivation refactor
  + virtualization still leave the UI janky under streaming, the next
  lever is token batching on the server (coalesce N tokens per frame,
  like `_flush_tool_buffer` already does for tool output). Do not do
  this pre-emptively — measure first.

**Next checklist items implied:**

- Keep `Performance optimization` open with two live children:
  - Implement frontend re-derivation refactor (sibling; now unblocked
    by these numbers).
  - After that lands, add timeline virtualization for sessions >N
    items (N = 200 as starting threshold, well below the observed 580
    max but above the 100 average).
- FTS5 and token-batching stay off the checklist.

## Security audit (2026-04-21) — pre-public-release

Full findings live in this session's transcript. Three audits ran in
parallel: privilege/agent-autonomy surface, architectural questionable
decisions, exposed-secrets sweep. Secrets sweep came back clean (modulo
identity leaks listed below). The other two converged on the same root
cause: the codebase was built assuming "localhost = safe" and that
assumption is wired into a dozen separate decisions.

### Ship-blockers (fix before first public push)

These are bugs, not preferences — no toggle, just fix.

- [ ] **WS has no Origin check.** `src/bearings/api/ws_agent.py:144-148`.
  Any tab in the same browser can drive the agent. Reject WS handshakes
  whose `Origin` isn't `http://127.0.0.1:<port>` / `localhost`.
- [ ] **Markdown XSS via `marked` + `{@html}` with no sanitizer.**
  `frontend/src/lib/render.ts:104-107` + every consumer that mounts
  `renderMarkdown` output via `{@html}` (`CollapsibleBody.svelte:102`,
  `TagEdit.svelte:221`). Add `isomorphic-dompurify`; pipe `marked.parse()`
  through it. Agent/tool output is attacker-influenced.
- [ ] **`tests/test_tags.py:453,456,507,513`** — `/home/beryndil/Projects/Bearings`
  hardcoded as test fixture. Identity leak in tracked code. Replace with
  `tmp_path` or generic placeholder.
- [ ] **Migrations run with no transaction wrapping, no checksum, no
  downgrade detection.** `src/bearings/db/_common.py:36-49`. Wrap each
  in `BEGIN/COMMIT`; record a checksum alongside the name; refuse to
  start when applied-but-unknown rows exist.
- [ ] **`/api/fs/list` enumerates the entire host.** `src/bearings/api/routes_fs.py:43-57`.
  Clamp to a configured allow-root (default `Path.home()`).
- [ ] **Resolve `CLAUDE.md:12` "Repository TBD"** — pick the org or remove
  the note before the README ships.
- [ ] **Decide on commit-email exposure.** `beryndil@hardknocks.university`
  and `dwhennigan@gmail.com` are in commit history. If either should not
  appear publicly, run `git filter-repo` (or fresh init) before first
  push to a public remote.

### Permission profiles / toggle layer (v0.2 release scope)

Three profiles selected at first run or via `bearings init <profile>`:

- **`safe`** (public default) — auth on with auto-generated token,
  `working_dir` defaults to `~/.local/share/bearings/workspaces/<id>`
  (sandbox subdir, *not* `$HOME`), `setting_sources=[]` so no global
  Claude config inherits, no MCP inherit, no hook inherit,
  `bypassPermissions` mode disabled and not persisted, Origin check
  enforced (overlaps ship-blocker), `/api/fs/list` clamped to working_dir,
  command/skill scanner scoped to project `.claude/` only, default
  `max_budget_usd` ceiling.
- **`workstation`** (middle) — auth on, `working_dir` defaults to `$HOME`
  but Edit/Write requires per-call approval, MCP/hook inherit allowed,
  `bypassPermissions` allowed but ephemeral (not persisted), everything
  else as `safe`.
- **`power-user`** (Dave's current behavior, opt-in) — current defaults
  restored. Startup banner in stdout lists every gate that's open so the
  user sees exactly what they're running.

Each profile is a preset that writes `config.toml`. Every individual
switch is also independently togglable for mix-and-match. Active profile
shown in UI header.

Implementation order:

- [ ] Land all ship-blockers above (they're not behind a toggle).
- [ ] Add config schema for every togglable gate (see findings list).
- [ ] Build the three preset profiles.
- [ ] Add startup banner that prints active profile + which gates are
  open.
- [ ] Rewrite README intro around the profile model.

### High but not ship-blocker (fold into toggle layer)

- [ ] Auth-token-in-WS-query-string + non-constant-time compare.
  `src/bearings/api/auth.py:43-53`.
- [ ] DB file written at default umask (world-readable on multi-user
  boxes). `os.chmod(path, 0o600)` after create.
- [ ] Runner survives WS disconnect for `idle_ttl_seconds=900` (closing
  the browser ≠ stopping the agent). `safe` profile: ttl=0 or much
  shorter.
- [ ] Systemd unit has zero hardening — no `ProtectHome`, `PrivateTmp`,
  `NoNewPrivileges`, `MemoryMax`. `config/bearings.service`.
- [ ] Skill/command scanner walks `~/.claude/plugins` and surfaces
  everything in the UI palette. `safe` profile: scope to project only.
- [ ] `cfg.server.host=0.0.0.0` accepted with no interlock when auth=off.
  Refuse to start if non-loopback bind + no auth + no TLS.
- [ ] No global `max_budget_usd` default — runaway loop is unbounded.

### Cleanup (low priority)

- [ ] `LIKE` query unescaped wildcard DOS. `src/bearings/db/_messages.py:281-298`.
  Use `LIKE ? ESCAPE '\\'` and escape `%` `_` `\` in input.
- [ ] `permission_mode` column has no `CHECK` constraint at SQL level.
  `src/bearings/db/schema.sql:18`.
- [ ] WS subscriber queues unbounded. `src/bearings/agent/runner.py:308-321`.
- [ ] `import_session` accepts arbitrary client-supplied JSON with no
  schema validation, no size cap, bypasses the "every session has ≥1 tag"
  invariant. `src/bearings/api/routes_sessions.py:223-232`.
- [ ] `commands_scan` follows symlinks during `rglob`.
  `src/bearings/api/commands_scan.py:60-77`.
- [ ] Multiple silent `except Exception` swallows in `agent/session.py`,
  `agent/runner.py`, `api/routes_tags.py`. Narrow the catches; surface
  a wire `error` event when a failure persists.

### v0.3+ — OS-level sandbox (DEFERRED, do not surface in "what's next")

**Do not surface this entry when Dave asks "what's next" until the
ship-blockers and toggle layer above have shipped.** This is intentionally
parked for v0.3+ planning, after v0.2 closes.

Once the toggle layer exists, add an opt-in `--sandbox=bwrap` mode that
wraps each session in bubblewrap with a single bind-mounted project dir
(the configured `working_dir`), no `$HOME`, no `~/.claude/`, no `~/.ssh`,
no `/run/user/<uid>/keyring`. Flag "experimental" until proven.

Why deferred:

- `claude-agent-sdk` doesn't expose a clean wrapping point for the CLI
  subprocess. Path is "swap the executable for a `bwrap`-wrapping shim"
  or fork the SDK. Both are real engineering, not a config knob.
- Fights the `power-user` profile by design — Dave wants `$HOME` reach.
  Means a sandbox toggle on top of the profile system.
- Toggle layer + `safe` profile already covers ~80% of the realistic
  threat model for a stranger downloading the app. Sandbox is the
  remaining 20% (defense vs. a jailbroken agent actively trying to
  escape).

When v0.3 planning starts, revisit this entry. Until then: silence.

## Per-session input ergonomics (deferred from 2026-04-22)

Original ask (paraphrased from the prompt lost in the 2026-04-22 mid-turn
incident — see v0.6.1 / `tests/test_runner_replay.py`):

> When I leave a session and come back to it any text I typed and
> didn't enter is gone. I'd also like each session to be able to
> press up or down on the keyboard to navigate input history.

Two discrete UI features, same input surface:

- [ ] **Draft persistence.** Unsent text in a session's composer should
  survive a page reload / tab switch / reconnect. Per-session key (not
  global), cleared on submit. Candidates: `localStorage` keyed by
  `session_id` (lives across reloads, dies on history clear), or
  `sessionStorage` (dies on tab close — weaker but simpler). Probably
  `localStorage` with a small size cap and a TTL so abandoned drafts
  don't accumulate forever.
- [ ] **Arrow-key history navigation.** `↑` / `↓` in the composer walks
  the caller's prior `user` messages for *this session*, newest-first
  on first `↑`. `Esc` or typing past the end restores the in-progress
  draft (don't clobber the user's typing). Scope: per-session only
  (don't leak prompts across sessions). Load from `list_messages(session_id)`
  filtered to role='user', or cache in the store on first use.

Treat as a single small PR (both live in the Conversation composer).
Research + plan before implementing — this is the explicit follow-up
to the 2026-04-22 research session that got eaten by the turn-loss
bug now fixed in v0.6.1.

## Live session list — Phase 2: `/ws/sessions` broadcast — shipped (v0.7.0, 2026-04-22)

Phase 1 shipped in v0.6.2 as a softRefresh poll on the 3-second
running-poll tick (good enough for a single-user localhost workflow,
but with three seconds of visible lag and full-list refetches).

Phase 2 replaces that with a real pubsub broadcast — sub-second
sidebar updates, no per-tick `/api/sessions` refetch:

- [x] Server-wide pubsub in `src/bearings/agent/sessions_broker.py`:
  `SessionsBroker` with bounded per-subscriber queue
  (`SUBSCRIBER_QUEUE_MAX = 500`). Slow subscribers are dropped rather
  than back-pressuring publishers. Helpers: `publish_session_upsert`,
  `publish_session_delete`, `publish_runner_state`.
- [x] Published from every mutation point: `routes_sessions.py`
  (create / update / close / reopen / viewed / delete / import) and
  `runner.py` (turn-start + turn-end via the finally block).
- [x] New route `src/bearings/api/ws_sessions.py` (`GET /ws/sessions`)
  with auth gate mirroring `ws_agent` (4401 on token failure / broker
  absent) and a forwarder-task pattern for per-subscriber pushes.
- [x] Frontend `frontend/src/lib/stores/ws_sessions.svelte.ts`:
  `SessionsWsConnection` with exponential backoff reconnect (cap 30s),
  routes `upsert | delete | runner_state` frames through
  `sessions.applyUpsert / applyDelete / applyRunnerState`.
- [x] Reducer methods added to `SessionStore`: `applyUpsert` (respects
  `local-newer updated_at`, re-sorts by `updated_at DESC, id DESC`,
  no-ops when a tag filter is active), `applyDelete` (clears a
  matching selection), `applyRunnerState` (reassigns the Set).
- [x] Boot wiring: `+page.svelte` calls `sessionsWs.connect()` after
  `startRunningPoll()`. Phase-1 poll kept intact as a
  belt-and-suspenders reconcile — on every (re)connect the WS handler
  also fires one `softRefresh` so anything missed while down
  converges.

Follow-up (keep deferred — poll stays until the broadcast has
earned trust via metrics / uptime):

- [ ] Drop the `softRefresh` call from `startRunningPoll` once the
  broadcast has a few weeks of clean data. `sessions.softRefresh`
  itself stays — it's the reconnect reconciliation path.
- [ ] Drop the `running`-set poll once the broadcast's `runner_state`
  frames have earned the same trust. Requires a reconnect-time
  snapshot of currently-running sessions (the WS currently has no
  replay buffer; either a short `/api/sessions/running` tick on
  connect or a `runner_state_snapshot` frame would work).

## Drag-and-drop file uploads (2026-04-22, initial slice shipped)

Shipped: `POST /api/uploads` bytes-upload endpoint + matching drop
handler in `Conversation.svelte`. Bypasses Chrome/Wayland's
`text/uri-list` stripping by reading `DataTransfer.files[].arrayBuffer()`,
POSTing to the endpoint, and injecting the server-side absolute path
into the prompt. `dropDiagnostic` banner retained as instrumentation
for future compositor/browser regressions.

Config: `[uploads] upload_dir` (default `$XDG_DATA_HOME/bearings/uploads`),
`max_size_mb` (default 25), `blocked_extensions` (default: executables).

Follow-ups:

- [ ] **GC for upload dir.** Time-based sweep of `upload_dir` — e.g.
  delete files older than `uploads.retention_days` (default 30) on
  server start and on a daily timer. Currently the directory grows
  unbounded; low-priority because uploads are small and localhost
  disk is cheap, but it'll accumulate over years of use. Consider
  tying cleanup to session deletion instead (per-session upload
  subdirs) if the attachment-chip work lands first.
- [ ] **Attachment chip above user bubble.** Render a small chip
  (filename + size + click-to-preview-or-open) above the user's
  message when the prompt contains one of our upload paths. Requires
  either persisting the upload metadata alongside the message OR
  teaching the turn renderer to detect `upload_dir`-prefixed paths
  in content and look them up. The `UploadOut` model already carries
  `filename` / `size_bytes` / `mime_type` for this shape; need a way
  to persist them per-turn.
- [ ] **Progress UI for large uploads.** Current fallback fires with
  a static "Uploading dropped file…" overlay; a 25 MB PDF on a slow
  bus is a noticeable pause. Options: XHR with `upload.onprogress`
  (gives real byte-count feedback) or a Fetch-based streaming POST
  with a `ReadableStream` tee. Cheap wins first — a dots-animation
  is probably enough for typical drops.
- [ ] **Batch POST for multi-file drops.** Today each file is a
  separate round-trip. For 10+ small files on a slow link this
  adds up. Not urgent — typical drop is 1-3 files.
- [ ] **Live smoke test on Kubuntu + Hyprland + Chrome.** Tests and
  typecheck are green; the in-browser drop test happens after the
  next server restart (restart would kick the live Bearings session
  — defer until Dave picks his moment).

## Sidebar redesign + severity tags (2026-04-22, shipped)

Shipped: sidebar gets a second tag axis (severity), medallion icons
per session row, and a collapsible density pass.

- [x] Migration `0021_severity_tag_group.sql`: adds `tag_group` column
  (CHECK `general | severity`), seeds five severity tags
  (Blocker / Critical / Medium / Low / Quality of Life) with the
  green→red Tailwind hex ramp, backfills every existing session with
  `Low` via a guarded INSERT OR IGNORE. Idempotent on re-run.
- [x] `attach_tag` enforces exactly-one-severity at the app layer:
  attaching a severity DELETEs any other severity tag on the session
  in the same transaction. Attaching the currently-attached severity
  is a no-op (short-circuit via `tag_id != ?`). Deleting a severity
  tag orphans affected sessions silently — "physical law, not DB
  constraint."
- [x] `list_sessions` takes a new `severity_tag_ids` axis that
  AND-combines with `tag_ids` and OR-combines within the group.
  Rows carry a `tag_ids` array built from a single GROUP_CONCAT
  subquery so the sidebar renders N medallions without an N+1.
- [x] `/api/sessions?severity_tags=<csv>` parses + 400s on bad input,
  same shape as the general-tag path. `POST /api/tags` accepts
  `tag_group` and `color`.
- [x] Frontend: `TagFilterPanel` is collapsible (localStorage key
  `bearings-tag-panel-collapsed`), has an HR between general and
  severity groups, hides Any/All inside severity (always-OR since
  one-per-session), and shows a "N on" chip when collapsed with
  filters active. Density pass: 11-12px type in the sidebar.
- [x] `SessionList` renders a medallion row per session:
  `SeverityShield` + one `TagIcon` per general tag, tinted from the
  DB `color` column. Hand-drawn inline SVG under
  `frontend/src/lib/components/icons/` — no new deps.
- [x] Tests: `tests/test_severity.py` covers migration seed/backfill,
  attach_tag invariants (swap, idempotent, general leaves severity
  alone), delete-orphan, list_sessions filter combinations, and the
  API surface. Frontend tests updated to include `tag_ids: []` on
  Session fixtures and `tag_group: 'general'` on Tag fixtures. All
  569 backend + 221 frontend tests green; svelte-check clean.

Follow-ups:

- [ ] **Server restart required to pick up `tag_ids` in
  SessionOut.** Migration 0021 ran on the live DB when the
  currently-running server booted, so severity seed + Low backfill
  are in place. But the Python `SessionOut` shape is cached in the
  running process — the sidebar medallion row stays empty until
  next restart. No rush (the UI degrades gracefully), but note it.
- [ ] **Per-severity color override in the tag edit modal.** The
  seed colors are a sensible default; some users will want to
  remap (e.g. colorblind-friendly). `PUT /api/tags/{id}` already
  accepts `color` — just needs a color picker in `TagEdit.svelte`.
- [ ] **"No severity" sentinel in the filter panel.** Deleting a
  severity tag orphans sessions silently; there's currently no way
  to filter *for* those orphans. Low priority — either a pseudo-id
  filter or an `IS NULL` axis in `list_sessions`.
