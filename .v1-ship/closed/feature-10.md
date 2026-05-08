# Feature 10 closeout — Filesystem, uploads, shell, MCP

**Closed:** 2026-05-08T12:00:00Z
**Closer session:** deae2e1e526c443da0b098e9d2771332
**Verifier session:** f37c34ae1b984ca091c72a49c5b242b0
**Executor sessions:**
- feature-10-001 → `0545534afaef47a0ba04ef306c7585b6` (commit `4d2bc4b1`)
- feature-10-002 → `70bdbe66df5940c79ff61096329cb6ed` (commit `3f98c155`)
- feature-10-003 → `2a3b54bc761341e790f7ea4da88e5b56` (commit `71269763`)
- feature-10-004 → `5a9cc9a33d2b47568543b295413ba5a9` (commit `a132f348`)

## Findings register

| ID | Severity | Verdict | Status | Commit | Notes |
|---|---|---|---|---|---|
| feature-10-001 | P0 | STILL\_OPEN | DONE | `4d2bc4b1` | `bearings_dir/` package (5 modules: contract, io, lifecycle, onboarding, pending); `web/routes/pending.py` thinned to delegate; 75 new tests |
| feature-10-002 | P0 | STILL\_OPEN | DONE | `3f98c155` | `cli/gc.py` + `bearings gc uploads` two-direction mark-and-sweep; `build_subparser` wired into `cli/app.py`; 12 tests |
| feature-10-003 | P0 | STILL\_OPEN | DONE | `71269763` | `bash`, `dir_init`, `get_tool_output` tools added to `bearings_mcp.py`; 34 new tests; `BearingsMcpDeps.minimal()` for existing callers |
| feature-10-004 | P1 | STILL\_OPEN | DONE | `a132f348` | DB search moved to `web/routes/search.py`; `web/routes/history.py` rewritten as `history.jsonl` reader; both routers mounted in `app.py`; OpenAPI regenerated |

## Behavior-spec coverage

Primary spec: `docs/architecture-v1.md §1.1.6` (bearings_dir), `§1.1.1` (gc), `§1.1.4` (MCP), `§1.1.5` (web/routes/history.py)

End-to-end behaviors verified:

1. **`bearings__dir_init` round-trip (findings 001 + 003)** — code path: `bearings_mcp.py:make_dir_init_tool` dispatches to `bearings_dir.onboarding.dir_init_body`; `dir_init_body` uses `bearings_dir.io` for atomic TOML writes (`tempfile.NamedTemporaryFile + os.replace()`). Test: `tests/test_bearings_mcp_dir_init.py`. Wired end-to-end.

2. **`GET /api/history/jsonl` reads history.jsonl via lifecycle (findings 001 + 004)** — code path: `web/routes/history.py` router handler → `bearings_dir.lifecycle` for cap/read; `web/models/history.DirectoryHistoryEntry` shape matches what `lifecycle.note_directory_context_start` appends. Graceful-degrade on missing file confirmed in `tests/test_history_jsonl_reader.py`. Both routers mounted in `web/app.py` at lines 435–437.

3. **DB full-text search still resolves after namespace move (finding 004)** — `GET /api/history/search?q=` handled by `web/routes/search.py` (moved verbatim from old `history.py`); URL preserved. `web/app.py` includes `search_router` tagged `ROUTE_TAG_SEARCH`. `372285c2` added LIKE-metacharacter escaping on this path post-move. Test: `tests/test_search_route.py`.

## Defect-typology cross-check

| Class | Instances in feature 10 | Resolved by |
|---|---|---|
| Module fictional (whole package absent) | 2 — `bearings_dir/` package; `cli/gc.py` | `4d2bc4b1`, `3f98c155` |
| Module surface incomplete | 1 — `bearings_mcp.py` (3 of 4 advertised tools absent) | `71269763` |
| Module exists, wrong responsibility | 1 — `web/routes/history.py` occupied by DB search instead of jsonl reader | `a132f348` |

No "Validator drift POST↔PATCH", "Constants drift backend↔frontend", or "Behavior partial" instances in feature 10.

## Outstanding concerns

1. **`note_directory_context_start` call site absent.** The function is implemented in `bearings_dir/lifecycle.py:43` and tested, but it is not yet called from the session-start flow. Architecture §1.1.6 notes the wiring lives in `agent/prompt.py`, which does not exist on v1-rebuild HEAD. The acceptance criteria for finding-001 required the function to be exported and tested — not the call site — so this does not block closure. It is a deferred integration task.

   This observation is logged here so the next audit pass or a TODO.md entry can track it. It does not affect any of the four resolved findings.

## Sign-off

Feature 10 is **CLOSED**. All three P0 findings and the one P1 finding are resolved. No P2 or minor findings were raised. The `note_directory_context_start` wiring gap above is an unscheduled integration task, not a finding regression.
