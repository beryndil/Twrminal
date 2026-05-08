# Feature 1 closeout — Session lifecycle

**Closed:** 2026-05-08T04:10:00Z
**Closer session:** 8faed0b36c6b4f40a804735813056d28
**Verifier session:** 8be44de29c6f492f9e54767a9b74e2c6
**Executor sessions:**
- feature-1-001: a7b8964e7ab44f3890f2a6c6f38e0650 → 48a6e202
- feature-1-002: fixed collaterally by feature-5-001 executor → 40eee019
- feature-1-003: 75c076d682854c1b916f03b0fe6a28a2 → 0ff76625
- feature-1-004: 15e880375da346d6a9864571a8bf1b3a → 4a49df48

---

## Findings register

| ID | Verdict | Status | Commit | Notes |
|---|---|---|---|---|
| feature-1-001 | STILL_OPEN | DONE | 48a6e202 | _bulk_close now returns `(BulkResultItem, Session \| None)` pairs; Session captured inside tx before commit; route iterates `close_pairs` for `publish_upsert` — no post-commit re-fetch, race window closed |
| feature-1-002 | STILL_OPEN | FIXED_COLLATERALLY | 40eee019 | `_validate_tag_cardinality(db, new_tag_ids)` inserted in `patch_session` at `sessions.py:421`; same fix landed by feature-5-001 executor; three regression tests added |
| feature-1-003 | STILL_OPEN | DONE | 0ff76625 | `bulkExportSessions` now JSON-parses the server response, filters null slots via typed guard, returns a new `Blob`; vitest case asserts null-free output; dist bundle rebuilt in same commit |
| feature-1-004 | STILL_OPEN | DONE | 4a49df48 | `CLOSEABLE_SESSION_KINDS = frozenset({'chat'})` added to `constants.py:716`; `close_session` checks `existing_kind not in CLOSEABLE_SESSION_KINDS` before touching the row; two tests cover chat-success and checklist-rejection paths |

---

## Behavior-spec coverage

Primary spec: `docs/behavior/sessions.md`

End-to-end behaviors verified:

1. **Bulk close → multi-tab broadcast** — bulk close on N sessions commits the
   transaction, then iterates `close_pairs` (pre-captured inside the tx) to
   call `publish_upsert` for every `ok=True` entry. A concurrent delete can no
   longer silently drop the broadcast.
   Code path: `sessions_bulk.py:349-358` (BULK_OP_CLOSE branch, `close_pairs`
   iteration) + `sessions_bulk.py:155-216` (`_bulk_close`, row captured at
   line ~207 after `RELEASE SAVEPOINT`, before outer `COMMIT`).
   Test: `tests/test_sessions_bulk_api.py:157` —
   `test_bulk_close_broadcast_survives_concurrent_delete`

2. **PATCH tag cardinality enforcement (≤1 project / ≤1 severity)** — after
   the existence check, `patch_session` calls
   `await _validate_tag_cardinality(db, new_tag_ids)` before
   `tags_db.set_for_session`. POST and PATCH now share the same validation
   path through the same function.
   Code path: `sessions.py:317` (create path) + `sessions.py:421` (patch
   path, new line).
   Tests: `tests/test_sessions_api.py:494`
   `test_patch_session_two_project_tags_422`,
   `tests/test_sessions_api.py:510`
   `test_patch_session_two_severity_tags_422`,
   `tests/test_sessions_api.py:526`
   `test_patch_session_valid_mixed_tags_200`

3. **POST /close kind guard — checklist sessions rejected** — `close_session`
   calls `sessions_db.get_kind` first; any kind not in
   `CLOSEABLE_SESSION_KINDS` returns 422 with an explanatory detail string
   before `sessions_db.close` is ever called. Inconsistent
   `(kind='checklist', closed_at IS NOT NULL)` row state is now unreachable.
   Code path: `sessions.py:495-508` (kind fetch + guard),
   `constants.py:716` (`CLOSEABLE_SESSION_KINDS`).
   Test: `tests/test_sessions_api.py:559`
   `test_close_checklist_session_422`

---

## Defect-typology cross-check

| Class | Instances in feature 1 | Resolved by |
|---|---|---|
| Validator drift POST↔PATCH | 1 — `_validate_tag_cardinality` absent from `patch_session` | 40eee019 |
| Behavior partial (broadcaster correctness) | 1 — bulk-close post-commit re-fetch race | 48a6e202 |
| Behavior partial (state-machine incomplete) | 1 — kind guard missing on `close_session` | 4a49df48 |
| Frontend-only / spec gap | 1 — null-slot filtering delegated to frontend but unimplemented | 0ff76625 |

All four classes fully resolved. No DONE_WITH_CONCERNS flags from any executor.

---

## Outstanding concerns

None. All four findings resolved cleanly. No P2 deferred items.

---

## Sign-off

Feature 1 is **CLOSED**. All four P1/P2 findings resolved. No open concerns.
