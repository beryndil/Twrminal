# Feature 6 closeout — Checklists, paired chats, auto-driver

**Closed:** 2026-05-08T00:00:00Z
**Closer session:** 7bd7658d1dd84456b6471628bf04b1e2
**Verifier session:** b0f4e9f9ba554a09821f3f3183ccbb3c
**Executor sessions:**
- feature-6-001 + feature-6-005: commit `ea1d1f1d`
- feature-6-002: commit `257147e1`
- feature-6-008 (collateral): commit `e2b03777`

## Findings register

| ID | Verdict | Status | Commit | Notes |
|---|---|---|---|---|
| feature-6-001 | STILL_OPEN | DONE | ea1d1f1d | blocking-followup recursion — `_apply_followups` now calls `await self._drive_item(child, followup_depth=depth+1)` before resuming parent; max_followup_depth guard threaded through |
| feature-6-002 | STILL_OPEN | DONE | 257147e1 | check-item cascade — route calls `sessions_db.close` + broadcaster on paired chat, then `cascade_parent_checks` for parent chain, then closes checklist session when all root items checked; uncheck does not reopen |
| feature-6-003 | FIXED_SINCE_AUDIT | N/A | 0e92965d | ON DELETE SET NULL FK + PRAGMA foreign_keys = ON already in place |
| feature-6-004 | FIXED_SINCE_AUDIT | N/A | de9f0137 | ＋ SPAWN pill wired in MessageTurn.svelte |
| feature-6-005 | STILL_OPEN | DONE | ea1d1f1d | visit_existing closed-chat skip — `_is_closed_chat_skip` calls `sessions_db.is_closed`; absent/closed → `_record_skip` + continue |
| feature-6-006 | STILL_OPEN | P2 DEFERRED to v1.1 | — | whitespace-only label slips through `if not self.label:` truthy check |
| feature-6-007 | STILL_OPEN | P2 DEFERRED to v1.1 | — | leg session vanished mid-run leaves run row stuck in `running` |
| feature-6-008 | STILL_OPEN | DONE (collateral) | e2b03777 | teardown_leg now calls `close_session_callback` wired from `app.py` to `sessions_db.close` + `broadcaster.publish_upsert`; predecessor leg chat row closes and broadcasts before successor spawns |
| feature-6-009 | minor | ABSORBED | this commit | TODO.md dead entries struck — PairedChatIndicator mounted since 33b3a55c; ChecklistChat re-added in 404c1818 |

## Behavior-spec coverage

Primary spec: `docs/behavior/checklists.md`

End-to-end behaviors verified:

1. **Blocking followup recurse → check cascade** — a blocking-followup child is driven to terminal via recursive `_drive_item(child, followup_depth=depth+1)` (`auto_driver.py:_apply_followups`). On the child's `item_done` sentinel the child's `mark_checked` fires; the parent's `checked_at` is set if it is now the last unchecked sibling (`cascade_parent_checks`); the checklist session closes and broadcasts when all root items are checked (`routes/checklists.py:check_item`). Code path: `auto_driver._drive_item` → `_apply_followups` → recursive `_drive_item` → `checklists_db.mark_checked` → `cascade_parent_checks` → `sessions_db.close` → `broadcaster.publish_upsert`. Tests: `tests/test_auto_driver_integration.py` (blocking followup), `tests/test_routes_checklists.py` (cascade close).

2. **visit_existing with a closed paired chat → skip** — when `visit_existing=True` and `item.chat_session_id` is set, `_is_closed_chat_skip` calls `sessions_db.is_closed`; if closed or absent the item is routed through `_record_skip` with reason `"visit_existing: paired chat is closed"`, `items_skipped` ticks, and the leg loop is not entered. Code path: `auto_driver._drive_item:_is_closed_chat_skip` → `sessions_db.is_closed` → `_record_skip`. Test: `tests/test_auto_driver_integration.py`.

