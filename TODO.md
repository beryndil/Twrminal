# Bearings v1 rebuild — deferred / orphaned work

Append the moment work is deferred or an error is passed on, per the
project CLAUDE.md "TODO.md Discipline" rule. Scheduled work belongs in
the master checklist (id `0f6e4006fb1d4340bda9983af3432064`), not here.

When a TODO is resolved, strike it from this file in the same commit
that lands the fix and cite the resolving commit hash in the removal
trailer.

## v1.1 closing-sweep (2026-05-02) — corrects v1.0's lying close

The 2026-04-29 close of the v1 master checklist
(`0f6e4006fb1d4340bda9983af3432064`) marked 29/29 items DONE without
artifact verification. The 2026-05-02 audit
(`bearings__get_tool_output toolu_01LjpFH7TnMzpGR81Z325Ky3`) found
~25% of arch §1.1.5 unbuilt — including the entire session-create
flow (button → broken route, no `POST /api/sessions`, NewSessionForm
orphaned). The v1.1 closing-sweep
(`~/.claude/plans/belated-closing-sweep.md`) closes the gap.

What v1.1 ships:

* **Phase 0.** ``POST /api/sessions`` + ``/sessions/new`` route +
  NewSessionForm submit wiring.
* **Phase 1.** RoutingRuleEditor mounted in ``/settings`` (system) +
  ``/tags`` (per-tag); ``/tags`` and ``/analytics`` stub pages
  replaced with real management surfaces; ChecklistChat orphan deleted.
* **Phase 2.** ``PATCH /api/sessions/{id}/model`` (DB-only swap; live
  runner forward deferred per "PATCH model" entry below) +
  ``POST /api/sessions/{id}/regenerate``.

What v1.1 defers (logged below):

* PairedChatIndicator wiring.
* PATCH model live runner forward.
* The 12 spec'd route modules from arch §1.1.5 — all absent in v1.0
  AND with zero v1 frontend consumers; deferred per the plan's
  "KEEP only modules with a v1 frontend consumer" rule.
* `bearings serve` CLI (entry below predates this sweep).
* `/api/usage/headroom` rename (entry below predates this sweep).
* Theme server-sync (entry below predates this sweep).

## Resolved by item 3.4 (final ledger sweep)

The ledger entries below were swept on the cutover-smoke commit (item
3.4, master id `0f6e4006fb1d4340bda9983af3432064` final entry).

* **Item 2.5 — chat.md augmentation for non-routing inspector
  subsections.** Resolved by item 3.3 documentation pass (commit
  `8e9bcd7`); chat.md §"Inspector pane (non-routing subsections)"
  describes Agent / Context / Instructions tabs.
* **Item 2.1 — SvelteKit scaffolding ledger (themes / keyboard /
  context-menu / api / stores / components).** Every directory the
  scaffold reserved was populated by items 2.2 – 2.10 in the Phase 2
  build order; no scaffold dirs remain empty.
* **Item 2.1 — inline-styling decision logged for 2.9 review.**
  Resolved by item 2.9 (commit `5e936e4`): the grid geometry stays
  scoped inline in `+layout.svelte`. The theme picker's density
  surface does not resize columns, so the CSS-variable hoist was not
  warranted. Documented here so a future component author defaults to
  the same choice if they sprout a similar inline style.
* **Item 2.1 — `{@html}` sanitization layer.** Resolved by item 2.3
  (commit `33b3a55`): `frontend/src/lib/sanitize.ts` wraps
  `isomorphic-dompurify` with the Bearings policy; `MessageTurn.svelte`
  routes every conversation `{@html}` through `sanitizeHtml()` before
  insertion. `linkifyToHtml()` output is also re-sanitized at the
  bubble seam for defense in depth.

## Item 3.4 — fix landed during the cutover smoke

* **Migration title-coercion.** v0.17 admitted NULL titles, empty-
  string titles, and titles longer than v1's 500-char dataclass
  invariant. The cutover smoke surfaced a 500 on `GET /api/sessions`
  the first time it ran against the live `~/.local/share/bearings/db.sqlite`
  (one outlier title was 1504 chars). The migration script now coerces
  NULL / empty titles to a `(untitled)` sentinel and truncates over-
  cap titles with an ellipsis suffix. Tests
  `tests/test_migrate_v0_17_to_v0_18.py::test_null_title_backfills_to_sentinel`,
  `::test_empty_title_backfills_to_sentinel`, and
  `::test_long_title_truncated` cover the three branches.

