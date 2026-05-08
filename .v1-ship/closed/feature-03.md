# Feature 3 closeout — Routing engine & quota

**Closed:** 2026-05-08T12:54:47Z
**Closer session:** 1fe8c517388a46d0bc87357ec5dcce2b
**Verifier session:** 6be4502a55cb43a4ad71eeaa92b8f79f
**Executor sessions:** none — all P0/P1 were FIXED_SINCE_AUDIT or SUPERSEDED; minors
absorbed (3-005, 3-007) directly by this closer session; remaining minors and P2
explicitly deferred to v1.1.

## Findings register

| ID | Verdict | Status | Commit | Notes |
|---|---|---|---|---|
| feature-3-001 | STILL_OPEN | **DEFERRED v1.1** | — | evaluate() quota_snapshot redundancy — refactor deferred |
| feature-3-002 | STILL_OPEN | **DEFERRED v1.1** | — | P2: OverrideAggregator Pass 2 origin CTE missing window filter — deferred |
| feature-3-003 | FIXED_SINCE_AUDIT | DONE | bda4c513 | _db/_quota_poller extracted to routes/_deps.py |
| feature-3-004 | STILL_OPEN | **DEFERRED v1.1** | — | list_for_tags N+1 — deferred |
| feature-3-005 | STILL_OPEN | **ABSORBED** | this commit | IntegrityError narrowed: FK→404, UNIQUE/CHECK→409 |
| feature-3-006 | STILL_OPEN | **DEFERRED v1.1** | — | phantom RoutingRule validation objects — deferred |
| feature-3-007 | STILL_OPEN | **ABSORBED** | this commit | `or 0.0` → explicit `if x is not None else 0.0` |
| feature-3-008 | SUPERSEDED | DONE | 0036f7c1 | advisor_disabled_reason absent from App A; spec corrected by CCW-5 |
| feature-3-009 | SUPERSEDED | DONE | 0036f7c1 | System-rule reorder spec gap; endpoint added to spec §9 by CCW-5 |
| feature-3-001-extra | STILL_OPEN | **DEFERRED v1.1** | — | PATCH /api/routing/system/reorder — path (c): spec aspirational, frontend uses N-PATCH workaround |

## 3-001-extra assessment (per assignment)

The spec §9 (post-CCW-5) lists `PATCH /api/routing/system/reorder` with note
"Implementation lands in feature 3 cleanup (doc-only here)." The endpoint is
absent from code. However:

- `frontend/src/lib/api/routingRules.ts:23-26` explicitly documents the
  workaround: "System rules have no documented reorder endpoint; the editor
  re-stamps priorities by issuing per-rule PATCHes (`reorderSystemRules`
  below)."
- The frontend is fully functional without the endpoint.
- No user-facing breakage; the spec note was aspirational.

