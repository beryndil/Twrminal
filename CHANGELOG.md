# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.9] - 2026-04-19

Teardown of projects. Course correction — projects were the wrong
primitive. Tags with memories (already shipped in v0.2.7) carry
the role; tag-level `default_working_dir` and `default_model`
land in v0.2.10 to close the gap. Pinned tag = "project". See
`V0.2.0_SPEC.md` (rewritten this slice).

### Removed

- Migration `0008_drop_projects.sql`: wipes existing sessions
  (none in production at teardown time, per Dave's call), drops
  `idx_sessions_project`, drops `sessions.project_id` column
  (SQLite 3.35+ DROP COLUMN), drops the `projects` table.
- `src/twrminal/api/routes_projects.py` — entire file.
- `src/twrminal/db/store.py` — `create_project` / `list_projects`
  / `get_project` / `update_project` / `delete_project` and their
  helper constants. `NO_PROJECT` sentinel + `ProjectFilter` alias.
- `ProjectCreate` / `ProjectUpdate` / `ProjectOut` DTOs.
- `SessionCreate.project_id` / `SessionUpdate.project_id` /
  `SessionOut.project_id` (backend + frontend TS).
- `GET /api/sessions?project_id=` query filter.
- Project layer in `agent/prompt.py`. The assembler is now 3-layer:
  base → tag memories → session instructions.
- `tests/test_projects.py` and `tests/test_migration_0007.py`
  (the latter asserted the post-0007 shape which no longer matches
  end state; the 0007 migration file itself stays in
  `migrations/` so `schema_migrations` stays consistent).
- Frontend `Session.project_id` field.

### Changed

- `V0.2.0_SPEC.md` rewritten to describe the tags-only design.
  The old projects-included version led this slice's teardown —
  preserved only in git history.
- `db/schema.sql` reconciled — no `projects` table, no
  `project_id` column, no `idx_sessions_project`.
- Prompt-assembler tests trimmed to match the 3-layer shape.
- System-prompt API test trimmed to match.

### Why

Tags carry shared system-prompt content (as memories), shared
working-dir defaults, shared model defaults, and sidebar-pin
behavior. A pinned `twrminal` tag IS the Twrminal project.
Maintaining a second "projects" primitive alongside that was
duplicating surface for no additional capability. Cheaper-than-
expected memory stacking (short pointers, not mirrored document
libraries) closed the gap that projects were meant to fill.

## [0.2.8] - 2026-04-19

Inspector Context tab — read-only view of the assembled system
prompt. Ninth v0.2 slice, spec step 6.

### Added

- `GET /api/sessions/{id}/system_prompt` returning
  `{layers, total_tokens}`. Layers carry `{name, kind, content,
  token_count}` — calls the same `assemble_prompt` the agent uses
  so the Inspector always shows current prompt state. 404 if the
  session doesn't exist.
- `SystemPromptLayerOut` / `SystemPromptOut` DTOs.
- `agent.prompt.estimate_tokens` — coarse 4-chars-per-token
  approximation. Avoids pulling `tiktoken` (heavy dep) for what's
  a visual-only estimate; empty strings count as zero, anything
  else is clamped to at least 1 so non-empty layers aren't
  rendered as 0 tokens.
- Frontend `getSystemPrompt(sessionId)` + `SystemPrompt` /
  `SystemPromptLayer` types.
- Inspector panel: new **Context** disclosure above the existing
  Agent one. On open, fetches the assembled prompt; header shows
  `~N tok`. Each layer renders as a collapsible row with a
  color-coded kind badge (base/project/tag_memory/session). When
  the selected session's `updated_at` changes the next open
  refetches so project/tag/memory edits surface immediately.
- Frontend `Session` type grew `project_id` and
  `session_instructions`. `SessionCreate` accepts `project_id`;
  `SessionUpdate` accepts `project_id` + `session_instructions`.
  Catches the frontend contracts up to the v0.2.6/v0.2.7 backend
  additions — no UI for these edits yet (v0.2.9 / v0.2.11).
- 3 new prompt-assembler tests for `estimate_tokens`.
- 3 new API tests for `/system_prompt` (404, base-only layer
  shape, full four-layer stack).

## [0.2.7] - 2026-04-19

Tag memories backend + `session_instructions` PATCH + wires the
v0.2.5 prompt assembler into the live agent. Eighth v0.2 slice,
spec step 5. Backend is now feature-complete for v0.2; remaining
slices (0.2.8+) are UI.

### Added

- `store.get_tag_memory` / `put_tag_memory` (upsert via `ON
  CONFLICT`) / `delete_tag_memory`. `put` returns None if the tag
  doesn't exist so the route can render 404 without an FK
  violation.
- `/api/tags/{id}/memory` CRUD: `GET` 200 | 404, `PUT` 200 | 404
  (body: `{content}`), `DELETE` 204 | 404. `TagMemoryOut` and
  `TagMemoryPut` DTOs.
- `PATCH /api/sessions/{id}` accepts `session_instructions` — new
  value, or explicit null to clear. `SessionOut.session_instructions`
  exposed on every session response.
- `SessionUpdate.session_instructions` field (Pydantic
  distinguishes unset from explicit null via `model_fields_set`,
  same as the existing nullable columns).
- `store.update_session` `allowed` set grew by
  `session_instructions`.
- `_SESSION_BASE_COLS` includes `session_instructions` so every
  session read (get, list, export) carries it.
- `AgentSession` accepts an optional `db` connection. When set,
  `stream()` calls `assemble_prompt(db, session_id)` per turn and
  passes `system_prompt=<layered text>` to `ClaudeAgentOptions`.
  Edits to project prompts, tag memories, or session instructions
  take effect on the next prompt without restarting the WS. Tests
  that don't exercise persistence leave `db=None` and behave as
  before (no `system_prompt`).
- `ws_agent.py` passes the lifespan-owned DB connection into
  `AgentSession` at construction.
- 13 new store + API tests in `tests/test_tag_memories.py` plus 1
  session-instructions PATCH round-trip.
- 2 new agent-session tests verifying system_prompt is assembled
  from project / tag memory / session instructions when db is
  wired, and stays None when it isn't.

### Changed

- `store.delete_project` is unchanged — cascade to SET NULL on
  `sessions.project_id` was already exercised by v0.2.4's
  migration test. `delete_tag` already cascaded to `tag_memories`
  via FK from migration 0007; new test pins the behavior.

## [0.2.6] - 2026-04-19

Projects backend — store CRUD + REST + session filter. Seventh v0.2
slice, spec step 4. Frontend for projects lands in v0.2.9.

### Added

- `store.create_project` / `list_projects` / `get_project` /
  `update_project` / `delete_project` with `session_count` rollup and
  canonical pinned-first / sort_order / id ordering (mirrors tags).
- `/api/projects` CRUD: `GET` (list), `POST` (201; 409 on duplicate
  name), `GET /{id}`, `PATCH /{id}` (409 on duplicate rename, 404 on
  missing), `DELETE /{id}` (204; sessions' `project_id` becomes NULL
  via `ON DELETE SET NULL`).
- `ProjectCreate` / `ProjectUpdate` / `ProjectOut` DTOs.
- `SessionOut.project_id` — exposed on every session response.
- `POST /api/sessions` accepts `project_id` at creation time.
- `PATCH /api/sessions/{id}` accepts `project_id` (explicit null
  clears the assignment).
- `GET /api/sessions?project_id=<id>` filter. `project_id=none`
  restricts to sessions with no project. Non-integer non-`none` → 400.
- `store.list_sessions(project_id=...)` composes with tag filters
  (both AND'd together; refactored from three branches to one
  dynamic WHERE builder).
- `store.NO_PROJECT` sentinel + `store.ProjectFilter` alias so
  routes don't reinvent the parsing rule.
- 23 new pytest cases covering store CRUD, session_count rollup,
  ordering tiebreakers, cascade-to-SET-NULL, project + tag filter
  composition, and the full REST surface.

## [0.2.5] - 2026-04-19

Layered system-prompt assembler — pure function, no consumers yet.
Sixth v0.2 slice, spec step 3. `AgentSession` wires through in
v0.2.7 once tag-memory + session-instructions CRUD land.

### Added

- `src/twrminal/agent/prompt.py::assemble_prompt(conn, session_id)`
  — async, pure SQL reads, returns `AssembledPrompt(layers, text)`.
  Layer order: `base` → `project` (if the session's project has a
  non-null `system_prompt`) → `tag_memory` layers (one per attached
  tag with a `tag_memories` row, in the canonical `pinned DESC,
  sort_order ASC, id ASC` order; tag-without-memory is silently
  skipped) → `session` (`sessions.session_instructions`, when set).
  `text` joins the layers with `<!-- layer: kind[name] -->` headers
  so downstream renderers can split them back out.
- `src/twrminal/agent/base_prompt.py::BASE_PROMPT` — short,
  deterministic base layer. Real content lives in project / tag /
  session layers.
- 8 new pytest cases in `tests/test_prompt_assembler.py`: base-only,
  missing session, project-with-prompt, project-without-prompt,
  tag-without-memory skip, pinned/sort_order/id tiebreakers,
  session_instructions-last, per-layer header verbatim.

## [0.2.4] - 2026-04-19

Schema migration **0007** — projects, tag memories, session
instructions. Fifth v0.2 slice. No routes yet; CRUD + prompt
assembly land in v0.2.5+.

### Added

- Migration `0007_projects_and_memories.sql`:
  - `projects` (id, name UNIQUE, description, system_prompt,
    working_dir, default_model, pinned, sort_order, created_at,
    updated_at).
  - `sessions.project_id INTEGER REFERENCES projects(id) ON
    DELETE SET NULL` + `idx_sessions_project`.
  - `tag_memories` (tag_id PK/FK, content, updated_at), FK
    `ON DELETE CASCADE` tied to `tags`.
  - `sessions.session_instructions TEXT` nullable — session-level
    override for the assembled system prompt (prompt assembler
    lands in v0.2.5).
- Canonical `db/schema.sql` caught up to the full applied shape
  (tags, session_tags, projects, tag_memories).
- 4 new pytest cases: migration applies (tables + index), columns
  present on `sessions`, project delete NULLs `sessions.project_id`,
  tag delete cascades `tag_memories` rows.

## [0.2.3] - 2026-04-19

Sidebar **click-filter** — fourth v0.2 slice. Closes out the
tag-primitives UI surface that started in v0.2.0. Full spec build
order step 1 (both back- and front-end) is now shipped.

### Added

- `GET /api/sessions?tags=1,2&mode=any|all` — optional filter on
  the session list. `mode="any"` matches sessions carrying any of
  the listed tags; `mode="all"` requires every listed tag. Empty /
  omitted `tags` returns the unfiltered list unchanged. Bad `tags`
  (non-integer) → 400.
- `store.list_sessions(tag_ids=, mode=)` extended to run the join
  + GROUP BY / DISTINCT path when filtering.
- `api.ts` `listSessions` now takes an optional `SessionFilter`;
  the sessions store caches the last-applied filter.
- `tags` store gets `selected: number[]`, `mode: 'any' | 'all'`,
  `toggleSelected()`, `clearSelection()`, plus derived `hasFilter`
  + `filter`.
- Sidebar tag rows become toggle buttons (emerald tint when
  selected), an Any/All toggle sits next to the "Tags" header, and
  a "Filter: N tag(s) ✕" pill appears when the filter is active —
  click to clear.
- SessionList watches the filter and re-fetches sessions on change.
- 5 new pytest cases (store any/all, store empty-filter, API happy
  path, API 400 on bad tags). 3 new vitest cases (toggle, derived
  filter, clearSelection).

## [0.2.2] - 2026-04-19

Attach/detach tags on a session. Third v0.2 slice — first path for
actually putting tags onto something from the UI. Sidebar
click-filter lands in v0.2.3.

### Added

- `TagCreate` / `TagUpdate` types + `createTag` / `updateTag` /
  `deleteTag` / `attachSessionTag` / `detachSessionTag` in
  `frontend/src/lib/api.ts`. The `deleteTag` helper handles the 204
  No Content response explicitly (the shared `jsonFetch` path
  assumes a JSON body).
- Mutation methods on the `tags` store: `create()`, `update()`,
  `remove()`, plus `bumpCount()` for post-attach/detach sidebar chip
  updates without a full refresh.
- **Tags section** in the SessionEdit modal: attached tags render
  as chips (with ★ on pinned) with an ✕ to detach. An input below
  filters global tags by name; click a suggestion to attach, or
  press Enter on a novel name to create-and-attach in one step.
- `SessionEdit.test.ts` covers detach via ✕, suggestion-click
  attach, and the Enter-to-create path.
- Extended `tags.svelte.test.ts` covers `create`, `remove`, and
  `bumpCount` including the clamp-at-zero rule.

## [0.2.1] - 2026-04-19

Sidebar **Tags panel** — read-only. Second v0.2 slice.

### Added

- `Tag` type + `listTags` / `listSessionTags` helpers in
  `frontend/src/lib/api.ts`.
- New `frontend/src/lib/stores/tags.svelte.ts` with a `TagStore`
  singleton (mirrors the shape of `sessions.svelte.ts`).
- Tags section in `SessionList.svelte`: "Tags" header above the
  session list, pinned tags first (with a ★ glyph), then a divider,
  then unpinned. Each row shows a right-aligned session-count chip.
  Section is hidden while sidebar search is active and when no tags
  exist. No click/filter behavior yet — that lands in v0.2.2.
- `+page.svelte` boot now refreshes sessions and tags in parallel
  (`Promise.all`).
- Store test `tags.svelte.test.ts` (success + error path).

## [0.2.0] - 2026-04-19

First v0.2 slice — **tag primitives**. Backend-only: establishes the
global `tags` registry + `session_tags` join table that the sidebar
Tags panel (v0.2.1) and eventual tag memories (v0.2.6+) build on.

### Added

- **Tag primitives.** New migration `0006_tag_primitives.sql` creating
  `tags` (id, name UNIQUE, color, pinned, sort_order, created_at) and
  `session_tags` (session_id, tag_id, created_at). Both FKs cascade
  on delete. `idx_session_tags_tag` keeps per-tag lookups fast.
- **Tag store helpers** in `db/store.py`: `create_tag`, `list_tags`,
  `get_tag`, `update_tag` (partial), `delete_tag`, `attach_tag`
  (idempotent `INSERT OR IGNORE`), `detach_tag`, `list_session_tags`.
  `list_tags` returns a `session_count` rollup per tag; all tag reads
  order pinned-first, then ascending `sort_order`, then `id`.
- **Tag REST surface** (`/api/tags/*`): `GET`, `POST` (201, 409 on
  duplicate name), `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` (204).
- **Session-tag endpoints** on the sessions router: `GET
  /api/sessions/{id}/tags`, `POST /api/sessions/{id}/tags/{tag_id}`,
  `DELETE /api/sessions/{id}/tags/{tag_id}`. Attach/detach bumps
  `sessions.updated_at` so a tagged session floats to the top.
- New DTOs `TagCreate`, `TagUpdate`, `TagOut` in `api/models.py`.
- 25 new tests in `tests/test_tags.py` covering migration shape,
  CRUD round-trips, idempotent attach, cascade on tag delete and
  session delete, unique-name 409, ordering, and every new endpoint
  including missing-session and missing-tag paths.

### Fixed

- `db/schema.sql` now includes the `sessions.description` column
  from v0.1.40 (previously missed during that slice's canonical-file
  update). Schema file is back in sync with applied migrations.

## [0.1.40] - 2026-04-19

### Added

- **Editable session descriptions.** New `description TEXT` column on
  `sessions` (migration `0005_session_description.sql`) surfaces a
  free-form context note for each session — longer than the title,
  shorter than the conversation. Wired through `SessionCreate` /
  `SessionUpdate` / `SessionOut`, a new textarea in the SessionEdit
  modal, and a subtle render under the Conversation header subtitle
  when set. Preserved through the v0.1.30 export/import shape.
- Three new route tests: description round-trip, patch-update,
  patch-null clears.

## [0.1.39] - 2026-04-19

Docs/housekeeping only — no code change. Brings the two pieces of
project documentation that drifted during the v0.1 sprint back in
line with reality.

### Changed

- `README.md` rewritten: removed the "v0.1.0 scaffold… stubbed" prose
  that had survived 38 shipped versions, added a Features summary
  (streaming, CRUD, import/export, auth, budgets, metrics, search,
  shortcuts, CLI `send`), and widened the config table to cover
  `auth.token`.
- `TODO.md` reconciled: the three "v0.1.7+" stragglers (auth gate,
  graceful shutdown, budget cap) had all shipped — ticked and moved
  under a "Stale items resolved in earlier slices" subsection with
  pointers to the slice that landed each one.

## [0.1.38] - 2026-04-19

Closes out v0.1. Two tweaks and the first testing-notes pass.

### Changed

- Prompt send rebound: **Enter sends, Shift+Enter newlines** (was
  `⌘/Ctrl+Enter` / Enter newline). IME composition respected.
  CheatSheet and placeholder updated to match.

### Added

- Inspector "Agent" disclosure: tool-call list now nested under a
  collapsible `<details>` summary showing the session model + a
  running count badge. Auto-follows scroll to the latest tool call
  while the agent is streaming (effect watches
  `conversation.toolCalls.length` + `streamingActive`).
- `TESTING_NOTES.md` at the project root — session-by-session log of
  what Dave found and what got fixed.

## [0.1.37] - 2026-04-19

### Added

- Multi-file session import: drop a directory's worth of
  `session-*.json` onto the sidebar (or pick several in the ⇡ file
  dialog) and they import serially. `<input type="file" multiple>`
  is set on the hidden picker; `onDrop` reads every file from
  `dataTransfer.files`.
- `Importing N of M…` emerald status line while the loop runs.
  Per-file failures collect and render as `name: error; name: error`
  in the existing rose-colored error banner; successes land in the
  sidebar with the last-imported selected.

## [0.1.36] - 2026-04-19

### Added

- Drag-drop a `session-*.json` onto the Sessions sidebar to import
  — matches the ⇡ button but skips the file picker. Emerald
  ring + "Drop session JSON to import" overlay while a drag is
  over the aside. `dragleave` is scoped to the aside so crossing
  into child elements doesn't flicker the overlay.
- Import file-reading logic extracted into `importFromFile(file)`
  shared by the ⇡ click-handler and the drop handler.

## [0.1.35] - 2026-04-19

### Added

- `POST /api/sessions/import` — consumes the v0.1.30 export shape
  (`{session, messages, tool_calls}`) and restores it as a new
  session. Generates fresh ids for the session, every message, and
  every tool call; preserves content / role / thinking / timestamps;
  remaps `tool_calls.message_id` through an id-translation table.
  Resets `total_cost_usd` to zero (restores don't count as spend).
  Returns 400 on missing / malformed `session` key.
- `store.import_session(conn, payload)` helper — single-transaction
  writeback.
- ⇡ button in sidebar header opens a file picker; FileReader parses
  the JSON, POSTs, prepends the imported session to the list,
  selects and connects. Inline error below the button on bad JSON
  or server rejection.
- `api.importSession(payload)` TS helper.

## [0.1.34] - 2026-04-19

### Added

- `AuthGate.test.ts` — 5 cases: hidden when `auth.status == 'open'`;
  visible on `required`; shows "rejected" copy on `invalid`; saving a
  token flips status to `ok` + writes localStorage; empty-string
  submission is a no-op.

### Fixed

- `vitest.setup.ts` installs a Map-backed `localStorage` shim on
  both `globalThis` and `window`. Node 22+ ships a native
  `localStorage` global that is non-functional unless
  `--localstorage-file` is given a valid path, and that global
  shadows jsdom's Storage under vitest — `setItem` / `getItem` threw
  `TypeError`. The shim sidesteps the whole mess and clears between
  tests via `afterEach`.

## [0.1.33] - 2026-04-19

### Added

- `Settings.test.ts` — exercises the real `prefs` store: fields
  pre-fill on open, Save writes all three fields back to the store,
  Cancel leaves the store untouched. Proves the component-test
  scaffold can drive store-integrated components, not just static
  markup.

### Changed

- `vitest.config` resolves `$lib` to `src/lib` explicitly — needed
  because SvelteKit's build-time alias isn't available in the
  isolated vitest plugin chain. Added `@types/node` dev dep so the
  config's `path.resolve(__dirname, …)` typechecks.

## [0.1.32] - 2026-04-19

### Added

- Component tests under `@testing-library/svelte` + `jsdom`:
  vitest.config adds `environment: 'jsdom'`, `resolve.conditions: ['browser']`
  (so Svelte 5 picks the client entry, not index-server.js), and a
  setup file loading `@testing-library/jest-dom/vitest` matchers.
- First component test: `CheatSheet.test.ts` — renders nothing when
  closed, renders the shortcuts list when open, close button is
  clickable. Auto-cleanup via `afterEach(cleanup)`.
- `src/vitest-env.d.ts` pulls jest-dom matcher types into the
  svelte-check tsconfig.

## [0.1.31] - 2026-04-19

### Added

- `Session.message_count` — computed via subquery in `get_session`,
  `list_sessions`, `list_all_sessions`. SessionOut API response
  exposes it.
- Conversation header shows `· N msg` (pluralized) next to the cost
  segment when a session is selected. Useful now that pagination
  only loads 50 messages at a time — you can tell at a glance
  whether older ones are hidden.
- `sessions.bumpMessageCount(id, delta)` — conversation store calls
  it on user prompt (+1) and on MessageComplete (+1), so the header
  count ticks up live during streaming.

## [0.1.30] - 2026-04-19

### Added

- `GET /api/sessions/{id}/export` — single-session JSON dump
  containing `{session, messages, tool_calls}`. Scoped version of the
  v0.1.5 `/api/history/export` for archiving one conversation.
- ⇣ button in the Conversation header (next to ✎) downloads the
  session as `session-{id8}-{YYYYMMDD}.json` via a Blob + temporary
  anchor. Disabled while a download is in flight.

## [0.1.29] - 2026-04-19

### Added

- `GET /api/sessions/{id}/messages?before=<iso>&limit=<N>` — newest-
  first pagination cursor. `store.list_messages` grows an optional
  `before` + `limit`; without `limit` it keeps the original
  all-oldest-first behavior so existing callers are unaffected.
- Frontend `api.listMessagesPage(sid, {before?, limit?})` returns
  `{messages, hasMore}` with the page already reversed to
  oldest-first for rendering.
- `conversation.load()` now fetches 50 most-recent messages (+
  `hasMore`), not the whole history.
- `conversation.loadOlder()` + scroll-to-top handler in
  Conversation.svelte: scrolling within 40px of the top prepends the
  next page, preserving viewport (`scrollTop = newHeight -
  prevHeight`).
- "Scroll up to load older messages" / "Loading older…" hint at the
  top of the message list when `hasMore`.

## [0.1.28] - 2026-04-19

### Changed

- `store.list_sessions` orders by `updated_at DESC` instead of
  `created_at DESC`. `insert_message` now also bumps the owning
  session's `updated_at`, so a session that just streamed a turn
  rises above an idle newer session.
- Frontend `sessions.bumpCost` mirrors the same move-to-top: the row
  gets a fresh `updated_at` and is spliced to the head of the list,
  matching what the next `refresh()` would produce.

## [0.1.27] - 2026-04-19

### Added

- Cost badge on each sidebar session row (`$0.1234` in a mono font,
  hidden when total cost is zero). Uses the same amber/rose pressure
  coloring as the Conversation header when a `max_budget_usd` is set.
- `sessions.bumpCost(id, deltaUsd)` — called by the conversation
  store on every MessageComplete that carries a cost, so the sidebar
  badge updates live during streaming instead of waiting for a full
  refresh.
- Sidebar timestamp uses `updated_at` instead of `created_at` so a
  rename or a just-streamed turn shows a meaningful "last touched".

## [0.1.26] - 2026-04-19

### Added

- `?` key toggles a CheatSheet modal listing every keyboard /
  discoverability shortcut we've accumulated (⌘K, Esc, ⌘/Ctrl+Enter,
  double-click rename, ✎ / ⚙ / ✕ icons). Gated off when focus is in
  a textarea / input so typing a literal "?" in the prompt still
  works. Esc closes the modal.

## [0.1.25] - 2026-04-19

### Added

- Keyboard shortcut `⌘/Ctrl+K` focuses (and selects) the sidebar
  search input. Placeholder updated to advertise it.
- `Esc` inside the search input clears the query and blurs.

## [0.1.24] - 2026-04-19

### Added

- Match pill above the Conversation body when `highlightQuery` is
  set: `Matching «query» · Esc to clear`, with a ✕ button to clear.
- Document-level `Esc` keydown clears the highlight; ignored while
  the prompt textarea or any input has focus so it doesn't compete
  with normal text editing.

## [0.1.23] - 2026-04-19

### Added

- `AgentSession.interrupt()` — forwards to the active SDK client's
  `client.interrupt()`. Safe no-op when no stream is active. The WS
  handler now calls it on a `{"type":"stop"}` frame *before* breaking
  out of the stream loop, so tools running in the CLI subprocess get
  an actual cancel signal rather than just getting their output
  stream orphaned.
- `AgentSession._client` field tracks the live SDK client while a
  stream is in flight. Cleared in a `finally` under the `async with`
  so reference drops even if the generator is closed mid-iteration.

### Why

v0.1.18's stop already broke out of the server's stream loop and
persisted the partial turn. But a Bash tool running a 30s command
kept running in the CLI subprocess — the user's Stop clicks
stopped what they saw on screen without freeing the compute. Now
`agent.interrupt()` pokes the SDK, which tells the CLI to abort the
in-flight tool.

## [0.1.22] - 2026-04-19

### Added

- `$lib/actions/highlight.ts` — Svelte action that DOM-walks text
  nodes, wraps case-insensitive matches of `query` in
  `<mark class="search-mark">`, and scrolls the first match into view.
  Unwraps previous marks on `update` so repeated queries stay stable.
- `conversation.highlightQuery` — set when a sidebar search result is
  clicked; Conversation's per-message prose div applies the action to
  that query so matches jump out in the message body, not only the
  sidebar snippet.
- Scoped `mark.search-mark` styling matches the amber tint used in
  the sidebar (`yellow-500 @ 35%` background / `yellow-300` text).

### Changed

- `conversation.pushUserMessage` clears `highlightQuery` — sending a
  new prompt shouldn't leave a stale search highlight behind.

## [0.1.21] - 2026-04-19

### Added

- `$lib/utils/highlight.ts::highlightText(text, query)` — returns HTML
  with case-insensitive matches wrapped in `<mark>`. HTML-escapes the
  source first (so injected markup renders as text), treats regex
  metacharacters in the query as literals. 6 unit tests cover the
  escaping, no-match, multi-match, and meta-char cases.
- Sidebar search results render highlights via `{@html}` on the
  snippet, with a scoped `<style>` giving `<mark>` an amber tint that
  reads cleanly on the dark theme.

## [0.1.20] - 2026-04-19

### Added

- Vitest for the frontend — pure-logic tests run via `npm run test`.
  First coverage: `$lib/utils/budget.ts::parseBudget` (extracted from
  `SessionList.svelte` so it's testable).
- `vitest.config.ts` kept separate from `vite.config.ts` so
  svelte-check's type-checking of the Vite config stays clean.
- CI `frontend` job now runs `npm run test` between `npm run check`
  and `npm run build`.

### Changed

- `SessionList` imports `parseBudget` from `$lib/utils/budget` instead
  of defining it inline.

## [0.1.19] - 2026-04-19

### Added

- `GET /api/history/search?q=...&limit=N` — case-insensitive LIKE
  match across `messages.content` + `thinking`, joined with
  `sessions` for title + model. Returns `SearchHit[]` with a trimmed
  snippet window (±40/±120 chars around the first match).
- `store.search_messages(conn, query, limit)` + `SearchHit` Pydantic
  model.
- Frontend `api.searchHistory(q, limit)` helper.
- Sidebar search input above the sessions list. Typing (debounced
  200ms) swaps the list for match previews — session title, role
  badge, snippet with ellipses. Clicking a hit selects the session
  and connects.

## [0.1.18] - 2026-04-19

### Added

- `{"type":"stop"}` frame on the agent WebSocket interrupts an
  in-flight stream. The server breaks out of `agent.stream`,
  synthesises a `MessageComplete`, and persists whatever text/tool
  calls streamed so far — the partial assistant message is not lost.
- Frontend `agent.stop()` sends the stop frame; Conversation header
  shows a red **Stop** button next to the connection badge while
  `conversation.streamingActive` is true.

### Changed

- WS handler refactor: a dedicated reader task drains inbound frames
  into an `asyncio.Queue`; the outer prompt loop pulls from it, and
  the streaming loop peeks non-blockingly between events. Keeps a
  single WS reader (no racing `receive_json` calls), lets any future
  mid-stream control frame follow the same pattern.
- Assistant-turn persistence extracted into a `_persist_assistant_turn`
  helper so natural-end and stop paths both write through the same
  code.

## [0.1.17] - 2026-04-19

### Added

- `SessionEdit.svelte` modal wired behind a ✎ button in the Conversation
  header. Edits `title` + `max_budget_usd` on an existing session via
  the v0.1.16 PATCH route. Cap is no longer create-time-only.
- `twrminal send --format=pretty` — human-readable output:
  - tokens stream inline with a flush,
  - `thinking` / `message_start` frames suppressed,
  - tool calls render as `↳ tool Name (input)` / `← ok: output` or
    `← error: message`,
  - each turn ends with a separator line + cost badge.
  Default `--format=json` stays one-event-per-line for scripting.

## [0.1.16] - 2026-04-19

### Added

- `PATCH /api/sessions/{id}` with `SessionUpdate` body — partial
  updates for `title` and `max_budget_usd`; unset fields leave the
  column untouched, explicit null clears. `updated_at` bumps on any
  real change. Returns 404 if the session is gone.
- `store.update_session(conn, session_id, fields)` — whitelists
  `title` / `max_budget_usd`, builds the SET clause dynamically.
- Frontend `api.updateSession(id, patch)` + `sessions.update(id, patch)`
  store method.
- Inline rename in the sidebar: double-click a session title →
  input; Enter / blur saves via PATCH, Esc cancels. Conversation
  header reflects the new title through normal reactivity.

## [0.1.15] - 2026-04-19

### Added

- `stores/prefs.svelte.ts` — reactive preferences persisted in
  `localStorage` (`defaultModel`, `defaultWorkingDir`, `authToken`).
- `components/Settings.svelte` — modal accessed via a ⚙ button in the
  Sessions panel header. Edits all three prefs + also lifts the auth
  gate when a token is entered here while the gate is up.
- SessionList new-session form pre-fills `working_dir` and `model`
  from saved prefs each time it opens; user edits within the open
  form still override. Create also falls back to the pref default if
  the user clears the field.

## [0.1.14] - 2026-04-19

### Added

- `messages.thinking` column (migration 0004). WS handler accumulates
  a `thinking_buf` alongside `buf` during the turn and passes the
  joined string (or `None` if empty) to `insert_message` at
  `MessageComplete`. Persisted thinking survives page reloads.
- `MessageOut.thinking` + frontend `Message.thinking` types.
- Conversation pane renders a `<details>` "thinking" block (closed by
  default) on any persisted message that has stored reasoning.

### Fixed

- `test_metrics.py::test_ws_counters_update` flake: the
  `messages_persisted` assistant counter is incremented in the
  MessageComplete branch after the last send, which can be truncated
  by TestClient context exit. Now polls the counter inside the WS
  context before asserting, matching the pattern used elsewhere.

## [0.1.13] - 2026-04-19

### Added

- `Thinking(type="thinking", session_id, text)` event. `AgentSession`
  now translates `ThinkingBlock.thinking` (emitted by the SDK when
  extended thinking is on) into a `Thinking` frame instead of silently
  dropping it.
- Frontend `AgentEvent` union picks up `ThinkingEvent`; conversation
  store accumulates `streamingThinking` alongside `streamingText`.
- Streaming pane shows a `thinking` `<details>` block (open by default)
  above the token output when the agent is reasoning aloud.

## [0.1.12] - 2026-04-19

### Added

- `AuthGate.svelte` modal. When `/api/health` reports
  `auth: "required"` and no token is stored (or the stored token is
  rejected on any API 401 / WS 4401), the modal blocks the UI with a
  password-masked input. Save → token persists in
  `localStorage["twrminal:token"]` → boot proceeds.
- `stores/auth.svelte.ts` tracks `status`
  (`checking`/`open`/`ok`/`required`/`invalid`/`error`). `api.ts`
  exports `onAuthFailure(cb)` so the store flips itself to `invalid`
  on 401 without a circular import. `agent.svelte.ts` flips the same
  way on WS close 4401 and aborts reconnect (no infinite loop).
- Boot flow moved from `SessionList.onMount` to `+page.svelte`: auth
  check first, then `sessions.refresh` + auto-connect only after the
  gate clears.
- Budget pressure coloring in the Conversation header: amber at ≥80%
  of `max_budget_usd`, rose at ≥100%. Sessions with no cap render
  unchanged.

### Fixed

- `SessionList` budget parsing now handles `<input type="number">`
  binding variants (number / empty string / null) instead of assuming
  a string; previously the new-session form submitted
  `max_budget_usd: null` when the field had a value.

## [0.1.11] - 2026-04-19

### Added

- Opt-in bearer-token auth. Set `auth.enabled = true` +
  `auth.token = "..."` in `config.toml`:
  - `/api/sessions*` and `/api/history*` require
    `Authorization: Bearer <token>` (new `api/auth.py` dependency).
  - `/ws/sessions/{id}` requires `?token=<token>` (browsers can't set
    WS headers); closes with app code `4401 Unauthorized` on mismatch.
  - `/api/health` and `/metrics` stay open so monitoring can probe
    without creds.
  - Enabling auth with an empty token fails the first request with
    500 — fail closed rather than silently ship with no protection.
- `GET /api/health` now returns `{auth: "required"|"disabled", version}`
  so clients can tell whether they need to supply a token.
- `twrminal send --token <t>` flag; CLI also auto-pulls from
  `cfg.auth.token` when `auth.enabled`.
- Frontend `api.ts` reads `localStorage["twrminal:token"]` and injects
  `Authorization: Bearer` on fetches + `?token=...` on the WS URL. UI
  to enter the token lands in a later slice; for now set it via devtools
  (`localStorage.setItem('twrminal:token', '...')`).

## [0.1.10] - 2026-04-19

### Added

- `MessageComplete.cost_usd` — SDK-reported turn cost
  (`ResultMessage.total_cost_usd`) surfaced on the wire. `AgentSession`
  captures it before the `break` on ResultMessage.
- `sessions.total_cost_usd` column (migration 0003, `REAL NOT NULL
  DEFAULT 0`). `store.add_session_cost` accumulates it per turn; WS
  handler calls it on MessageComplete when cost is non-null.
- `SessionOut.total_cost_usd` on the API.
- Frontend `Session.total_cost_usd` + `MessageCompleteEvent.cost_usd`.
- Conversation store tracks `totalCost`: seeded from the DB row on load,
  incremented locally per MessageComplete. Conversation header shows
  `spent $Y.YYYY` and, when a cap is set, `/ $X.XX`.

## [0.1.9] - 2026-04-19

### Added

- Graceful WebSocket shutdown: FastAPI lifespan tracks active agent
  sockets in `app.state.active_ws`; on shutdown, each is closed with
  code `1001 Going Away` before the DB connection is torn down.
  Clients see a clean disconnect (and hit the v0.1.4 reconnect path)
  instead of `ConnectionReset` on `systemctl restart`.
- Conversation header shows `budget $X.XX` next to model + working_dir
  when the session has a `max_budget_usd` cap set; otherwise omitted.

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