3. **Leg cutover → predecessor chat closes + broadcasts** — on handoff (and any terminal that ends a leg), `_drive_item` calls `runtime.teardown_leg(leg_session_id=...)`. `AutoDriverRuntime.teardown_leg` invokes `self._opts.close_session_callback(leg_session_id)`. The callback is wired in `app.py:_build_auto_driver_runtime` as `_close_leg_session` which calls `sessions_db.close` + `bc.publish_upsert` on the predecessor chat row. The successor leg's `_leg_session_factory` broadcasts the new row immediately after. Code path: `auto_driver._drive_item` → `runtime.teardown_leg` → `_close_leg_session` (`app.py`) → `sessions_db.close` + `broadcaster.publish_upsert`. Test: `tests/test_auto_driver_integration.py` (CCW-3 broadcaster regression tests also in `48066b85`).

## Defect-typology cross-check

| Class | Instances in feature 6 | Resolved by |
|---|---|---|
| Backend-only (frontend unwired) | 1 — spawn-from-reply UI | de9f0137 (FIXED_SINCE_AUDIT) |
| Behavior partial | 3 — followup recursion, cascade-close, leg-cutover broadcast | ea1d1f1d, 257147e1, e2b03777 |
| Behavior partial (edge case) | 1 — visit_existing + closed-chat | ea1d1f1d |
| Stale docs | 1 — TODO.md dead entries | this commit (feature-6-009 absorbed) |
| Validator drift (P2) | 1 — whitespace-only label | deferred to v1.1 |

No instances of: validator drift POST↔PATCH, constants drift backend↔frontend, module exists unwired, inert gates, promise unenforced.

## P2 deferrals

### feature-6-006 — Followup label whitespace validation

**User-visible impact:** A sentinel emitted by an agent can create a
checklist item with a label that is visually blank (whitespace-only string). The
item renders as an empty row in the checklist pane. Subsequent driver runs will
attempt to drive this blank-label item, spawning a leg whose first prompt says
"work on: `   `". No data is corrupted and the run does not crash, but the
checklist gains noise items that the user must manually delete. The same issue
applies when the user manually types whitespace and presses Enter in the Add-item
input (though most browsers trim the field on submit, it is not guaranteed).

**Suggested v1.1 fix shape:** Tighten `ChecklistItem.__post_init__` from
`if not self.label:` to `if not self.label.strip():` (matching the discipline
already used by `db/messages.py:118`). Apply the same guard at
`checklists_db.update_label` and in `auto_driver._apply_followups` (skip the
followup rather than letting the db layer raise). Add a 422 route-layer test
and a db-layer unit test for `'   '` input.

### feature-6-007 — No recovery if leg session vanishes mid-run

**User-visible impact:** If a leg chat session is deleted from the database
while a driver run is in flight (e.g. the user deletes the paired chat from the
sidebar, or a concurrent migration removes the row), the driver's `runner_factory`
raises an exception that propagates out of the `asyncio` task uncaught. The run
row is left permanently in state `running` with no status-line update. The
checklist's auto-driver control shows the run as still in progress; Start is
disabled; the user has no way to reset the run state short of direct DB surgery.
A server restart would rehydrate the `running` row and attempt to re-attach — at
which point the same crash recurs.

**Suggested v1.1 fix shape:** Add a typed `LegSessionVanished` exception raised
by the runtime when `runner_factory` cannot find the session row. Catch it in
`auto_driver.drive()`: record the current item as `failed` with
`reason="leg_session_vanished"`, finalize the run row to `finished` with outcome
`"Halted: leg session vanished"`. Update the done-callback in
`routes/checklists.py` to log and finalize on unhandled task exceptions (so even
unanticipated errors don't strand the run in `running`). Add an integration test
that deletes the session row mid-turn and asserts the run reaches `finished`.

## Outstanding concerns

- The `PairedChatIndicator` component is mounted and receives data from
  `ConversationHeader`, but the backend lookup for `(parent_title, item_label)` via
  a dedicated endpoint (`GET /api/sessions/{id}/paired-chat-info` or a `paired_chat`
  block on `SessionOut`) is not yet implemented. The component likely renders with
  empty or stub data in v1.0. This is a separate deferral tracked in TODO.md under
  "Missing arch §1.1.5 route modules" and is not a feature-6 regression.

## Sign-off

Feature 6 is **CLOSED**. All P0 and P1 findings resolved (5 DONE, 2
FIXED_SINCE_AUDIT). P2 findings feature-6-006 and feature-6-007 are explicitly
deferred to v1.1 with fix shapes documented above. feature-6-009 (minor / doc
hygiene) absorbed in this closeout commit.
