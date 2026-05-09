# Changelog

All notable changes to Bearings are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **fix(frontend): F9-rt-01 — per-theme treatment CSS now in dist bundle:**
  `[data-theme=midnight-glass]` radial-gradient, backdrop-filter, and aside treatments
  were absent from the served CSS bundle because the four `@import` statements in
  `frontend/src/app.css` appeared after `@tailwind base;`, causing PostCSS/Vite to
  silently drop them on every rebuild. The `@import` lines were moved above
  `@tailwind base;` (theme-sweep-001, commit `788b0e1d`) and the dist was rebuilt.
  Verified: `[data-theme=midnight-glass]` treatment rules confirmed present in current
  dist bundle. (Already resolved by sibling executor A3 at `788b0e1d`.)

- **fix(keyboard): F9-rt-14 — Ctrl+K now opens the SidebarSearch overlay:**
  `KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH` had `displayOnly: true` in `bindings.ts`,
  so `buildRegistry` skipped it and Ctrl+K was never dispatched. `SidebarSearch`
  registered its handler via `bindHandler` — removing `displayOnly: true` connects the
  two. (Already resolved by sibling executor A5 at `26a0d7d5`.)

- **fix(frontend): F9-rt-17 — no state\_unsafe\_mutation on ? → ? → Ctrl+Shift+P → Esc:**
  A reactive computation in the cheat-sheet / command-palette overlay path mutated
  `$state` mid-derivation (Svelte error `state_unsafe_mutation`). Fixed by the
  Svelte 5.55.5 compiler upgrade (commit `5a9cff64` CVE dep bump), which corrects
  the compiled reactive graph for the `$effect` in `KeybindingsProvider` that calls
  `setModalOpen`. Dist rebuilt after the upgrade. Added `KeybindingsProvider.test.ts`
  regression guard for the `?` → `?` → Ctrl+Shift+P → Esc sequence.

- **fix(context-menus): F9-rt-25 — destructive confirm dialog renders "Don't ask again this session" checkbox:**
  The per-session suppression checkbox was unreachable because `ConfirmDialog` was not
  invoked with `showSuppressCheckbox={true}` from the `ContextMenu` bridge.
  `ContextMenu.svelte` now passes `showSuppressCheckbox={true}` and the
  `onConfirmAndSuppress` callback wired to `suppressAction(actionId)`. Subsequent
  destructive actions of the same type short-circuit the dialog; the in-memory
  suppression set resets on hard-refresh / new tab. (Source wiring was added in
  gap-cycle-10-004, commit `ef69195d`; dist rebuilt at `51c2cabd`.) Regression
  tests added to `ConfirmDialog.test.ts`.

- **perf(frontend): code-split shiki via dynamic import (PERF-BUG-005/006 frontend):**
  `render.ts` statically imported shiki at module load time. Changed to `import("shiki")`
  inside `getHighlighter()` so shiki only loads when the first code block needs
  highlighting. Routes that never render fenced code pay zero shiki parse cost at startup.

- **fix(frontend): eliminate duplicate GET /api/sessions on /sessions/new warm loads (PERF-BUG-002):**
  `hydrateDefaults()` called `getMostRecentSession()` → `GET /api/sessions?include_closed=true`,
  duplicating the layout's bootstrap fetch. Now reads `sessionsStore.sessions[0]` when
  the store is already populated (warm navigation); cold loads fall back to the API as before.

- **fix(frontend): reserve min-height on layout header and sidebar rows to prevent CLS (PERF-BUG-003/004):**
  `/sessions/<id>` CLS = 0.102 (budget 0.10) was driven by the main-header growing from
  near-zero to ~2.75 rem when `activeSession` populated on bootstrap fetch resolve. Added
  `min-height: 2.75rem` to `.app-shell__main-header` and `min-height: 3.5rem` to
  `.session-row` (absorbs tag-chip row arrival). PERF-BUG-001 and PERF-BUG-005 require
  Orch B's backend pagination to reach the ≥90 envelope; flagged DONE_WITH_CONCERNS.

- **fix(frontend): quota mock and sessions store stub in /sessions/new tests:**
  `NewSessionForm.svelte` uses `getCurrentQuotaSafe` but the test mock only exposed
  `getCurrentQuota`, causing 5 pre-existing failures. Fixed the mock; added a
  `sessionsStore` stub to prevent WebSocket-in-jsdom errors.

- **fix(preferences): POST /api/preferences/avatar and sync_from_system returned
  500 for all inputs (F8-rt-04/05/12):** `_avatars_root()` in
  `web/routes/preferences.py` used `getattr(state, "avatars_root", DEFAULT)`,
  which silently returned `None` (not `DEFAULT`) because
  `_configure_app_state()` always sets the attribute — even to `None` when no
  path is injected. Subsequent `None.mkdir()` crashed with `AttributeError` →
  HTTP 500.  Fixed by replacing the bare `getattr` default with an explicit
  `None`-check: `raw = getattr(..., None); effective = raw if raw is not None
  else DEFAULT_AVATARS_STORAGE_ROOT`.  Additionally wired
  `DEFAULT_AVATARS_STORAGE_ROOT` into the `bearings serve` CLI's `create_app`
  call so the production path is always populated.  UI error-badge symptom
  (F8-rt-12) resolves once the backend fix is live.

- **fix(vault): row metadata — parent-dir subtitle + relative mtime
  (F7-RT-00):** Vault list rows were rendering the entry label alone.
  Now each plan/todo row renders a subtitle line showing the parent
  directory short name and a relative-time string ("5m ago", "2d ago").
  Added `parentDirName` and `formatRelativeTime` helpers (exported for
  unit tests) to the VaultPanel module block.

- **fix(vault): linkifier applied to vault reader body (F7-RT-01):**
  `renderMarkdown` in `render.ts` had no linkifier extension, so bare
  URLs and session references in vault doc bodies rendered as plain text.
  Added `renderMarkdownWithLinkifier` — a separate `Marked` instance with
  two inline extensions: `vaultBareUrl` (bare `https?://` → `<a
  target="_blank">`) and `vaultSessionId` (`ses_<hex>` → internal
  `/sessions/<id>` anchor). VaultPanel now uses this path for the reading
  panel body. `BearingsRenderer` (`data-cm-target` attributes) is
  preserved via `setOptions()`.

- **fix(vault): "Open against this session" affordance (F7-RT-02):**
  The reader header had no affordance to pin the active session. Added an
  "Open against this session" button (visible when `activeSessionId ≠
  null` and a doc is selected) that stores a `pinnedSessionId` in local
  state and shows a "Pinned to session" indicator in the header. Paste-
  into-composer operations use the pinned session when set, falling back
  to the prop-supplied `activeSessionId`.

- **feat(cli): add `bearings init` and `bearings migrate` subcommands
  (F13-rr-12 — fulfils v1.0.0 stability commitment §"CLI flag surface"):**
  Both subcommands were named as stable v1.x CLI surfaces in the
  `[1.0.0]` entry but were absent from the binary. Now wired:
  * `bearings init [--db PATH] [--uploads-root PATH] [--avatars-root PATH]`
    — creates `~/.local/share/bearings-v1/` directory tree (data dir,
    uploads root, avatars root) and applies the canonical DB schema via
    `load_schema`. Fully idempotent (`exist_ok=True` on dirs, `IF NOT EXISTS`
    guards on all schema objects); safe to run on an already-initialised
    installation.
  * `bearings migrate [--db PATH]`
    — applies any pending column additions from `connection._ADDED_COLUMNS`
    to the existing DB, using `PRAGMA table_info` probes to skip columns that
    already exist. Returns the count of columns actually altered (0 on an
    up-to-date schema). Exits 1 with a hint to run `bearings init` first if
    the DB file is absent.
  Both handlers are thin argparse dispatchers per arch §1.1.1; domain logic
  lives in `bearings.bearings_dir.init.ensure_data_dir` and
  `bearings.db.migrate.run_migrations` respectively. Seven pytest smoke
  tests cover creation, idempotency, missing-DB error path, and help text
  for both subcommands (`tests/test_cli_init_migrate.py`).

- **fix(a11y): resolve 10 WCAG AA violations — contrast, aria-label, touch
  target, accessible names (BUG-A11Y-01..07 + NEW-BUG-A11Y-01..03):**
  Ten axe-core serious/critical a11y violations fixed across seven frontend
  files:
  (1) *Tag chip contrast (BUG-A11Y-01)* — conversation header tag chips used
  `color:${tag.color}` (purple text on tinted-purple bg). Removed inline text
  color; chips now use `text-fg-strong` on the tinted background.
  (2) *White-on-accent buttons (BUG-A11Y-02)* — primary CTA buttons failed
  4.5:1 in evergreen (4.48), default (2.55), and midnight-glass (2.5) themes.
  Darkened `--bearings-accent` tokens: evergreen `#107538`, default blue-600
  `#2563eb`, midnight-glass `#3769d2`. Introduced `--bearings-accent-text`
  (lighter tint) for text-on-dark-surface usage via unlayered `.text-accent`
  override in `app.css`.
  (3) *Evergreen accent as text (BUG-A11Y-03)* — brand heading, nav links,
  and active inspector tabs used `#258846` directly on dark surfaces (3.9:1).
  Fixed via `--bearings-accent-text: 134 239 172` (green-300, 13:1) and
  Inspector.svelte active-tab CSS updated to use the new token.
  (4) *Default fg-muted on surface-2 (BUG-A11Y-04 + NEW-BUG-A11Y-03)* —
  muted text on elevated cards yielded 4.01:1. Lightened
  `--bearings-fg-muted` in default theme from `156 163 175` to `176 183 196`
  (now 5.07:1). Fixes model badge, tag-filter chips, import/templates buttons,
  and system-status rows.
  (5) *Paper-light error text (BUG-A11Y-05)* — `text-red-400` on cream
  background yielded 2.58:1. Added unlayered `[data-theme="paper-light"]
  .text-red-400` override to `--bearings-accent-error`; darkened error token
  to red-700 (6.1:1 on all paper-light surfaces).
  (6) *Avatar fallback aria-label on span (BUG-A11Y-06)* —
  `<span aria-label>` without a role is prohibited. Added `role="img"` to
  `UserIdentityBlock.svelte`'s fallback span.
  (7) *Label-content-name mismatch (BUG-A11Y-07)* — sidebar templates button
  `aria-label="Open template picker"` did not contain visible text
  "Templates…"; identity button `aria-label="Open Settings"` did not contain
  user's display name. Fixed: templates label updated to `"Templates… — open
  picker"`; identity button aria-label now prefixes with the display name.
  (8) *Touch target (NEW-BUG-A11Y-01)* — tag filter chip buttons too small
  for WCAG 2.5.8 (< 24px). Added `min-h-6 inline-flex items-center` to all
  chip buttons in `TagFilterPanel.svelte`.
  (9) *Emerald-500 badge + accent/70 contrast (NEW-BUG-A11Y-02)* —
  `text-emerald-500` session-count badges failed on paper-light surface-2
  (1.99:1); `text-accent/70` in AccentCards failed (3.06:1); severity badge
  `tracking-wide text-white` could fail on light-colored tags. Fixed:
  emerald-500 → `text-ok` (green-800 in paper-light); `text-accent/70` →
  `text-fg-muted`; severity badge now uses `severityTextClass()` helper to
  select `text-white` or `text-fg-strong` based on background luminance.
  Also darkened `--bearings-accent-ok` in paper-light to green-800 (22,101,52)
  for sufficient contrast.
  All fixes include vitest regression tests (attribute and class assertions).