## Remaining deferrals (post-v1 scope)

### Theme picker silently flips to OS scheme on first paint — 2026-05-02

`frontend/src/lib/themes/persistence.ts:resolveBootTheme()` returns
`loadStoredTheme() ?? resolveOsFallbackTheme()`, and
`resolveOsFallbackTheme()` returns `THEME_PAPER_LIGHT` when
`(prefers-color-scheme: light)` matches. `index.html` paints
`data-theme="evergreen"` on first frame, then `ThemeProvider`'s
`onMount` re-applies `themeStore.theme` and the OS fallback overrides
the static-HTML choice. Net effect for a user on a light-scheme OS who
hasn't explicitly clicked the picker: the page boots evergreen,
flickers, and lands on paper-light without telling them. Dave hit this
during the `/sessions/new` contrast-bug investigation 2026-05-02.

**Action**: either (a) drop the OS fallback so the static-HTML default
(`evergreen`) is the sole "no persisted choice" path, or (b) make the
picker write the OS-fallback resolution into localStorage on first
boot so the choice surfaces in the UI. Probably (b) — keeps OS-aware
defaulting, removes the silent flip.

### Daily-probe `/api/usage/headroom` endpoint swap — 2026-05-01

Master item B.1 (daily probe script) names `/api/usage/headroom` in
its done-when criteria. That endpoint does not exist in v1's route
surface (verified against the live `/openapi.json` — only
`/api/usage/by_model`, `/api/usage/by_tag`, `/api/usage/override_rates`
are present). The probe instead hits `/api/quota/current` +
`/api/quota/history` to cover the headroom-conceptual surface (the
inspector's 7-day headroom chart already reads from those).

**Action when a literal `headroom` endpoint lands** (if ever — the
data surface is fully covered by `quota/*` today, so this may be a
permanent rename rather than a missing route): swap the
`quota_current` / `quota_history` rows in `scripts/daily_probe.py`
`PROBES` for one `headroom` row pointing at the new path, drop this
TODO entry, cite the resolving commit.



### Stopgap launcher → `bearings serve` CLI (deferred) — 2026-05-01

`~/.local/share/bearings-v1/launch.py` still owns boot-time wiring
(Settings → create_app → aiosqlite startup hook → uvicorn). The
systemd unit `config/bearings-v1.service` calls it directly via
the project venv. Documented as a stopgap in the launcher's own
docstring; landed in production on the dogfood cutover (2026-05-01)
because the planned `bearings serve` subcommand hadn't shipped.

**Action when the CLI lands**: swap the unit's ExecStart from
`/.venv/bin/python /.local/share/bearings-v1/launch.py` back to
`/usr/bin/uv run bearings serve --host 127.0.0.1 --port 8788`,
delete launch.py, drop this entry. The CLI must own the same
startup-hook side effects (DB connection on app.state.db_connection)
or the swap regresses cold-start.

### Item 2.9 — theme server-sync layer (deferred)

`docs/behavior/themes.md` §"Persistence boundary" prescribes
**per-account, server-synced** theme persistence with a "couldn't save
your theme" toast when the preferences PATCH fails. v1 ships
**localStorage-only** persistence: the runtime store reads / writes
``localStorage["bearings-theme-v1"]`` and listens to the browser-native
``storage`` event for cross-tab parity. Decision rationale:

- Bearings v1 is a single-user localhost app — "per account" degenerates
  to "the only account on this device", which is what localStorage
  already keys on.
- The arch §1.1.5 routes table lists ``web/routes/preferences.py``, but
  no preferences route, Pydantic models, or DB table exist yet. Adding
  schema + route + tests would expand this frontend item into a backend
  concern that a separate item should own (alongside other per-user
  preferences like the display timezone the doc mentions).
- The store interface is forward-compatible: a future item adds
  ``persistThemeToServer(theme)`` behind the same
  :func:`saveTheme` / :func:`loadTheme` shape used by the localStorage
  layer today, then re-points the toast copy at the network failure.

**Action when the preferences route lands** (post-v1 work item to be
scheduled separately): extend
``frontend/src/lib/themes/persistence.ts`` to call the API client,
keeping localStorage as the synchronous boot-time read so the no-flash
guarantee holds.

### Closing-sweep gap log — 2026-05-02

The 2026-05-02 audit (`bearings__get_tool_output`
`toolu_01LjpFH7TnMzpGR81Z325Ky3`) found ~25% of arch §1.1.5 unbuilt
despite the v1 master checklist
(`0f6e4006fb1d4340bda9983af3432064`) marking 29/29 DONE. The
closing-sweep plan (`~/.claude/plans/belated-closing-sweep.md`) is
the source of truth for the work; the entries below are deferrals
that arose during execution.

#### PairedChatIndicator wiring (deferred)

`paired-chats.md` §"From the chat side" point 2 mandates a breadcrumb
chip on the conversation header (`<parent checklist title> › <item
label>`). The `PairedChatIndicator.svelte` component is built
(`frontend/src/lib/components/conversation/PairedChatIndicator.svelte`)
but unmounted because no backend endpoint exposes the
`(parent_title, item_label)` lookup for a chat session id.

**Action when the lookup endpoint lands**: add
`GET /api/sessions/{id}/paired-chat-info` (or extend `SessionOut` with
a `paired_chat` block) returning the parent checklist title + item
label or `null`. Mount `PairedChatIndicator` in
`frontend/src/routes/+layout.svelte`'s conversation header guarded on
the lookup result. Same data also unblocks the sidebar annotation
(`↳ <parent checklist title>` per paired-chats.md §"From the
sidebar").

#### Missing arch §1.1.5 route modules (deferred — no v1 UI consumer)

The audit flagged 12 spec'd route modules absent from
``src/bearings/web/routes/``:

* ``sessions_bulk.py`` — bulk close/reopen/delete/tag.
* ``checkpoints.py`` — chat-undo checkpoint CRUD.
* ``templates.py`` — Templates CRUD.
* ``reorg.py`` — session-reorg analyze + apply.
* ``spawn_from_reply.py`` — ``+ SPAWN`` action on a reply.
* ``reply_actions.py`` — inline reply-action execution.
* ``artifacts.py`` — artifact register + serve.
* ``commands.py`` — slash-command palette scan.
* ``preferences.py`` — per-user preferences.
* ``pending.py`` — ``.bearings/pending.toml`` ops.
* ``history.py`` — ``history.jsonl`` reader.
* ``config.py`` — ``/api/ui-config`` runtime knob exposure.

Per-commit grep over ``frontend/src/**/*.{ts,svelte}`` (excluding
test files) found **zero** consumers for any of these endpoints in
v1.1's frontend tree. Building backend modules with no frontend
caller is dead-weight code; deferring per the closing-sweep plan's
"KEEP only modules with v1 frontend consumers" decision.

The audit's claim that ``/api/checklists`` list+create is absent
turned out to be a non-issue: checklists are sessions of
``kind="checklist"``, so the unified ``/api/sessions`` list+create
landed in this sweep covers them. The audit's claim about a
session-level bulk-tag-set endpoint (``PUT /api/sessions/{id}/tags``)
is similarly unbacked — the existing per-tag attach/detach
endpoints are what the v1 frontend uses.

**Action when each module's UI consumer lands**: implement the
backend module from arch §1.1.5 in the same commit that lands the
frontend caller. The arch doc is the source of truth for the route
shape; the per-module test patterns in
``tests/test_*_api.py`` are the reference for the integration tests.

#### PATCH model: live runner forward (deferred)

The v1.1 closing-sweep ships ``PATCH /api/sessions/{id}/model`` as a
DB-only swap. Spec §7 calls for the live forward to
:meth:`AgentSession.set_model` so the swap takes effect mid-turn —
that requires routing the swap through the runner's prompt queue (or
a dedicated control queue per arch §3.2) since the route layer holds
a :class:`SessionRunner`, not the inner :class:`AgentSession`.

**Action when the live forward lands**: extend
:meth:`SessionRunner.enqueue_set_model` (or a similar dedicated queue
if mixing control + data on one queue is too messy), have the
worker loop drain it before the next prompt, then call
``await self._client.set_model(model)`` from the worker. Drop the
"DB-only" caveat from :func:`update_model`'s docstring and from the
``patch_session_model`` route's docstring.

#### ChecklistChat — deleted (no documented role)

The `ChecklistChat.svelte` component shipped as an orphan (only its
own test imported it). No `docs/behavior/*.md` describes the embedded
conversation pane it offered; the v1 paired-chat flow uses
`goto(/sessions/<id>)` for full pane swap. Removed in commit (this
sweep) along with its test and its `CHECKLIST_STRINGS.checklistChat*`
entries. Re-add only when a behavior doc justifies an inline pane
alternative to pane-swap.