**Path (c) applies** — endpoint missing, not used by frontend. Deferred to v1.1
with spec annotation updated (docs/model-routing-v1-spec.md line 431 now reads
"DEFERRED to v1.1: feature 3 cleanup did not implement; frontend uses N-PATCH
workaround"). This is NOT a ship blocker.

## Behavior-spec coverage

Primary spec: `docs/model-routing-v1-spec.md` (routing engine, quota guard,
override aggregator)

End-to-end behaviors verified (read-based, per runbook §2):

1. **Quota guard threshold path** — `src/bearings/agent/quota.py:apply_quota_guard`
   checks `overall_used_pct` and `sonnet_used_pct` thresholds (L161-216); both
   production callers (`web/routes/routing.py` preview and
   `agent/session_assembly.py`) pass the snapshot to `apply_quota_guard` after
   calling `evaluate()`. The absorption of 3-007 confirms `quota_state_dict()`
   correctly handles `None` vs `0.0` without conflation. Tests:
   `tests/test_quota_guard.py` (35 pass).

2. **Tag-rule FK error discrimination** — `web/routes/routing.py:create_tag_rule`
   now maps FK IntegrityError (tag absent) to 404 and UNIQUE/CHECK IntegrityError
   to 409, closing the misclassification window identified in 3-005. Test:
   `test_create_tag_rule_404_on_missing_tag` in `tests/test_routing_api.py` (POST
   to tag_id=9999 → 404 verified).

3. **Dependency deduplication** — `src/bearings/web/routes/_deps.py` (bda4c513)
   is the single source for `_db()` and `_quota_poller()`; all three route modules
   (`routing.py:52`, `quota.py:26`, `usage.py:33`) import from it. No duplicate
   definitions remain (verified by verifier session 6be4502a).

## Defect-typology cross-check

| Class | Instances in feature 3 | Resolved by |
|---|---|---|
| Module exists, unwired | 1 (3-003: _deps.py) | bda4c513 (FIXED_SINCE_AUDIT) |
| Behavior partial | 1 (3-002: P2 override aggregator window asymmetry) | DEFERRED v1.1 |
| Redundant parameter | 1 (3-001: evaluate quota_snapshot) | DEFERRED v1.1 |
| Catch-all error mapping | 1 (3-005: IntegrityError → FK vs UNIQUE) | ABSORBED this commit |
| Code clarity / intent | 1 (3-007: `or 0.0` vs `is not None`) | ABSORBED this commit |
| Phantom object | 1 (3-006: validation phantom RoutingRule) | DEFERRED v1.1 |
| N+1 query | 1 (3-004: list_for_tags) | DEFERRED v1.1 |
| Spec/code gap | 2 (3-008, 3-009) | SUPERSEDED by CCW-5 (0036f7c1) |
| Spec aspirational gap | 1 (3-001-extra: system/reorder endpoint) | DEFERRED v1.1 (path c) |

## Outstanding concerns

### P2 deferred — feature-3-002

`OverrideAggregator.compute()` Pass 2 origin CTE lacks the `AND
CAST(strftime('%s', created_at) AS INTEGER) >= ?` window filter that Pass 1
carries. Today this is latent: override messages arrive at session creation so
the origin row is always within the window in practice. Regression risk on any
future session-lifecycle change that can insert a rule-fired message outside the
session's creation window. Fix is one line + one test. Scheduled for v1.1.

### Minor deferred — feature-3-001

`evaluate()` carries `quota_snapshot` only to populate
`RoutingDecision.quota_state_at_decision`, which `apply_quota_guard` then
unconditionally overwrites. Both production callers thread the same snapshot
through both functions redundantly. Refactor is straightforward but touches 4
files and every test that constructs a decision directly. Scheduled for v1.1.

### Minor deferred — feature-3-004

`list_for_tags()` issues one SELECT per tag id (N+1). Hot path on preview
keystroke and session creation. Fix: single `WHERE tag_id IN (?, …)` query +
Python groupby. Scheduled for v1.1.

### Minor deferred — feature-3-006

Four CRUD helpers in `db/routing.py` construct throwaway `RoutingRule` /
`SystemRoutingRule` instances purely to trigger `__post_init__` validation.
`_validate_rule_fields()` is already extracted — callers should call it directly.
Scheduled for v1.1.

### Endpoint deferred — feature-3-001-extra

`PATCH /api/routing/system/reorder` is specified in spec §9 but not implemented.
Frontend has a functioning N-PATCH workaround. Not a ship blocker. Scheduled for
v1.1 alongside `reorder_system_rules` db helper and OpenAPI export update.

## Sign-off

Feature 3 is **CLOSED**. All P0 and P1 findings resolved (FIXED_SINCE_AUDIT or
SUPERSEDED). The one P2 finding (3-002) is explicitly deferred to v1.1 with a
latency note. Five minor findings deferred to v1.1 (3-001, 3-004, 3-006,
3-001-extra); two minor findings absorbed in this session (3-005, 3-007); two
SUPERSEDED by CCW-5. No v1.0 ship blockers.