- **fix(keyboard): resolve 8 keyboard-nav bugs — focus-trap, Ctrl+Shift+P
  toggle, Ctrl+K dispatcher (KBD-04/07/15/24/28/52/53/54):**
  Three root-cause fixes:
  (1) *Ctrl+K dispatcher* — `bindings.ts` had `displayOnly: true` on the
  `KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH` entry, causing `dispatch.ts` to
  skip it when building the registry so `lookupBindingForEvent` always
  returned `undefined` and `SidebarSearch.svelte`'s `openOverlay` handler
  never fired. Fix: removed `displayOnly: true`; the binding now routes
  through the global dispatcher to the already-registered handler (KBD-28,
  KBD-54).
  (2) *CommandPalette stop-propagation* — `CommandPalette.svelte`'s panel
  `<div>` had `onkeydown={(e) => e.stopPropagation()}` which ate every
  keydown before it could bubble to the window-level `KeybindingsProvider`
  listener, so a second `Ctrl+Shift+P` inside the palette never reached the
  toggle handler. Fix: replaced the blanket stop with `handlePanelKeyDown`
  that only traps `Tab`/`Shift+Tab` within the panel and lets all other
  keys propagate (KBD-07, KBD-53, KBD-15).
  (3) *Modal focus-on-open* — `CheatSheet.svelte`, `CommandPalette.svelte`,
  and `TemplatePicker.svelte` all set `tabindex="-1"` on their dialog
  wrappers but never called `.focus()` on open, so Tab walked document
  order to outer-page elements (WCAG 2.4.3 violation). Fix: added
  `$effect`-driven `requestAnimationFrame(() => el.focus())` on open and
  a `handleDialogKeyDown` / `handlePanelKeyDown` Tab-trap in each modal
  (KBD-04, KBD-15, KBD-24, KBD-52). `CheatSheet.svelte` also handles `?`
  inside the dialog so a second press closes the sheet even though
  `stopPropagation` prevents the event reaching the window listener.
  Vitest coverage: 14 new test cases across `CheatSheet.test.ts`,
  `CommandPalette.test.ts`, `TemplatePicker.test.ts`, and
  `dispatch.test.ts`.

- **chore: fix pre-existing vulture + codespell pre-commit gate failures
  (A7):** Three `urlopen` mock parameters in
  `tests/test_preflight_openapi_match.py` were flagged by vulture as unused
  variables (100 % confidence). Root cause: the lambdas and inner `_raise`
  function accepted a positional `timeout` param that matched `urlopen`'s
  positional signature but was never referenced in the body. Fix: replaced
  with `**_kw` (variadic keyword catch-all) so the mocks correctly absorb
  `urlopen(url, timeout=…)` keyword-arg calls while suppressing vulture.
  Codespell failure: `.playwright-mcp/` snapshot files contain snapshot text
  with typos (`subsytem`, `followin`) in MCP-managed fixtures we do not own.
  Fix: added `.playwright-mcp` to the `skip` list in `[tool.codespell]` in
  `pyproject.toml`. Both `pre-commit run vulture` and `pre-commit run
  codespell` now pass.

