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

### Browser verification pending

Checklist lives in `TESTING_NOTES.md` §"Pending Dave's browser
walkthrough". Every v0.2 UI surface needs exercising; unit tests
cover shape, not feel.

### Other

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

## v0.4.x — Directory Context System (open)

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

### Decisions to resolve before code

- [ ] **CLI namespace.** `bearings init` is already taken (it
  initializes the global config + DB). Either rename the existing
  command (`bearings setup` / `bearings bootstrap`) or namespace
  the new one (`bearings here init` / `bearings dir init`).
- [ ] **"Session" vocabulary.** Three `session_id`s in play: Bearings
  row, claude-agent-sdk session (from v0.3.5), directory-history
  entry. Pick which the `history.jsonl.session_id` field refers to
  (leaning: Bearings row id) and document.
- [ ] **Directory-session boundary.** When does a `history.jsonl`
  line get written — one per WS connection? One per logical
  "visit"? Leaning: WS connect/disconnect lifecycle.
- [ ] **Confirmation UX for onboarding.** Spec's
  `Save this as the directory's bearings? [Y/n]` is a TTY
  affordance. In the browser UI, the natural fit is: brief is the
  first assistant message; user replies "yes" or edits; agent
  writes on confirm.
- [ ] **Claude-Code-terminal awareness.** Is `.bearings/` only for
  sessions started through the Bearings WebUI, or do we also want
  terminal `claude` invocations to pick it up (via a shell-init
  hook or wrapper)? Scope-defining.
- [ ] **Version sequencing.** Big-bang 1→10 in v0.4.0 or phased
  across 0.4.0 / 0.4.1 / 0.4.2? Leaning phased so revert is
  surgical if something's wrong mid-way.

### v0.4.0 — foundation

- [ ] **Pydantic schema** for all five file shapes
  (`Manifest`, `State`, `Pending`, `HistoryEntry`, plus the
  `PendingOperation` sub-model). Validators cap field lengths
  (`description` ≤ 500, history `summary` ≤ 200). Invalid files
  moved to `.bearings/corrupted-YYYYMMDDHHMM.toml` and treated as
  missing so the next session re-onboards instead of crashing.
- [ ] **Read/write helpers** with atomic writes for
  `state.toml` / `pending.toml` (temp file + `os.replace`) so a
  crash mid-write can't corrupt. File-level `fcntl.flock` for
  concurrent-session safety on Unix; Windows documented as
  single-session only.
- [ ] **Onboarding ritual as a command** (name TBD per decision
  above). Seven steps implemented:
  1. Identify — walk up for `.git`, `pyproject.toml`,
     `package.json`, `Cargo.toml`, `go.mod`, `CLAUDE.md`,
     `README.md`. Read first 50 lines of README.
  2. Git state — `git status --porcelain`, stashes, in-progress
     merge/rebase/cherry-pick/bisect markers under `.git/`.
  3. Environment validation — Python venv path sanity, lockfile
     freshness (use `uv sync --locked --dry-run` or lock-vs-site-
     packages diff, not `uv pip check`), language version pins
     (`.python-version`, `.nvmrc`, `rust-toolchain.toml`), DB
     file existence, unapplied migrations.
  4. Related directories — sibling clones with matching remote
     under `$HOME/Projects`, `$HOME/code`, `$HOME/dev`,
     `$HOME/src`.
  5. Unfinished work — `TODO` / `FIXME` / `XXX` / `WIP` grep
     respecting `.gitignore`; read `TODO.md`, `CHANGELOG.md`,
     `TESTING_NOTES.md`; **naming-inconsistency grep** (exact
     Twrminal / Bearings failure mode).
  6. Tag match — `SELECT * FROM tags WHERE ? LIKE
     default_working_dir || '%'` against the Bearings DB.
  7. Present structured brief; on confirm, write manifest + state
     (and pending if ops were detected).
- [ ] **`bearings check` command.** Re-run steps 2, 3, 5; bump
  `state.toml.environment.last_validated`; surface any new
  inconsistencies.
- [ ] **`bearings pending` CRUD** — `add <name>`, `resolve <name>`,
  `list`. Full Python API + CLI. Tests for concurrent writes.

### v0.4.1 — session-layer integration

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

### v0.4.2 — automatic onboarding

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

### v0.4.3+ — polish

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
