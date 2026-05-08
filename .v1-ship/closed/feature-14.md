# Feature 14 closeout — Analytics v1

**Closed:** 2026-05-08T11:30:00-05:00
**Closer session:** 7cae7bcf40d0484b8040b98966999f55
**Verifier session:** e86e77beeeaa445eb26ae6420135b65b
**Executor sessions:** n/a — no STILL_OPEN findings; implementation delivered
as 7 autonomous phases (commits listed below)

## Findings register

| ID | Verdict | Status | Commit | Notes |
|---|---|---|---|---|
| (none) | Spec-only | CLOSED | a18fbdc7…3b2c2fa0 | Feature was PLANNED at audit time; all 7 phases now implemented |

Zero numbered defect findings existed in the verified JSONL (feature-14.jsonl
is empty). The verifier correctly recorded the audit verdict as "spec-only /
PLANNED" — the closer's job was to verify the implementation landed cleanly
across all 7 phases, not to resolve audit findings.

## Phase delivery register

| Phase | Description | Commit |
|---|---|---|
| 0 | `cache_creation_tokens` column in `messages` table; `MODEL_USAGE_KEY_CACHE_CREATION` constant; full pipeline update | `a18fbdc7` |
| 1 | Analytics schema: `turns`, `plug_blocks`, FTS5 `plug_blocks_fts` (with sync triggers), `session_plug_blocks`, `bucket_snapshots`, `suppressed_warnings`; `PLUG_YELLOW_THRESHOLD_TOKENS=500`, `PLUG_RED_THRESHOLD_TOKENS=1500`; `db/analytics.py` query layer; Pydantic wire models | `b84ea3fb` |
| 2 | `agent/analytics_capture.py`: normalize + hash + token-estimate + walk-up CLAUDE.md + `capture_session_plug` + `capture_turn`; wire-in to `sdk_loop._finish_turn()` and `session_bootstrap.setup()` | `d2bb1e62` |
| 3 | Extend `GET /api/usage/by_tag` and `GET /api/usage/by_model` with `cache_creation_tokens`; new `GET /api/usage/turns` endpoint; `db.analytics.list_turns()` | `9ed6b758` |
| 4 | Full `web/routes/analytics.py` — all 13 endpoints from spec §9 (2 logging, 6 read, 5 action); `compute_tag_attribution`, `list_redundant_plug_blocks`, `list_versions_for_block` DB helpers; router mounted in `app.py` | `98a700dc` |
| 5 | Frontend: `api/analytics.ts` typed client; `InspectorAnalytics.svelte` (sections A, B, C); `INSPECTOR_TAB_ANALYTICS` constant; Inspector.svelte wired; 32 vitest tests; dist rebuilt | `b41ee738` |
| 6 | Promote actions: idempotency on backend (promote-to-tag-memory, promote-to-on-open); frontend modal state machine; `promoteToTagMemory`, `promoteToOnOpen`, `draftNewSession`, `createSessionFromDraft` API functions; 8 new promote tests | `3b2c2fa0` |

## Behavior-spec coverage

Primary spec: `BEARINGS_ANALYTICS_v1.md`

End-to-end behaviors verified:

1. **Turn token capture** — every SDK turn writes to `turns` table via
   `sdk_loop.py:350-357` calling `capture_turn()` after `persist_fn`.
   Integration confirmed: `sdk_loop.py` imports `capture_turn` at line 64;
   call site at line 357. Spec §5 / Phase 2.

2. **Plug block hashing and session association** — on session creation,
   `session_bootstrap.py:221-227` calls `assemble_plug_blocks()` (walk-up
   CLAUDE.md + tag memories + session_instructions) then
   `capture_session_plug()` which upserts into `plug_blocks` and inserts
   into `session_plug_blocks`. INSERT OR IGNORE ensures idempotency on
   supervisor respawn. Spec §5.1 / Phase 2.

3. **Analytics tab rendering** — `Inspector.svelte:202-203` renders
   `<InspectorAnalytics>` panel behind `activeTabId === INSPECTOR_TAB_ANALYTICS`
   guard. All three sections (A: bucket bars + tag attribution, B: redundancy
   list with promote actions, C: active-session plug breakdown) present.
   Frontend constants `PLUG_YELLOW_THRESHOLD_TOKENS=500`,
   `PLUG_RED_THRESHOLD_TOKENS=1500` match backend constants identically.
   Spec §10 / Phases 5–6.

## Defect-typology cross-check

| Class | Instances in feature 14 | Resolved by |
|---|---|---|
| Spec-only | 1 (correctly framed as PLANNED at audit time) | All 7 phases `a18fbdc7`–`3b2c2fa0` |
| All other classes | 0 | n/a |

No validator drift, no constants drift, no module-unwired, no behavior-partial
issues found. The implementation passed the spec against all 11 typology classes.

## Implementation decisions (from V1_FEATURE_AUDIT.md §14)

These design decisions from the audit body were carried through into implementation:

- `turns` table deferred; `messages` table used for attribution (Phase 0 adds
  `cache_creation_tokens`). **Implementation note:** Phase 1 restored `turns`
  as a parallel table per spec §4.1 — both `messages` and `turns` exist, with
  `turns` being the analytics-specific per-turn log.
- `bucket_snapshots` table added (spec §4.1) alongside existing `quota_snapshots`
  — two tables serve different purposes (quota guard vs analytics time-series).
- FTS5 `plug_blocks_fts` created fresh per spec §4.2 with `content='plug_blocks'`
  linkage and three AFTER INSERT/UPDATE/DELETE sync triggers.
- Token counting uses `len(content)//4` local estimate (not Anthropic API) to
  avoid burning bucket on accounting.
- `meta:plug-draft` maps to `routing_source = plug_draft` on the `messages` row.
- Plug capture scope: `claude_md`, `tag_memory`, `session_instructions`,
  `system_baseline` only. MCP/skill descriptions deferred to v1.x.

## Outstanding concerns

None. All P0 and P1 spec sections implemented. The following remain as
explicitly deferred v1.x items (per spec §13 and audit open questions):

- Burn rate comparison (current 30-min vs 7-day median) — deferred to v1.x.
- Per-tag custom yellow/red thresholds — deferred to v1.x.
- MCP tool description and skill description block capture — deferred to v1.x
  pending SDK plug assembly visibility investigation.
- `mcp_tools`/`skill_desc` auto-suppression in redundancy view — deferred
  pending observation in production.

## Sign-off

Feature 14 is **CLOSED**. All 7 Analytics v1 phases implemented and verified
against `BEARINGS_ANALYTICS_v1.md`. Zero P0/P1 findings outstanding. Deferred
items are v1.x scope per spec §13 and the original audit decisions.

This is the 14th and final feature closer. All 14/14 features are now CLOSED.