- **chore: bump frontend devDependencies for 10 CVEs (vite 8.x, vitest 4.x,
  @sveltejs/* latest):** Package upgrade already committed in `2894ad40`;
  this commit fixes the vitest@4 / Svelte 5.55.5 test compatibility regressions
  introduced by that bump. Changes: (1) VirtualItem.test.ts — arrow-function
  mock replaced with regular function so `new IntersectionObserver()` works as
  constructor in vitest@4; (2) sanitize.ts — cross-realm `instanceof Element`
  guard replaced with `"tagName" in node` duck-check, fixing DOMPurify
  `afterSanitizeAttributes` hook under vite@8 Node.js conditions; (3) vitest@4
  Mock type compatibility fixes in TagFilterPanel.test.ts, ContextMenu.test.ts;
  (4) Svelte 5.55.5 $effect init-phase mock-call isolation fixes
  (`mockClear()`) in SettingsDefaults, SettingsProfile, SettingsAuth,
  SettingsNotifications; (5) templates.svelte.test.ts — resilient fetch-call
  matching for Svelte 5 reactive re-fetches. CVEs resolved (7 moderate): vite
  path-traversal (GHSA-4w7w-66w2-5vf9), esbuild dev-server CORS
  (GHSA-67mh-4wv8-2f99), and transitive vitest/vite-node chain. Remaining 3
  low-severity CVEs (GHSA-pxg6-pf52-xh8x cookie via @sveltejs/kit@2.59.1) have
  no upstream fix available — @sveltejs/kit@latest still pins cookie@^0.6.0.
  Frontend dist rebuilt.

- **BUG-NET-24-FE — Five missing SvelteKit route stubs:** Direct navigation to
  `/dashboard`, `/chat`, `/history`, `/preferences`, and `/paired` produced
  in-app 404s because the SvelteKit client router had no component for those
  paths (the backend SPA catch-all landed in commit `661a473e` but the frontend
  routes were absent). Added `+page.svelte` for all five paths:
  `/dashboard`, `/chat`, `/history` — minimal "coming soon" stubs with correct
  `<title>` elements; `/preferences` — replace-redirect to `/settings` (the
  canonical preferences surface per `docs/behavior/preferences.md`); `/paired`
  — informational stub explaining the paired-chat spawn workflow per
  `docs/behavior/paired-chats.md`. Five vitest smoke tests added under
  `frontend/tests/route-stubs.test.ts`. Frontend dist rebuilt and synced.

- **Theme-sweep bundle (theme-sweep-001 through 004):** Four related theme
  bugs filled in a single bundle.

  - **theme-sweep-001 / theme-sweep-003 — Per-theme treatment CSS files now
    land in the production bundle:** The four `@import` directives in
    `frontend/src/app.css` were placed after the `@tailwind` directives;
    the CSS spec forbids `@import` after any non-`@import` rule, so
    `postcss-import` silently discarded them during the production build.
    All per-theme structural effects (aurora wash, glass panels,
    `[data-theme]`-scoped gradients, active-row accents, per-theme
    `focus-visible` rings — theme-sweep-003) were absent from every served
    bundle. Fix: moved the four `@import` lines to before `@tailwind base`.
    The unlayered `[data-theme="…"]` selectors retain cascade precedence
    over `@layer utilities` rules by specificity, so moving them earlier
    has no visual regressions. Verified: `[data-theme=midnight-glass]`
    appears 10 times in `0.DvjN9Whz.css`; radial-gradient and
    backdrop-filter are present; 6 per-theme `focus-visible` rules land.

  - **theme-sweep-002 — Conversation error bubble now respects Bearings
    themes:** The error-state `<div>` in `Conversation.svelte` used
    `dark:bg-red-900/20 dark:text-red-300 dark:text-red-400` Tailwind
    modifiers. Because `tailwind.config.js` had no `darkMode` key (defaults
    to `'media'`), those classes fired on OS `prefers-color-scheme: dark`
    rather than on the Bearings `[data-theme]` attribute, making the error
    bubble ignore the active Bearings theme entirely. Fix: removed all
    `dark:` modifiers from the error bubble; replaced with
    `border-error / bg-error/10 / text-error / text-error/80` Tailwind
    tokens backed by the new `--bearings-accent-error` CSS variable.
    Verified: `prefers-color-scheme:dark` count in served bundle = 0.

  - **theme-sweep-004 — `--bearings-accent-{info,ok,warn,error}` tokens
    now defined per theme:** `InspectorUsage.svelte` (headroom chart,
    advisor-effectiveness chart) consumed these four tokens via
    `var(--bearings-accent-info, #hex)` fallbacks. Because no `[data-theme]`
    block defined them, the chart always painted the raw hex fallback
    regardless of theme. Fix: added all four tokens to every `[data-theme]`
    block in `app.css`. Dark themes (evergreen, midnight-glass, default)
    use 400-range Tailwind palette values (sky-400, green-400, yellow-400,
    red-500) for contrast on dark surfaces; `paper-light` uses 600–700-range
    values (sky-600, green-600, amber-700, red-600) for contrast on the
    cream background. Wired as `info / ok / warn / error` Tailwind color
    tokens in `tailwind.config.js`. Verified: 4 `--bearings-accent-error`
    definitions in the bundle; 0 fallback-hex-only consumers remain.

  Contract tests added to
  `frontend/src/lib/themes/__tests__/treatments.test.ts`: `@import`
  placement, per-theme state-token presence, and `dark:`-free error bubble.

- **Console-clean quota + pending-ops empty states (console-replay-001-FE,
  console-replay-012-FE):** Two fetch paths logged to console on documented
  empty-state responses. `GET /api/quota/current` returns 404 when no snapshot
  has been recorded yet; `GET /api/fs/read` returns 403 when `allow-roots` is
  empty. Both are expected conditions, not errors. Fix: added
  `getCurrentQuotaSafe()` to `frontend/src/lib/api/quota.ts` — wraps
  `getCurrentQuota` and resolves `null` on 404 / 503 / 502 without throwing.
  Extended `fetchPendingOps` in `frontend/src/lib/api/pendingOps.ts` to treat
  403 identically to 404 (empty ops list). `ConversationHeader.svelte` and
  `NewSessionForm.svelte` updated to call the safe variant. Tests added
  asserting `console.error` is not called and helpers resolve to soft-empty.

- **Sidebar row hydration (F1-RT-06/07/08):** 311 `.virtual-item`
  placeholders never hydrated because the scrolling
  `<nav class="flex-1 overflow-y-auto">` inside `SessionList` reported
  `clientHeight: 0` at common viewports. Root cause: `app-shell__sidebar-body`
  was an `overflow-y: auto` block container whose flex-allocated height is not
  always treated as a "definite" size for children's `height: 100%` resolution.
  `session-list` used `h-full` which silently resolved to `height: auto`; with
  no definite container height the inner `nav.flex-1` had 0 px to fill.
  `IntersectionObserver` then classified every row as off-screen and replaced
  all content with placeholders. Fix: converted `app-shell__sidebar-body` to a
  flex column pass-through (`display: flex; flex-direction: column;
  min-height: 0; overflow: hidden`) and changed `session-list` from `h-full`
  to `flex-1 min-h-0`. All sizing now lives in the flex domain; no percentage
  heights. Inline rename (double-click + Enter/Esc) and blur-commit (RT-07/08)
  are unblocked as rows now hydrate correctly. Regression test added to
  `layout.test.ts`.

- **OpenAPI undocumented-status bundle (BUG-NET-10/11/20):** Four
  endpoints legitimately return 4xx responses that were absent from
  the OpenAPI specification, causing clients and the frontend to treat
  them as unexpected errors.
  - `GET /api/quota/current` — 404 (`no quota snapshot recorded yet`)
    now declared with a typed `DetailError` schema. This is the root
    cause of `console-replay-001` (frontend `console.error` on every
    cold-cache page load); the backend contract change is shipped here.
    Frontend soft-empty wrap for this 404 is handed off to Orch A
    (console-replay-001).
  - `GET /api/preferences/avatar` — 404 (`no avatar set`) now declared
    with a typed `DetailError` schema. Empty-state is a documented and
    expected condition.
  - `GET /api/fs/list` — 403 (`no fs allow-roots configured` or path
    outside roots) now declared with a typed `DetailError` schema.
  - `GET /api/fs/read` — 403 now declared; same root cause as
    `/api/fs/list`. Frontend soft-empty wrap for the 403 on
    session-detail render is handed off to Orch A (console-replay-012).
  - Shared `DetailError` model added at
    `src/bearings/web/models/errors.py` — exposes the `{"detail": str}`
    shape that `HTTPException` raises produce throughout all Bearings
    routes.
  - `docs/openapi.json` regenerated (all four status codes now appear
    in the spec with typed schemas).
  - Regression tests added for all four body shapes; `GET /api/fs/read`
    403 (no allow-roots) is also newly covered.

### Added

- **Documentation set — concepts overview, task-oriented guides,
  master cross-reference index, curated API reference.** Plan at
  `~/.claude/plans/sunny-churning-catmull.md`. The repo carried
  reference-grade docs already (16 behavior specs, 1005-line
  architecture decomposition, routing-v1 spec, OpenAPI export, two
  audit registers) but no task-oriented user docs and no
  cross-reference matrix. New files: `docs/README.md` (master
  index with six lookup paths), `docs/concepts.md` (connected
  mental model + glossary), `docs/api.md` (121 endpoints across
  25 route groups, curated by prefix with curl examples and links
  to `openapi.json` for full schemas), and 10 task-oriented
  walkthroughs under `docs/guide/`: `getting-started.md`,
  `sessions.md`, `routing.md`, `inspector.md`, `checklists.md`,
  `paired-chats.md`, `vault-and-memories.md`, `analytics.md`,
  `settings.md`, `cli.md`. Root `README.md` rewritten to point
  at the new front door. Inspector "five-tab" mention in the
  highlights updated to the actual eight tabs (Agent, Context,
  Instructions, Files, Changes, Metrics, Routing, Usage); the
  five-tab text was a stale claim from an earlier release. No
  code changes in this commit set — surgical drift fixes for
  the OpenAPI 202 schema gap (`/prompt`, `/regenerate`,
  `/regenerate_from`) and the stale Stop-undo entry in
  `V1_FEATURE_AUDIT.md` ship in parallel commits dispatched to
  audit-fix session `714700c04b7f4d48820b3f05d63a35af`.

- **Phase 2 QA — Doctor preflight OpenAPI cross-check
  (`scripts/preflight_openapi_match.py`):** The Phase 2 Doctor
  preflight check #7 only verified that the served `dist/` tree
  matched HEAD; it never confirmed the *live API surface* matched the
  routes declared at HEAD. Bug F1-RT-00 (blocker) exposed this gap:
  a uvicorn worker launched on 2026-05-05 from HEAD `ba158917`
  predated all Phase 1 fix commits, so the live server lacked
  `/api/sessions/bulk`, `/api/sessions/{id}/export`, and
  `/api/sessions/import` even though source and dist were both
  current. All Wave 2 and Wave 3 feature surveys hitting those
  endpoints received 404/405. Fix: new script
  `scripts/preflight_openapi_match.py` that fetches
  `/openapi.json` from the running server, generates the HEAD path
  set via `create_app().openapi()`, and diffs them — exit 0 on
  match, exit 1 on mismatch ("live API stale vs HEAD"), exit 2
  when the server is unreachable. 15 unit tests covering
  `_extract_paths`, `get_live_paths` (urlopen mock), and
  `check_openapi_match` (match / mismatch fixture / unreachable /
  extra-in-live). Server restarted; all three previously-missing
  paths now respond correctly.

- **Analytics Phase 3 — usage routes extended:** The three existing
  `/api/usage/` endpoints now expose the full token picture from the
  Phase 0/1 analytics schema:
  - `GET /api/usage/by_model` and `GET /api/usage/by_tag` gain a
    `cache_creation_tokens` field (summed from
    `messages.cache_creation_tokens`, landed in Phase 0; advisor rows
    always carry `0` since cache-creation costs attach to executor turns).
  - New `GET /api/usage/turns?period=week&session_id=<id>` endpoint
    surfaces the Phase 1 `turns` table — one row per Claude Agent SDK
    turn with full token counts (`input_tokens`, `output_tokens`,
    `cache_read_tokens`, `cache_creation_tokens`, `model`, `timestamp`
    in unix ms). Supports the same `period` param (`day` / `week`) as
    the other usage endpoints plus an optional `session_id` filter.
    Operation id: `get-usage-turns`. Per spec §3.2, rows carry their
    `model` field so callers can group by model before aggregating.
  - `db.analytics.list_turns()` — new DB helper backing the endpoint;
    filters by unix-ms cutoff and optional session id.
  - `web/models/usage.TurnOut` — Pydantic wire model for the new
    endpoint.
  - `docs/openapi.json` regenerated (135 operations, was 134).

- **SDK history replay on supervisor respawn:** Mid-session model
  swap, idle reap, server restart, and recovery from ERROR all
  recycle the SDK CLI subprocess. Before this change, the new
  subprocess started with empty conversation context — the user
  observed "this is the start of the session" on the next turn and
  the agent had no memory of prior turns. Bearings now persists the
  CLI's per-session JSONL transcript via the SDK's
  `SessionStore` adapter (`bearings.agent.session_store.BearingsSessionStore`),
  backed by a new `sdk_session_entries` mirror table. On every spawn
  after the first the bootstrap sets `resume=<sdk_uuid>` and the SDK
  materialises history into the new subprocess; on the first spawn
  it pins the CLI's session UUID via `session_id=<sdk_uuid>` so
  subsequent appends are routable back to the Bearings session id.
  The SDK UUID is derived deterministically from the Bearings
  session id (`ses_<32hex>` → `<8>-<4>-<4>-<4>-<12>`) — no new column,
  no migration. New modules:
  `bearings.agent.sdk_session_id`,
  `bearings.agent.session_store`,
  `bearings.db.sdk_entries`. New tests:
  `test_sdk_session_id.py`, `test_sdk_entries_db.py`,
  `test_session_store.py`, `test_session_bootstrap_resume.py` plus
  added `compose_session_options` coverage of the new kwargs and the
  mutual-exclusion guard between `sdk_session_id` and `resume`.

- **Tag classes (project / severity / general):** Tags now carry a
  `class` column that partitions them into three buckets the UI
  renders as separate filter sections. Cardinality is enforced at the
  API boundary on bulk-replace: a session may carry up to one project
  tag, up to one severity tag, and any number of general tags.
  Severity-class tags reject `default_model` / `working_dir` at the
  dataclass + Pydantic validators (severity is signalling, not
  configuration). New `tags.sort_order` column scopes per-class
  display order; `PUT /api/tags/sort-order` is the atomic
  drag-reorder endpoint. New `?class_=` filter on `GET /api/tags`;
  three new `tag_ids_<class>` query params on `GET /api/sessions`
  (OR within a section, AND across sections; empty section means
  "no constraint", not "exclude everything"). The legacy `tag_ids`
  param and `GET /api/tag-groups` endpoint are retained one release
  for back-compat with v0.18.x consumers.

- **`/advisor` per-turn override (G9):** The composer slash-command
  `/advisor <message>` attaches `force_advisor=true` to the prompt
  payload.  The backend SDK loop honours the flag by prepending
  `FORCE_ADVISOR_INSTRUCTION` to the content sent to `client.query`,
  directing the executor to call the advisor tool for that turn only.
  Sessions without an advisor model configured treat the flag as a
  no-op (graceful degradation).  OpenAPI spec regenerated;
  `docs/openapi.json` updated.

- **Probe log retention `--max-age-days`** (finding feature-11-005):
  Both `scripts/daily_probe.py` and `scripts/diff_probe.py` now
  prune old probe logs after each successful write. Files in the
  probe log directory matching `YYYY-MM-DD.log` whose date is more
  than `--max-age-days` days old are deleted. Default retention
  window: **30 days** (`PROBE_LOG_RETENTION_DAYS_DEFAULT = 30`).
  Pass `--max-age-days 0` to disable pruning entirely (useful during
  the dogfood window when full log history is wanted). Pruning errors
  are non-fatal and warning-logged so a permission edge-case never
  crashes the probe. Retention contract documented in
  `docs/behavior/routing.md §"Probe log retention"`.

### Changed

- **Status-bar decorative pills removed** (wiring-v1-daily-driver item 4.2):
  "Recovery: Idle", "Auto-save: Idle", and "IDLE" pills had no backing stores
  in v1 and were removed from `+layout.svelte`. No functionality was lost.

- **Keyboard bindings hygiene** (wiring-v1-daily-driver item 4.1): strip
  unbound chords from the cheat sheet; wire simple navigation/create chords.
  - **Stripped** (surface absent): `T` (template picker), `Ctrl+Shift+P`
    (command palette), `Ctrl+Shift+O` (pending-ops card) — removed from
    `bindings.ts` and their constants/labels from `config.ts`.
  - **Wired** in `+layout.svelte` via `bindHandler` on `onMount`:
    `C` → `goto("/sessions/new")`, `Shift+C` →
    `goto("/sessions/new?bare=1")`, `J`/`K`/`Alt+]`/`Alt+[` → sidebar
    selection step through `sessionsStore.sessions`, `Alt+1`–`Alt+9` →
    jump to sidebar slot _n_.
  - `frontend/src/routes/sessions/new/+page.svelte` — skips
    `hydrateDefaults()` (last-session pre-fill) when `?bare=1` is present,
    giving `Shift+C` a clean form.
  - Tests in `dispatch.test.ts` + `CheatSheet.test.ts` updated to match the
    trimmed binding table.

### Added

- **Import from Bearings** — `POST /api/import/bearings` copies all sessions,
  messages, tags, tag memories, and checklist items from the main Bearings
  database (`~/.local/share/bearings/db.sqlite`) into the v1 database.
  Duplicate rows (by primary key) are skipped; the entire operation is
  transactional (all-or-nothing). The `/settings` page exposes an
  "Import now" button with a result summary showing imported/skipped counts
  and any error messages.
  - `src/bearings/db/import_bearings.py` — `import_from_bearings(dest, source_path)`
    function and `ImportResult` dataclass. Handles column mapping for schema
    differences (e.g., `default_working_dir` → `working_dir` on tags;
    `message_count=0`, `closing_summary=NULL` on imported sessions).
  - `src/bearings/web/routes/import_db.py` — `POST /api/import/bearings`
    endpoint; returns `ImportResultOut` Pydantic model with per-table counts.
  - `frontend/src/lib/api/import.ts` — `importFromBearings()` client.
  - `frontend/src/routes/settings/+page.svelte` — **Import section** with
    "Import now" button, result summary on success, and error display.
  - `src/bearings/config/constants.py` — `ROUTE_TAG_IMPORT` constant.
  - `frontend/src/lib/config.ts` — `API_IMPORT_BEARINGS_ENDPOINT` constant.
  - Tests: `tests/test_import_bearings.py` (10 DB layer tests),
    `tests/test_import_api.py` (3 route tests).

- **Default-from-last-session auto-fill** (wiring-v1-daily-driver item 3.4).
  - `frontend/src/lib/api/sessions.ts` — `getMostRecentSession()` helper:
    calls `listSessions({includeClosed: true})` and returns the first row
    (sorted `updated_at DESC` by the backend) or `null` when no sessions exist.
  - `frontend/src/routes/sessions/new/+page.svelte` — replaces the
    preferences-only `hydratePrefs()` call with `hydrateDefaults()`: fetches
    the most-recently-updated session on mount and pre-fills `workingDir` +
    `initialExecutor` from it; falls back to the preferences-API defaults
    (item 3.2) only when no prior session exists; both sources are
    overridable before submit. No templates picker — deferred.

- **Permission-mode toggle** (wiring-v1-daily-driver item 3.3).
  - `src/bearings/db/sessions.py` — `update_permission_mode` DB helper.
    Validates non-`None` values against `KNOWN_SDK_PERMISSION_MODES`; `None`
    clears the column so the runner uses the profile default on next boot.
  - `src/bearings/web/models/sessions.py` — `SessionPermissionModeUpdate`
    Pydantic shape (`permission_mode: str | None`).
  - `src/bearings/web/routes/sessions.py` — `PATCH /api/sessions/{id}/permission_mode`
    endpoint. 422 on unknown mode; 404 on missing session; broadcasts upsert
    via sessions WS channel.
  - `frontend/src/lib/api/sessions.ts` — `patchSessionPermissionMode` helper.
  - `frontend/src/lib/config.ts` — `PERMISSION_MODE_SELECTOR_STRINGS`.
  - `frontend/src/lib/components/conversation/PermissionModeSelector.svelte` —
    header dropdown (Default / Accept edits / Bypass permissions / Plan only).
    Reads current mode from `sessionsStore`; PATCHes on change; disables
    during in-flight request; shows inline error on failure.
  - `frontend/src/lib/components/conversation/Conversation.svelte` — mounts
    `PermissionModeSelector` in a header bar at top of conversation pane.
  - `tests/test_sessions_api.py` — four new tests: happy-path swap,
    clear-to-null, unknown-mode 422, missing-session 404.

- **Preferences API + settings Defaults section** (wiring-v1-daily-driver item 3.2).
  - `src/bearings/db/schema.sql` — `preferences` singleton table
    (`id=1 CHECK`, `theme TEXT NOT NULL DEFAULT 'default'`, `default_model`,
    `default_permission_mode`, `default_working_dir`, `updated_at`). Seeded
    via `INSERT OR IGNORE` on every `load_schema` call.
  - `src/bearings/db/preferences.py` — `get_preferences` / `patch_preferences`
    DB helpers. `patch_preferences` accepts a `fields: frozenset[str]`
    parameter so the route layer can distinguish "omit" from "set to NULL".
  - `src/bearings/web/models/preferences.py` — `PreferencesOut` /
    `PreferencesPatch` Pydantic wire shapes.
  - `src/bearings/web/routes/preferences.py` — `GET /api/preferences` and
    `PATCH /api/preferences` (partial update via `model_fields_set`).
  - `src/bearings/web/app.py` — mounts preferences router.
  - `src/bearings/config/constants.py` — `ROUTE_TAG_PREFERENCES`.
  - `frontend/src/lib/api/preferences.ts` — `getPreferences` / `patchPreferences` helpers.
  - `frontend/src/lib/config.ts` — `API_PREFERENCES_ENDPOINT`,
    `KNOWN_PERMISSION_MODES`, `PERMISSION_MODE_LABELS`, `PREFERENCES_STRINGS`.
  - `frontend/src/routes/settings/+page.svelte` — **Defaults section** with
    four selects/inputs (theme, default model, default permission mode,
    default working dir). Reads on mount, writes on "Save defaults" click,
    shows "Saved." feedback for 2 s.
  - `frontend/src/lib/components/new_session/NewSessionForm.svelte` —
    `initialExecutor` prop; initial executor state seeded from it.
  - `frontend/src/routes/sessions/new/+page.svelte` — fetches
    `/api/preferences` on mount; pre-fills working directory and executor
    model from defaults (fails silently so form still works offline).
  - `~/.local/share/bearings-v1/launch.py` — calls `load_schema` on the
    DB connection at startup so schema migrations apply on boot.

- **Folder picker for new-session form** (wiring-v1-daily-driver item 3.1).
  - `src/bearings/web/routes/fs.py` — `POST /api/fs/pick` endpoint. Validates
    the requested root against configured `allow_roots`; falls back to the
    user's home directory when `allow_roots` is empty so the picker works on
    default installations. Returns `{token, path, entries, capped}`. Each call
    issues a fresh UUID token (reserved for future server-side session
    tracking). Traversal reuses the same endpoint — no separate navigation
    route needed.
  - `src/bearings/web/models/fs.py` — `FsPickIn` (request body; `root: str`)
    and `FsPickOut` (response; adds `token: str` to the listing shape).
  - `frontend/src/lib/api/fs.ts` — new `pickDir(root?)` client function.
  - `frontend/src/lib/components/new_session/FolderPicker.svelte` — new
    interactive directory browser. Renders as a compact field (current value +
    "Browse…" button). Opening the overlay calls `POST /api/fs/pick` at the
    current value (or home dir). Keyboard: ArrowDown/Up navigate the list;
    Enter on a highlighted directory descends into it; Enter with no highlight
    selects the currently displayed path; Tab auto-completes the filter to the
    first match; Backspace on an empty filter goes up one level; Esc closes
    without changing the value.
  - `frontend/src/routes/sessions/new/+page.svelte` — plain text input for
    working directory replaced with `FolderPicker`.
  - `docs/openapi.json` — regenerated (adds `POST /api/fs/pick`).

- **Sessions-broadcast WS channel** (wiring-v1-daily-driver item 2.6).
  - `src/bearings/web/routes/ws_sessions.py` — new `SessionsBroadcaster`
    class (fan-out hub) + `GET /ws/sessions` WebSocket endpoint. Three
    message types: `session_upsert` (full `SessionOut` JSON), `session_delete`
    (session_id only), `runner_state` (is_running + is_awaiting_user flags).
    Heartbeat sent on idle to keep connections alive. Auto-reconnect with
    capped exponential backoff handled on the frontend side.
  - `src/bearings/config/constants.py` — `ROUTE_TAG_WS_SESSIONS` constant.
  - `src/bearings/agent/runner.py` — `wire_status_hook()` method +
    `_status_hook` callback field; `set_status()` now calls the hook
    synchronously after updating so the broadcast is immediate.
  - `src/bearings/web/runner_factory.py` — `InProcessRunnerRegistry`
    and `build_in_process_factory` accept optional `sessions_broadcaster`;
    `_wire_status_hook()` attaches a closure to each new runner on first
    touch so runner-state changes fan out to all `/ws/sessions` subscribers.
  - `src/bearings/web/routes/sessions.py` — `create_session`, `patch_session`,
    `patch_session_model`, `close_session`, `reopen_session` each call
    `broadcaster.publish_upsert(out)` after the mutation; `delete_session`
    calls `broadcaster.publish_delete(session_id)`.
  - `src/bearings/web/app.py` — creates `SessionsBroadcaster`, stores it on
    `app.state.sessions_broadcaster`, threads it through
    `build_in_process_factory`, mounts `ws_sessions_router`.
  - `frontend/src/lib/config.ts` — `WS_SESSIONS_PATH` constant.
  - `frontend/src/lib/api/wsSessions.ts` — `connectSessionsBroadcast()`
    opens `/ws/sessions`, parses frames into typed
    `SessionsBroadcastEvent` union, auto-reconnects with exponential
    backoff (500 ms initial, ×2, cap 30 s).
  - `frontend/src/lib/stores/sessions.svelte.ts` — calls
    `connectSessionsBroadcast` at module load; `session_upsert` merges
    into the session list (replace in-place or prepend if new);
    `session_delete` removes the matching row. All open tabs update
    without reload or polling.

- **Composer essentials** (wiring-v1-daily-driver item 2.5).
  - `frontend/src/lib/composer/draftStore.svelte.ts` — per-session draft
    persistence to `localStorage` under `bearings-v1:draft:{sessionId}`.
    Degrades silently in private-browsing / quota-full contexts.
  - `frontend/src/lib/composer/inputHistory.ts` — `InputHistory` class;
    shell-readline-style Up/Down walk through sent messages (in-memory,
    per page-load); deduplicates consecutive identical sends; restores the
    live draft when Down is pressed past the newest entry.
  - `frontend/src/lib/config.ts` — `COMPOSER_DRAFT_KEY_PREFIX` constant.
  - `frontend/src/lib/components/composer/Composer.svelte` — auto-grow
    textarea (height tracks `scrollHeight`, capped at `max-h-64`); loads
    persisted draft on mount and on session switch; saves draft on every
    keystroke; clears draft + records history on successful send;
    `ArrowUp` at cursor position 0 walks back through history, `ArrowDown`
    at cursor end walks forward; modified arrow keys (Shift/Ctrl/etc.)
    pass through unmodified.

- **Sidebar search** (wiring-v1-daily-driver item 2.4).
  - `src/bearings/web/routes/history.py` — `GET /api/history/search?q=`
    performs case-insensitive LIKE search over `sessions.title`,
    `sessions.description`, and `messages.content`. Returns up to 50 hits
    (session hits first, then message hits); each hit carries a `kind`,
    `session_id`, `session_title`, optional `message_id`, and a 120-char
    snippet centred on the first match occurrence. Empty / blank queries
    return immediately without touching the DB.
  - `src/bearings/web/models/history.py` — `HistorySearchResult` Pydantic model.
  - `src/bearings/config/constants.py` — `HISTORY_SEARCH_RESULT_CAP`,
    `HISTORY_SEARCH_SNIPPET_CHARS`, `HISTORY_SEARCH_DEBOUNCE_MS`, and
    `ROUTE_TAG_HISTORY` constants.
  - `src/bearings/web/app.py` — mounts history router.
  - `frontend/src/lib/config.ts` — `API_HISTORY_SEARCH_ENDPOINT`,
    `HISTORY_SEARCH_DEBOUNCE_MS`, `HISTORY_SEARCH_RESULT_CAP`, and
    `SIDEBAR_SEARCH_STRINGS`.
  - `frontend/src/lib/api/history.ts` — `searchHistory(q)` client; returns
    empty array on network/server error for graceful sidebar degradation.
  - `frontend/src/lib/components/sidebar/SidebarSearch.svelte` — full-screen
    overlay: debounced input (300 ms), scrollable results list with SESSION /
    MESSAGE kind badges, ArrowUp/Down keyboard navigation, Enter to select,
    Escape to close, backdrop click to close. Clicking a result calls
    `goto('/sessions/{id}')` with `#msg-{id}` hash for message hits.
  - `frontend/src/routes/+layout.svelte` — mounts `<SidebarSearch />`.
  - `frontend/src/lib/keyboard/bindings.ts` — `KEYBINDING_ACTION_FOCUS_SIDEBAR_SEARCH`
    wired as `Ctrl+K` (`global: true`); `displayOnly: true` removed.

- **Slash-command palette** (wiring-v1-daily-driver item 2.3).
  - `src/bearings/web/routes/commands.py` — `GET /api/commands` scans
    `~/.claude/commands/**/*.md` (user commands), `~/.claude/skills/*/SKILL.md`
    (skills), and `<working_dir>/.claude/commands/**/*.md` (project commands).
    Parses YAML frontmatter for `name` + `description`; falls back to filename
    stem / first body line. Returns `[{name, description, source}]`.
  - `src/bearings/web/models/commands.py` — `CommandOut` Pydantic model.
  - `src/bearings/config/constants.py` — `ROUTE_TAG_COMMANDS` constant.
  - `src/bearings/web/app.py` — mounts commands router.
  - `frontend/src/lib/config.ts` — `API_COMMANDS_ENDPOINT` + `COMMAND_MENU_STRINGS`.
  - `frontend/src/lib/api/commands.ts` — `listCommands()` client; gracefully
    returns empty list on network/server error.
  - `frontend/src/lib/components/composer/CommandMenu.svelte` — typeahead
    listbox; shows all commands on bare `/`; filters by name + description
    substring; ArrowUp/Down navigate; Tab/Enter confirm; Escape dismisses;
    source badge (User / Skill / Project); scroll-into-view on active change.
  - `frontend/src/lib/components/composer/Composer.svelte` — opens
    `CommandMenu` when draft starts with `/`; closes once a space follows
    the command token (selection done); keyboard events delegated to
    `CommandMenu.handleKey` before normal submit logic.

- **Context/token meter in header** (wiring-v1-daily-driver item 2.2).
  - `src/bearings/agent/events.py` — re-added `model: str | None`,
    `is_auto_compact_enabled: bool | None`, and `auto_compact_threshold: int | None`
    to `ContextUsage`. All three default to `None` so older SDK builds that omit
    the fields remain wire-compatible.
  - `src/bearings/agent/translate.py` — `_project_context_usage` return type
    widened to a six-tuple; extracts `model` / `isAutoCompactEnabled` /
    `autoCompactThreshold` from the SDK camelCase usage dict (snake_case fallback
    for forward-compat). `_feed_result` propagates all six fields to the emitted
    `ContextUsage` event.
  - `frontend/src/lib/api/events.ts` — `ContextUsageEvent` extended with the
    three new optional fields.
  - `frontend/src/lib/stores/conversation.svelte.ts` — added `ContextUsageSnapshot`
    interface; added `contextUsage: ContextUsageSnapshot | null` and
    `cacheHitRatio: number | null` to `ConversationState`; reset in
    `resetConversation`; two new imperative reducer arms: `applyContextUsage`
    (overwrites snapshot on every `context_usage` frame) and `applyCacheHit`
    (computes `cache_read_tokens / (executor_input_tokens + cache_read_tokens)`
    from `message_complete`).
  - `frontend/src/lib/config.ts` — added `CONTEXT_METER_STRINGS` string table
    and `CONTEXT_METER_WARN_BAND_PCT = 15` constant.
  - `frontend/src/lib/components/conversation/ContextMeter.svelte` — new header
    strip: thin progress bar (% context used), percentage label, total-token count
    (formatted as 3.2k / 1.4M), cache-hit ratio from the last turn's
    `message_complete`. Warn band (amber tint + "⚠ compact" badge) fires when
    `percentage` is within 15 % of the auto-compact threshold; falls back to
    warning above 85 % when auto-compact is enabled but the threshold token count
    is not present. Hidden (no DOM node) until the first `context_usage` frame
    arrives. A vertical marker line on the bar shows the threshold position when
    `autoCompactThreshold` is set.
  - `frontend/src/routes/+layout.svelte` — imports and mounts `<ContextMeter />`
    immediately after the `<header>` closing tag so it renders as a slim strip
    between the session header and the conversation body.

- **Live todos panel** (wiring-v1-daily-driver item 2.1).
  - `src/bearings/agent/sdk_loop.py` — after emitting a `ToolCallStart` for
    `TodoWrite`, immediately emits a `TodoWriteUpdate` event carrying the parsed
    todos array as `todos_json`. Added `_make_todo_update()` helper; imports
    `json`, `TodoWriteUpdate`, `ToolCallStart`.
  - `frontend/src/lib/stores/conversation.svelte.ts` — added `LiveTodoItem`
    interface (flexible schema: `id?`, `content`, `status`, `priority?`,
    `activeForm?`); added `liveTodos: LiveTodoItem[]` to `ConversationState`;
    resets to `[]` in `resetConversation` (session-switch clears the panel);
    new `applyTodoState()` imperative arm parses `todos_json` and updates
    `liveTodos`; wired into `ingestFrame` alongside `applyApprovalState`.
  - `frontend/src/lib/components/conversation/LiveTodos.svelte` — new
    collapsible panel; hidden when `liveTodos` is empty; header shows
    completed/total count; each item shows status icon (✓/●/○) and optional
    priority badge (H/M/L); completed items rendered muted + strikethrough;
    uses `todo.id ?? todo.content ?? index` as stable Svelte key to handle the
    SDK's built-in TodoWrite schema (which omits `id`).
  - `frontend/src/lib/components/conversation/Conversation.svelte` — mounts
    `<LiveTodos />` above the scroll body as a sticky strip.
  - `frontend/src/lib/config.ts` — added `LIVE_TODOS_STRINGS` string table.

- **`runner_status` event + `turn_replayed` reducer** (wiring-v1-daily-driver item 1.4).
  - `src/bearings/agent/events.py` — added `RunnerStatusEvent` (`type:
    "runner_status"`, `streaming_active: bool`, `current_turn_id: str | None`)
    to the `AgentEvent` discriminated union. Sent once per WS connect after the
    replay drain so clients can reconcile their spinner state on reconnect.
  - `src/bearings/agent/runner.py` — added `get_status_event()` method to
    `SessionRunner`; synthesises a `RunnerStatusEvent` from `_status.is_running`
    and a reverse-scan of the ring buffer for the most recent `MessageStart`;
    imports `MessageStart` and `RunnerStatusEvent` from `events`.
  - `src/bearings/web/streaming.py` — `serve_session_stream` now calls
    `runner.get_status_event()` after `_send_replay` and sends the result as
    `event_frame(seq=0, …)`; seq=0 is intentional (synthetic frame, not ring-
    buffered) and the frontend handles it before the seq-dedup filter.
  - `frontend/src/lib/api/events.ts` — added `RunnerStatusEvent` interface and
    included it in the `AgentEvent` union.
  - `frontend/src/lib/config.ts` — added `turnResumedLabel: "↻ resumed"` to
    `CONVERSATION_STRINGS`.
  - `frontend/src/lib/stores/conversation.svelte.ts` — added `streamingActive:
    boolean` and `currentTurnId: string | null` to `ConversationState` (reset
    in `resetConversation`); added `applyRunnerStatus` (called before seq-dedup
    for `runner_status` frames) and `applyStreamingState` (sets/clears
    `streamingActive`/`currentTurnId` on `message_start`, `message_complete`,
    `error`); added `resumed: boolean` to `MessageTurnView`; `turn_replayed`
    arm in `applyEvent` now marks the matching user row with `resumed: true`
    instead of being a no-op; `runner_status` added as an explicit exhaustive
    case.
  - `frontend/src/lib/components/conversation/MessageTurn.svelte` — user bubble
    now renders a `<span data-testid="message-turn-resumed">↻ resumed</span>`
    annotation when `turn.resumed` is true.
  - `frontend/src/lib/components/conversation/Conversation.svelte` —
    `hasInFlightTurn` derived now gates on `conversationStore.streamingActive &&
    turns.some(!complete)` so the Stop button is hidden when the runner is idle
    even if the replay left an incomplete assistant turn open.
  - `tests/test_streaming_unit.py` — added `RunnerStatusEvent` fixtures to the
    parametrised round-trip test (active + idle variants).
  - `tests/test_streaming_reconnect.py` — added three tests for
    `get_status_event()` covering idle runner, running runner with
    `MessageStart` in buffer, and multi-turn reverse-scan ordering.
  - `tests/test_streaming_integration.py` — updated `close_after` budgets in
    `test_live_tool_output_streaming_roundtrip` (+1 for runner_status) and
    `test_heartbeat_fires_when_idle` (+1 for runner_status); both tests now
    assert the synthetic first frame.

- **ApprovalModal + AskUserQuestionModal** (wiring-v1-daily-driver item 1.1).
  - `frontend/src/lib/components/conversation/ApprovalModal.svelte` — generic
    allow / deny modal shown when the agent needs permission to use a tool.
    Resolves via `POST /api/sessions/{id}/approvals/{request_id}` and stays
    open until the `approval_resolved` WS event arrives so multi-tab resolution
    (Tab B approves → Tab A modal closes) works automatically.
  - `frontend/src/lib/components/conversation/AskUserQuestionModal.svelte` —
    text-input variant shown when `tool_name === 'AskUserQuestion'`; the user's
    typed answer is sent as `{ approved: true, answer: "…" }` and the backend
    threads it back to the SDK callback as `PermissionResultAllow.updated_input`.
  - `frontend/src/lib/api/approvals.ts` — typed client for the approval
    endpoint (handles 204 No Content without the shared `postJson` helper).
  - `frontend/src/lib/stores/conversation.svelte.ts` — added `PendingApproval`
    interface and `pendingApproval: PendingApproval | null` state; `ingestFrame`
    now calls `applyApprovalState` to set/clear it on `approval_request` /
    `approval_resolved` events; `resetConversation` zeroes it on session switch.
  - `frontend/src/lib/components/conversation/Conversation.svelte` — mounts the
    appropriate modal based on `conversationStore.pendingApproval`.
  - `frontend/src/lib/config.ts` — added `sessionApprovalEndpoint` URL helper
    and `APPROVAL_STRINGS` i18n table.
  - `src/bearings/web/models/approvals.py` — added `answer: str | None = None`
    to `ApprovalResolution` for the `AskUserQuestion` answer payload.
  - `src/bearings/agent/approval.py` — `ApprovalBroker` now holds a
    `_answers` side-channel dict; `resolve(answer=…)` stores the text before
    resolving the future so the `_can_use_tool` callback can pass it as
    `updated_input`; `cancel_all` clears it.
  - `src/bearings/web/routes/approvals.py` — passes `answer=payload.answer`
    to `broker.resolve`.

- **Message pagination cursor** (wiring-v1-daily-driver item 1.3).
  - `src/bearings/db/messages.py` — added `seq: int` field to `Message`
    (SQLite `rowid` alias); `list_for_session` now accepts `before: int | None`
    which filters `WHERE rowid < before` for backward pagination; pre-INSERT
    validation calls use `seq=0` placeholder since the rowid is DB-assigned.
  - `src/bearings/config/constants.py` — added `MESSAGE_PAGE_SIZE = 100` for
    the session-open tail fetch and each `loadOlder()` page.
  - `src/bearings/web/models/messages.py` — added `seq: int` to `MessageOut`;
    added `MessagePage` model (`items: list[MessageOut]`, `has_more: bool`).
  - `src/bearings/web/routes/messages.py` — `GET /api/sessions/{id}/messages`
    now returns `MessagePage` instead of `list[MessageOut]`; accepts `before:
    int | None` query param; fetches `limit+1` rows and trims from the front
    to detect `has_more` without a separate `COUNT` query.
  - `docs/openapi.json` — regenerated to reflect the new endpoint shape.
  - `frontend/src/lib/api/messages.ts` — added `seq: number` to `MessageOut`;
    added `MessagePage` interface; updated `listMessages` params to include
    `before?: number`; return type changed to `Promise<MessagePage>`.
  - `frontend/src/lib/config.ts` — added `MESSAGE_PAGE_SIZE = 100` and two
    new `CONVERSATION_STRINGS` entries (`loadOlderLabel`, `loadingOlder`).
  - `frontend/src/lib/stores/conversation.svelte.ts` — added `hasMore`,
    `loadingOlder`, `oldestSeq` state; `hydrateTurns` now accepts `MessagePage`
    and seeds `hasMore`/`oldestSeq` from the response; added `prependTurns`
    for prepend-to-front on `loadOlder`; added async `loadOlder(sessionId)`
    action that no-ops when already loading or `hasMore` is false.
  - `frontend/src/lib/components/conversation/Conversation.svelte` — session-
    open fetch uses `limit: MESSAGE_PAGE_SIZE` instead of unbounded; wires
    `loadOlder` to a "Load older messages" button rendered at the top of the
    conversation body when `hasMore` is true.
  - `frontend/src/lib/components/inspector/InspectorRouting.svelte` — updated
    `fetchMessages` result accessor to `page.items` (full-transcript fetch,
    `has_more` is always false for the inspector).

- **Stop / cancel turn** (wiring-v1-daily-driver item 1.2).
  - `src/bearings/agent/runner.py` — added `_stop_event: asyncio.Event`,
    `stop_event` property, and `request_stop()` method to `SessionRunner`.
    Calling `request_stop()` sets the event; the SDK loop's watcher
    clears it at the start of each new turn.
  - `src/bearings/agent/sdk_loop.py` — `_run_one_turn` now spawns a
    `_stop_watcher` background task that awaits `runner.stop_event` and
    forwards `session.interrupt()` → `client.interrupt()` when the user
    clicks Stop. The watcher is always cancelled in the turn's `finally`
    block; `_do_run_one_turn` holds the former body.
  - `src/bearings/web/routes/sessions.py` — new `POST
    /api/sessions/{id}/stop` endpoint; 204 on success (even when no
    runner is live), 404 for unknown session, 503 if the registry is
    not the `InProcessRunnerRegistry`.
  - `frontend/src/lib/api/sessions.ts` — added `stopSession()` helper
    (raw fetch, handles 204 No Content like `postApproval`).
  - `frontend/src/lib/components/conversation/StopUndoInline.svelte` —
    new inline Stop button; visible while any assistant turn is
    incomplete; disables itself after the first click to prevent double-
    submission; re-enables on error so the user can retry.
  - `frontend/src/lib/components/conversation/Conversation.svelte` —
    mounts `StopUndoInline` when `hasInFlightTurn && sessionId !== null`.
  - `frontend/src/lib/config.ts` — added `sessionStopEndpoint` URL
    helper and `stopTurnLabel` / `stopTurnAriaLabel` to
    `CONVERSATION_STRINGS`.
  - `docs/openapi.json` — regenerated to include the new stop endpoint.

- **UI/UX gap sweep — Phases 1–7** (commits `d2387ff`–`0e42f9f`). Filled
  the gaps identified by `UI_AUDIT.md` (2026-05-03 audit against spec).

  *Phase 1 — Conversation UX:*
  - Reopen-session button in closed-session footer.
  - Error block styling: left red border, label, hint text.
  - "Ask for more detail" button on assistant bubbles (inserts a
    canned prompt via `composerBridge`).
  - Regenerate context-menu handler wired to `POST /api/sessions/{id}/regenerate`.

  *Phase 2 — Paired-chat wiring:*
  - `GET /api/sessions/{id}/paired-chat-info` backend route +
    `get_paired_chat_info()` DB query.
  - `PairedChatIndicator` mounted in conversation header (parent
    checklist breadcrumb).
  - `↳ <parent>` annotation on `SessionRow` sidebar rows.

  *Phase 3 — Vault drag-to-composer:*
  - `VaultPanel` rows are draggable; `Composer` accepts drops and
    inserts the vault entry's markdown link at cursor position.
  - CLI subprocess stderr now routed to journald with session prefix
    via `ClaudeAgentOptions.stderr` callback (helps diagnose init stalls).

  *Phase 4 — Error state recovery:*
  - `RunnerStatus.is_error` flag; `_enter_error_state` sets it so
    `runner_state` WS frames carry the error signal immediately.
  - Sessions store: `runner_state.is_error=true` flips local
    `session.error_pending` without waiting for a page reload.
  - `set_error_pending(db, session_id, value)` DB helper.
  - `POST /api/sessions/{id}/recover` (handler `resume_session`) — clears
    `error_pending`, triggers runner reap-recovery respawn, broadcasts
    the updated session row.
  - `recoverSession()` API client + Recover button in the error block
    with loading state.
  - Sidebar error pip gains `animate-pulse` (spec: "red flashing pip").

  *Phase 5 — Global command palette:*
  - `Ctrl+Shift+P` keybinding (global) wired in `bindings.ts`.
  - `CommandPalette.svelte` modal: search filter, arrow-key + Enter
    navigation, click/hover, backdrop/Escape to close; selection inserts
    `/command` into the active composer.
  - `KeybindingsProvider` mounts palette alongside cheat sheet; opening
    one closes the other.

  *Phase 6 — Theme silent-flip fix:*
  - `resolveBootTheme()` now persists the OS-fallback choice to
    localStorage on first boot so the `app.html` static
    `data-theme="evergreen"` matches subsequent loads (no more
    evergreen → paper-light flash for light-scheme OS users).

  *Phase 7 — Documentation:*
  - `UI_AUDIT.md` updated to reflect resolved gaps.
  - `TODO.md` resolved entries struck: `POST /recover` route and
    theme-flicker entries.
  - `docs/openapi.json` regenerated to include `POST /recover`.

### Fixed

- **`PATCH /api/sessions/{id}` with `tag_ids` skipped the cardinality
  guard** (`web/routes/sessions.py:patch_session`). `POST /api/sessions`
  calls `_validate_tag_cardinality` before persisting; the PATCH bulk-replace
  path called `tags_db.set_for_session` directly without that check, allowing
  a client to permanently land a session with two project-class or two
  severity-class tags via PATCH. Fix: call `_validate_tag_cardinality(db,
  new_tag_ids)` inside `patch_session` immediately after the existence check
  and before any data is written. Collaterally fixed a latent `TypeError`
  (`row["id"]` on a plain-tuple aiosqlite row in the PATCH existence-check
  query; production was unaffected because `serve.py` sets `row_factory`,
  but the bug would have surfaced as soon as a test exercised the path).
  Regression tests added: two 422 paths (double-project, double-severity)
  and one 200 happy path (one of each class plus general).

- **conversation transcript hit `each_key_duplicate` on every page load**
  (`stores/conversation.svelte.ts:applyEvent`). `resetConversation`
  zeroes `lastSeq`, hydrate seeds turns from the REST `/messages`
  history but doesn't bump `lastSeq`, and the WS subscription opens
  without a `since_seq` cursor — so the server replays every event
  from seq 0 and the reducer blindly appended `user_message` /
  `message_start` turns whose ids were already on the page. Svelte's
  `{#each (id)}` rejected the duplicate key and refused subsequent
  appends, so newly-arrived events couldn't render either (Dave's
  "text disappears, never shows up in the conversation"). Make the
  two create-events idempotent: skip the append when a turn with
  that id already exists.
- **`fallback_model == model` crashed the SDK CLI** for `haiku` sessions
  (`agent/sdk_loop.py:_to_sdk_options`). The bearings
  `EXECUTOR_FALLBACK_MODEL` table maps `haiku → haiku` to encode "no
  further fallback", but the Claude CLI rejects identical pairs with
  `Error: Fallback model cannot be the same as the main model`. Drop
  the SDK option when the resolved fallback equals the main model;
  the SDK then runs without a fallback override, which is the same
  semantic the table was trying to express.
- **agent loop never spawned — every posted prompt queued forever**
  (`bearings/cli/serve.py`, stopgap `~/.local/share/bearings-v1/launch.py`).
  Both boot paths called `create_app()` *without* `db_connection`,
  then set `app.state.db_connection` in a FastAPI startup hook. But
  `create_app` (`web/app.py:149`) checks `db_connection` at construction
  time to wire `session_setup` on the runner factory; with `None` it
  falls into the test-only branch (`build_in_process_factory()` with
  no setup callable). Every `POST /api/sessions/{id}/prompt` queued
  on the runner but no supervisor task was ever spawned — `is_running:
  false`, `queue_length: N`, `ring_buffer_size: 0`, no SDK subprocess
  child. Open the DB synchronously *before* `create_app` so the
  factory ships with `session_setup` from the start.
- **composer footer invisible in paper-light** — wrapper used
  `bg-surface-1` (244,240,230), only 6 RGB units off the conversation
  body's `bg-surface-0` (250,247,240). Switched to `bg-surface-2`
  (234,228,213) for clearly distinct elevation in paper-light;
  evergreen / midnight-glass still have ample contrast at the new
  token. The textarea below it picks up `bg-surface-0` and reads as a
  proper inset.
- **`~`-prefixed `working_dir` would crash the SDK** if the agent loop
  ever reached chdir (`agent/session_bootstrap.py`). Expand `~` at the
  SDK boundary so a session row stored as `~/Projects/...` (the
  inspector's display form) resolves to an absolute path the SDK can
  chdir into. Defensive — masked by the agent-loop bug above, but
  would surface as soon as that was fixed.
- **theme contrast on light themes** — scoped style blocks across
  `routes/sessions/new`, `routes/tags`, `routes/settings`,
  `routes/analytics`, `lib/components/new_session/*`, and
  `lib/components/routing/*` referenced undeclared CSS variable names
  (`--surface-1/2/3`, `--fg`, `--fg-muted`, `--accent-info`,
  `--accent-danger`, `--bg`, `--border`). Every reference fell through
  to its hardcoded dark-color fallback regardless of `data-theme`,
  producing a dark "New Session" card on a paper-light page with
  near-invisible tag-chip text. Remapped surface / fg / accent / border
  refs to the actual themed `--bearings-*` channel-triple tokens; warn /
  error / ok semantic colors stay inlined as literals (no theme
  vocabulary for them yet).

## [1.0.0] — 2026-05-01

The stability commitment. v1.0.0 promotes the v0.18.0 rebuild after a
two-week dogfood window against the live `bearings-v1.service` running
concurrently with v0.17.x. The public HTTP surface (107 paths, 95
schemas, 134 operations — see [`docs/openapi.json`](docs/openapi.json)), the
per-subsystem behavior contracts under [`docs/behavior/`](docs/behavior/),
and the routing/quota wire shapes in
[`docs/model-routing-v1-spec.md`](docs/model-routing-v1-spec.md)
Appendix A are now the SemVer-governed compatibility surface — breaking
changes ship in v2.0.0, additive changes in v1.x, fixes in v1.0.x.

### Stability commitment

What this means concretely:

* **HTTP API**: paths and request/response schemas listed in
  `docs/openapi.json` will not be removed or shape-changed within the
  v1.x line. New optional fields and new endpoints are additive (minor
  bump). Removals or required-field changes require a v2 cutover.
* **Routing/quota wire shapes**: `RoutingDecision`, `RoutingRule`,
  `SystemRoutingRule`, and `QuotaSnapshot` (frozen dataclasses, spec
  Appendix A) are the JSON contract every routing client sees.
  Additive evolution only within v1.x.
* **On-disk schema**: `~/.local/share/bearings-v1/sessions.db` keeps
  its v0.18.0-shipped schema; future column additions arrive via
  forward-only migrations that v1.x clients can read. Removals require
  v2.
* **Behavior docs**: `docs/behavior/<subsystem>.md` is the
  observable-behavior contract. Drift between the docs and the
  service is treated as either a doc bug or a code bug — not a "the
  spec is just guidance" situation. Behavior addenda (per the plan's
  "Behavioral gap escalation" §) extend, never silently override.
* **WebSocket message shapes**: JSON payloads on `/ws/sessions/{id}`
  and `/ws/sessions` (the fan-out channel) are part of the
  SemVer-governed surface. Their schema is the contract documented in
  `docs/behavior/tool-output-streaming.md`. Additive fields are
  permitted in v1.x; field removals or type changes require v2.
* **CLI flag surface**: `bearings serve`, `bearings init`,
  `bearings gc`, `bearings todo`, and `bearings migrate` — including
  their named flags (`--host`, `--port`, etc.) — are stable within
  v1.x. Flag renames or removals ship in v2.0.0. New optional flags
  are additive (minor bump). The flag contract lives in
  `src/bearings/cli/`.

What this does *not* mean: localhost-only posture, single-user model,
SQLite backend, and the orphan `v1-rebuild` history are all retained
from v0.18.0 — none of them rotate to v2 territory just because the
tag flipped.

### Dogfood window summary

The window ran on the live v1 service against the same DB Dave uses
day-to-day. Coverage:

* **Daily probe** (`scripts/daily_probe.py`, item B.1) — six endpoints
  (`/api/health`, `/api/sessions?limit=5`, `/api/quota/current`,
  `/api/quota/history`, `/openapi.json`, `/metrics`) hit by a
  systemd-user timer (`bearings-v1-probe.timer`, daily 09:15 local).
  Logs to `~/.local/share/bearings-v1/probes/YYYY-MM-DD.log`. Final
  window: PASS on every run.
* **Differential probe** (`scripts/diff_probe.py`, item B.2) — five
  surfaces diffed against the v0.17.x service on port 8787
  (`/api/health`, `/api/sessions?limit=5`, `/api/tags`,
  `/openapi.json` path-set, `/metrics` name-set). Logs to
  `~/.local/share/bearings-v1/diff-probes/YYYY-MM-DD.log`. Final
  window: 0 reachability failures. Shape divergence on
  `openapi_paths` and `metric_names` is the *expected* delta — v1
  removes legacy v0.17 endpoints (e.g. `/api/preferences/*`,
  per-session `/api/sessions/{id}/checklist*`) and adds the routing /
  quota / usage surfaces, and rotates the metric set to the
  bearings_* names declared in `web/metrics.py`. Both deltas are
  documented in the spec and CHANGELOG and were not promoted to
  issues.
* **Issue triage protocol** (`docs/dogfood/issue-triage.md`, item
  B.3) — P0 / P1 / P2 ladder, fix-or-defer rubric, escalation paths
  back to the orchestrator. Final window: **0 P0**, **0 P1**, P2s
  (if any) carried into `TODO.md` for the v1.0.x backlog.
* **Final-readiness audit** (item D.1) — confirmed the probe history,
  the deferred-list, and the cutover-smoke acceptance gate
  (`scripts/cutover_smoke.py`, item 3.4) all green ahead of the tag.

### Added

* **Issue-triage protocol doc** (master item B.3).
  [`docs/dogfood/issue-triage.md`](docs/dogfood/issue-triage.md)
  defines the four issue sources (daily probe, differential probe,
  manual review windows C.1 / C.2, and ad-hoc), the P0 / P1 / P2
  severity labels, the fix-or-defer rubric, and the escalation paths
  back to the orchestrator session
  (`d4e89042507141f4a790a02459018152`). D.1 reads it as the
  final-readiness gate input.
* **Differential probe v0.17.x ↔ v1** (master item B.2). New
  `scripts/diff_probe.py` is a stdlib-only differential probe that
  hits equivalent endpoints on the live v0.17.x service (loopback
  port 8787) and the v1 service (port 8788), then diffs structural
  shape and logs the deltas. Three diff modes cover the
  heterogeneous surface: `json_shape` (recursive type-skeleton diff
  for `/api/health`, `/api/sessions?limit=5`, `/api/tags`),
  `openapi_paths` ((METHOD, path) set diff for `/openapi.json` —
  the highest-leverage mode, surfacing every endpoint added /
  removed / renamed in v1), and `metric_names` (Prometheus
  `# HELP <name>` set diff for `/metrics`). Logs one JSONL record
  per probe plus a `SUMMARY` trailer to
  `~/.local/share/bearings-v1/diff-probes/YYYY-MM-DD.log` (mode
  0700, append). Exit 0 = both sides reachable on every probe,
  1 = any reachability failure. Shape divergence is informational
  (logged, not gated) — observing divergence over the cutover
  window is the point. Backed by 28 unit tests in
  `tests/test_diff_probe.py` covering shape extraction,
  shape diff, OpenAPI path-set diff, Prometheus parse, log
  serialisation, and end-to-end orchestration through a fake
  transport. The `[tool.mypy]` `mypy_path = "scripts"` entry in
  `pyproject.toml` is added in the same commit so the test's
  `TYPE_CHECKING` import resolves cleanly under
  `mypy --strict`; this also clears the pre-existing
  `import-not-found` baseline that `tests/test_cutover_smoke.py`
  inherited from item 3.4.
* **Daily probe + systemd-user timer** (master item B.1). New
  `scripts/daily_probe.py` is a stdlib-only health probe (no httpx
  / venv dependency) that hits `/api/health`, `/api/sessions?limit=5`,
  `/api/quota/current` (the headroom-conceptual surface — the literal
  `/api/usage/headroom` named in the done-when text doesn't exist in
  v1's route surface; see the script docstring for the swap), the
  paired `/api/quota/history`, `/openapi.json`, and `/metrics`. Logs
  one JSONL record per probe plus a `SUMMARY` trailer to
  `~/.local/share/bearings-v1/probes/YYYY-MM-DD.log` (mode 0700,
  append). Exit 0 = all PASS, 1 = any FAIL.
* **Probe systemd units.** `config/bearings-v1-probe.service`
  (oneshot, hardened identical to `bearings-v1.service`) and
  `config/bearings-v1-probe.timer` (daily 09:15 local, 5min jitter,
  `Persistent=true`). Install:
  `cp config/bearings-v1-probe.{service,timer} ~/.config/systemd/user/
  && systemctl --user daemon-reload
  && systemctl --user enable --now bearings-v1-probe.timer`.
  Both pass `systemd-analyze --user verify`.
* **Differential-probe systemd units** (master item B.2, finding
  feature-11-003). `config/bearings-v1-diff-probe.service` (oneshot,
  hardened identical to `bearings-v1-probe.service`,
  `ReadWritePaths=%h/.local/share/bearings-v1/diff-probes`) and
  `config/bearings-v1-diff-probe.timer` (daily 09:20 local — five
  minutes after the B.1 daily probe — 5min jitter, `Persistent=true`,
  `After=bearings-v1-probe.service`). Install:
  `cp config/bearings-v1-diff-probe.{service,timer} ~/.config/systemd/user/
  && systemctl --user daemon-reload
  && systemctl --user enable --now bearings-v1-diff-probe.timer`.
  Both pass `systemd-analyze --user verify`.

### Changed

* **Package version** rolled `0.18.0.dev0` → `1.0.0` across
  `pyproject.toml`, `src/bearings/__init__.py`, `frontend/package.json`,
  `frontend/package-lock.json`, the SvelteKit sidebar `versionTag`
  string in `frontend/src/lib/config.ts`, and the regenerated
  `docs/openapi.json` (`info.version`).

## [0.18.0] — 2026-04-29

The v1 rebuild: behavioral parity with v0.17.x's feature surface, plus
model-routing v1, on a fresh tree (`v1-rebuild` branch, orphan
history). Concurrent run with v0.17.x is supported (port 8788, DB
`~/.local/share/bearings-v1/`, systemd unit `bearings-v1.service`).

### Added

* **Model routing v1** (per `docs/model-routing-v1-spec.md`):
  * `evaluate()` pure function for tag-rule + system-rule + default
    resolution (`agent/routing.py`).
  * Quota poller and `apply_quota_guard()` downgrade with manual-override
    accounting (`agent/quota.py`).
  * Override-rate aggregator with rolling 14-day window
    (`agent/override_aggregator.py`).
  * Routing / quota / usage HTTP endpoints per spec §9
    (`/api/routing/*`, `/api/quota/*`, `/api/usage/*`).
  * Per-message routing/usage columns on `messages` capturing executor
    and advisor `model_usage`, source, reason, matched rule.
  * `RoutingDecision`, `RoutingRule`, `SystemRoutingRule`, `QuotaSnapshot`
    frozen dataclasses (Appendix A wire shape).
* **Frontend routing surfaces** (per spec §6 + §10):
  * New-session dialog with reactive routing preview (300 ms debounce),
    advisor toggle, quota bars (yellow at 80 %, red at 95 %), and
    downgrade banner with "Use anyway" override.
  * Per-message `RoutingBadge` in the conversation pane.
  * Inspector **Routing** subsection: current decision, advisor totals,
    quota delta this session, per-message timeline with "Why this
    model?" expandable rule chain.
  * Inspector **Usage** subsection: 7-day headroom chart, by-model
    table, advisor-effectiveness widget, rules-to-review list (override
    rate > 30 % over 14 days).
  * Routing rule editor (per-tag + system-wide) with drag-reorder,
    enable/disable, duplicate, delete, and a deterministic
    test-against-message dialog (no LLM).
* **Inspector core** (per arch §1.2): five-tab inspector shell with
  Agent / Context / Instructions / Routing / Usage subsections (item
  2.5 ships the first three; 2.6 lights up Routing + Usage).
* **Paired chats + prompt endpoint + bearings CLI**:
  `POST /api/sessions/<id>/prompt` returning 202, paired-chat persistence
  per `docs/behavior/paired-chats.md`, and a `bearings` CLI with the
  `todo` subcommand.
* **Checklists, auto-driver, and sentinels**: full picking / linking /
  reordering / run-control endpoints; auto-driver agent surfaces
  per-item run state through the sidebar sentinel pip.
* **Vault + memories**: per-tag system-prompt overlays, vault search,
  memories editor, redaction toggles per `docs/behavior/vault.md`.
* **Themes**: theme provider with no-flash boot script, runtime picker
  with Midnight Glass / Default / Paper Light, theme-color meta updater.
* **Keyboard shortcuts and context menus**: keybinding registry with
  cheat-sheet, palette, and right-click action surface per
  `docs/behavior/keyboard-shortcuts.md` and `docs/behavior/context-menus.md`.
* **Migration script**: `scripts/migrate_v0_17_to_v0_18.py` copies
  v0.17.x DB to the v1 path, transforms schema, has dry-run mode, and
  is idempotent on re-run.
* **OpenAPI export**: `GET /openapi.json` (item 1.10) and the static
  copy at [`docs/openapi.json`](docs/openapi.json) — 62 paths,
  53 schemas.
* **Documentation**: `docs/architecture-v1.md`, `docs/model-routing-v1-spec.md`,
  per-subsystem behavior specs under `docs/behavior/`, augmented chat.md
  §"Inspector pane (non-routing subsections)", project `CLAUDE.md`.
* **Quality gates**: 12-tool pre-commit stack (ruff, mypy, pytest,
  vulture, radon, interrogate, codespell, pip-audit, eslint, prettier,
  svelte-check, knip, ts-prune, depcheck, lychee), playwright e2e,
  cross-system consistency lint, ≥ 80 % coverage on business logic.

### Changed

* **Repo posture**: `v1-rebuild` is an orphan branch; pre-commit
  `branch-verifier` rejects commits to any other branch on this
  worktree. Per-worktree `core.hooksPath` isolation via
  `scripts/setup-worktree.sh`.
* **Backend layout** consolidated per `docs/architecture-v1.md`:
  * `bearings.agent` collapses v0.17.x's three-file session split into a
    single session lifecycle module.
  * `bearings.web` separates DTOs (`web/models/`) from routes
    (`web/routes/`); each route group has a typed Pydantic wire model.
  * `bearings.config` exposes the spec-mandated numeric constants in a
    single constants module — no inline literals downstream.
  * `bearings.db` keeps a single routing-aware schema (no migration
    chain) and per-concern query modules.
* **Frontend layout**: `lib/components/` regrouped from v0.17.x's
  flat 60+ files into feature-scoped folders
  (`conversation/` + `sidebar/` + `inspector/` + `routing/` + `vault/`
  + `reorg/` + `menus/` + `modals/` + `feedback/` + `common/` +
  `pending/` + `checklist/` + `settings/` + `icons/`).
* **SDK**: pinned `claude-agent-sdk~=0.1.69` (compatible-release).
  Streaming protocol, advisor tool, beta headers, `model_usage` shape,
  effort levels, `fallback_model`, and subagent auto-select all updated
  to current SDK surface (see `docs/architecture-v1.md` §5 SDK currency
  audit).
* **Concurrent-run defaults** for v1 vs v0.17.x: port 8787 → **8788**;
  DB `~/.local/share/bearings/` → `~/.local/share/bearings-v1/`;
  systemd `bearings.service` → `bearings-v1.service`.

### Deferred (explicitly NOT in v0.18.0)

* Multi-user / auth — Bearings stays localhost.
* Cross-user shared rule libraries (per spec §12).
* ML routers, A/B testing, classifier preflight (per spec §12).
* Per-rule model-version pinning (per spec §12).
* `1.0.0` stability commitment — post-dogfood decision.

### Migration

Run the one-shot migration script after upgrading from v0.17.x:

```bash
uv run python scripts/migrate_v0_17_to_v0_18.py --dry-run
uv run python scripts/migrate_v0_17_to_v0_18.py
```

The script reads from `~/.local/share/bearings/sessions.db` and writes
to `~/.local/share/bearings-v1/sessions.db`. The v0.17.x install is left
untouched so the two services can run concurrently on ports 8787 / 8788
during cutover.

The migration coerces v0.17 session titles to fit v1's runtime
invariants:

* NULL or empty titles → ``"(untitled)"`` sentinel (the v1 ``Session``
  dataclass requires a non-empty title; the schema's NOT NULL alone is
  not sufficient).
* Titles longer than 500 chars are truncated with an ellipsis suffix
  so the row remains addressable through ``GET /api/sessions``.

### Cutover smoke

`scripts/cutover_smoke.py` is the v1 acceptance gate. It migrates a v0.17.x
DB into a tempdir target, boots the v1 FastAPI app + SvelteKit dist
against the migrated data, probes every API subsystem (health, metrics,
tags, sessions, vault, uploads, routing, quota, usage, diag, static
SPA), walks migrated rows back through the API to confirm round-trip
integrity, and runs the Playwright E2E suite (29 tests across 9
specs). The script emits a per-stage PASS / FAIL report and exits 0
only when every stage is green:

```bash
uv run python scripts/cutover_smoke.py             # full acceptance
uv run python scripts/cutover_smoke.py --skip-e2e  # fast iteration
uv run python scripts/cutover_smoke.py --json      # machine-readable
```

[1.0.0]: https://github.com/Beryndil/Bearings/releases/tag/v1.0.0
[0.18.0]: https://github.com/Beryndil/Bearings/tree/v1-rebuild
