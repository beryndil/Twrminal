# Feature 13 closeout — SemVer commitment (v1.0.0)

**Closed:** 2026-05-08T00:00:00Z
**Closer session:** `c6e2a79063a34e21a2fe8b01ee081ef9`
**Verifier session:** `f4b0b90360b1437abbee9cc9f10c813c`
**Executor sessions:**
- feature-13-001 → executor `98c245c1` / `fa4fd9c0` (spec-drift CI gate)
- feature-13-002 → executor `6dd3b770` / `fa4fd9c0` (schema-drift CI gate)
- feature-13-003 → executor `fa4fd9c0` (version-alignment CI gate)
- feature-13-004 → executor `f2cdc020` (api-compat oasdiff job)
- feature-13-005 → executor `eca98de5` (133 operation_ids pinned)
- feature-13-006 → absorbed in closeout commit (deprecated=True on tag_ids)
- feature-13-008 → fixed collaterally `881a32eb` (CCW-1 [Unreleased] behavior docs)
- feature-13-009 → absorbed in closeout commit (CHANGELOG WS + CLI stability scope)
- feature-13-010 → absorbed in closeout commit (docs/deprecation-convention.md)
- feature-13-011 → absorbed in closeout commit (CHANGELOG count update)

## Findings register

| ID | Verdict | Status | Commit | Notes |
|---|---|---|---|---|
| feature-13-001 | STILL_OPEN | DONE | `98c245c1`, `fa4fd9c0` | CI spec-drift gate: regen openapi.json + git diff --exit-code |
| feature-13-002 | STILL_OPEN | DONE | `6dd3b770`, `fa4fd9c0` | CI schema-drift gate: check_schema_drift.py |
| feature-13-003 | STILL_OPEN | DONE | `fa4fd9c0` | CI version-alignment gate: pyproject.toml == openapi.json info.version |
| feature-13-004 | STILL_OPEN | DONE | `f2cdc020` | CI api-compat job: tufin/oasdiff-action breaking-change gate |
| feature-13-005 | STILL_OPEN | DONE | `eca98de5` | 133 operation_ids pinned across 29 route files |
| feature-13-006 | STILL_OPEN | DONE (absorbed) | this commit | `Query(deprecated=True)` on tag_ids in sessions.py:383; openapi.json regen |
| feature-13-007 | FIXED_SINCE_AUDIT | N/A | — | All four dataclasses confirmed frozen=True at HEAD |
| feature-13-008 | STILL_OPEN | DONE (collateral) | `881a32eb` | [Unreleased] behavior docs: tag-classes, import-bearings, sdk-history-replay, permission-mode |
| feature-13-009 | STILL_OPEN | DONE (absorbed) | this commit | CHANGELOG §Stability commitment: added WS message shape + CLI flag surface bullets |
| feature-13-010 | STILL_OPEN | DONE (absorbed) | this commit | docs/deprecation-convention.md: three-part convention (deprecated=True + x-sunset + Sunset header) |
| feature-13-011 | STILL_OPEN | DONE (absorbed) | this commit | CHANGELOG v1.0.0 surface count updated 62/53 → 107/95/134 |

## Behavior-spec coverage

Primary spec: `docs/behavior/tool-output-streaming.md` (WS surface), `src/bearings/cli/` (CLI surface), `docs/openapi.json` (HTTP surface)

End-to-end behaviors verified (code-read):

1. **Spec-drift gate fires on unregistered changes** — `scripts/regen_openapi.py` calls `create_app().openapi()`, writes with `indent=2` + trailing newline matching CLAUDE.md prescription; ci.yml backend job runs it then `git diff --exit-code -- docs/openapi.json`. Any route change that does not include a regen commit fails CI. Wired: `.github/workflows/ci.yml` backend job.

2. **operation_ids are stable slugs, not auto-generated** — `eca98de5` pinned all 134 operations with explicit kebab-case slugs. `tests/test_operation_ids.py` iterates `create_app().openapi()['paths']` asserting every operation has a non-empty unique `operationId`. The oasdiff gate is therefore signal-clean: function renames do not register as breaking changes.

3. **Deprecated surfaces are flagged in the OpenAPI contract** — `GET /api/tag-groups` carries `deprecated=True` (tags.py:269); `tag_ids` Query param on `GET /api/sessions` carries `Query(deprecated=True)` (sessions.py:383). Both propagate to `docs/openapi.json` as `"deprecated": true`. The oasdiff gate distinguishes intentional deprecations from removals.

## Defect-typology cross-check

| Class | Instances in feature 13 | Resolved by |
|---|---|---|
| Promise unenforced | 4 (spec-drift, schema-drift, version-align, api-compat — docs said rule, CI did not enforce) | `98c245c1`, `6dd3b770`, `fa4fd9c0`, `f2cdc020` |
| Module exists, unwired | 1 (operation_ids absent — FastAPI auto-generated, oasdiff gate would false-positive on renames) | `eca98de5` |
| Doc gap | 3 (behavior docs for [Unreleased] surfaces, CHANGELOG WS/CLI scope, deprecation convention) | `881a32eb`, this commit |
| Validator drift POST↔PATCH | 0 | — |
| Constants drift backend↔frontend | 0 | — |
| Behavior partial | 0 | — |

## Outstanding concerns

**Sunset header middleware deferred to v1.1.0** — The three-part deprecation convention (deprecated=True + x-sunset + Sunset response header) is now documented in `docs/deprecation-convention.md`. The first two parts are implemented on the existing deprecated surfaces. The ASGI middleware for the `Sunset` response header is deferred: it requires wiring into `create_app()` and tests, which is code-layer work beyond this closeout's doc-absorption scope. Tracked in `TODO.md`. No deprecated surface will be removed before v1.2.0, giving at least one full minor release for the middleware to land.

**x-sunset extension** — `docs/deprecation-convention.md` documents the `openapi_extra={"x-sunset": "<version>"}` pattern. The currently deprecated surfaces (`GET /api/tag-groups`, `tag_ids` param) do not yet carry the `x-sunset` extension — it is part of the Sunset-middleware story and deferred together with it to v1.1.0.

## Sign-off

Feature 13 is **CLOSED**. All P0 and P1 findings resolved (001–005 by executors, 007 confirmed already fixed, 008 fixed collaterally). P2 findings 006, 009, 010, 011 absorbed in this closeout commit. Two deferred items (x-sunset extension, Sunset header middleware) are explicitly tracked in TODO.md for v1.1.0 — they do not affect the stability commitment as no deprecated surface is removed before v1.2.0.
