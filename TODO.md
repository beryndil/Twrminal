# Bearings v1 rebuild — deferred / orphaned work

Append the moment work is deferred or an error is passed on, per the
project CLAUDE.md "TODO.md Discipline" rule. Scheduled work belongs in
the master checklist (id `0f6e4006fb1d4340bda9983af3432064`), not here.

When a TODO is resolved, strike it from this file in the same commit
that lands the fix and cite the resolving commit hash in the removal
trailer.

## Resolved by item 3.4 (final ledger sweep)

The ledger entries below were swept on the cutover-smoke commit (item
3.4, master id `0f6e4006fb1d4340bda9983af3432064` final entry). v1's
build order has no further items, so this is the closing sweep.

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
