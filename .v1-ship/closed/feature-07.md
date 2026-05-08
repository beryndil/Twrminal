# Feature 7 closeout — Vault & memories

**Closed:** 2026-05-08T10:30:00Z
**Closer session:** `196d05814b1b485b9c69e9e0ef55f39a`
**Verifier session:** `9e6f171e143542ecb8f45fbdb4864d69`
**Executor sessions:**
- feature-7-002 → commit `00d260b9` (memories→system prompt wiring)
- feature-7-003 → commit `e5726383` (vault _cfg() 503 fail-fast)
- feature-7-004 → commit `ccaf25aa` (vault drag-paste + memories chip-filter tests)

## Findings register

| ID | Severity | Verdict | Status | Commit | Notes |
|---|---|---|---|---|---|
| feature-7-001 | P0 | FIXED_SINCE_AUDIT | CLOSED | `e814f7aa` | Verifier confirmed `rows.length === 0` guard was correct at HEAD; `filteredRows.length === 0` form described by audit never existed in the codebase. Regression test added under feature-7-004. |
| feature-7-002 | P0 | STILL_OPEN → DONE | CLOSED | `00d260b9` | `resolve_tag_memory_blocks()` added to `agent/tags.py`; wired into `session_bootstrap.py`; `prompt_assembler.py` layer kinds split (tag_claude_md vs tag_memory). 11 new tests across 2 test files. Doc correction also applied this closeout (see §Outstanding concerns). |
| feature-7-003 | P1 | STILL_OPEN → DONE | CLOSED | `e5726383` | `_cfg()` in `routes/vault.py` now raises `HTTPException(503)` matching `_db()`. `create_app()` always sets `app.state.vault_cfg` on startup; production path unaffected. New 503 test added. |
| feature-7-004 | P1 | STILL_OPEN → DONE | CLOSED | `ccaf25aa` | Two remaining test gaps closed: vault drag-paste DragEvent test (`VaultPanel.test.ts`) and memories chip-filter zero-rows spec guard (`MemoriesIndex.test.ts`). No code changes — tests only. |
| feature-7-005 | P2 | STILL_OPEN → DEFERRED | v1.1 backlog | — | Per-doc line cap silent truncation. See §v1.1 deferred items below. |

## Behavior-spec coverage

Primary specs: `docs/behavior/vault.md`, `docs/behavior/memories.md`

End-to-end behaviors verified (code-read, no execution):

1. **Vault _cfg() fail-fast** — typing `GET /api/vault` or `GET /api/vault/search` when `app.state.vault_cfg` is missing returns 503 with `"vault_cfg not configured on app.state"`. Code path: `routes/vault.py:_cfg()` raises `HTTPException(503)` when `getattr(request.app.state, "vault_cfg", None) is None`. Test: `tests/test_vault_api.py::test_get_vault_503_when_vault_cfg_not_wired`. Satisfies spec fail-fast convention. Global cap still sets `SearchResult.capped` flag and surfaces "showing first N" to the user via VaultPanel; per-doc cap is silent (P2, deferred).

2. **Tag memories injected per-turn** — enabled memory bodies for every tag on the session flow into the system prompt on every worker dispatch. Code path: `agent/tags.py:resolve_tag_memory_blocks()` → `session_bootstrap.py:compose_session_options()` appends `extra_memory_blocks` to `extra_system_prompt_parts` after CLAUDE.md blocks. Re-read semantics hold: editing a memory and sending the next prompt picks up the new body without runner respawn. Tests: `tests/test_agent_tags_memory.py` (7 tests: empty, enabled/disabled filtering, multi-tag precedence, per-turn re-read, isolation) + `tests/test_prompt_assembler_api.py` (db_memories_appear_as_tag_memory_layers, disabled_memory_excluded, both_claude_md_and_db_memory_produces_both_layer_kinds, deleted_memory_absent_on_next_assemble_call). Inspector distinguishes `tag_claude_md` (filesystem) from `tag_memory` (DB, source_path=null).

3. **Memories empty-state guard + chip-filter regression lock** — the "No memories yet" empty state renders only when `GET /api/memories` returns `[]`; selecting a chip that filters all rows to zero does NOT show the empty state. Code path: `MemoriesIndex.svelte:119` — guard is `{:else if rows.length === 0}` (unfiltered backing array), not `filteredRows.length`. Test: `MemoriesIndex.test.ts:describe('chip-filter zero-rows spec guard (finding-7-001 regression)')` — loads two rows for two distinct tags, activates each chip, asserts `memories-index-empty` absent from DOM in both cases.

## Defect-typology cross-check

| Class | Instances in feature 7 | Resolved by |
|---|---|---|
| Module exists, unwired | 1 — feature-7-002: tag_memories CRUD wrote rows the agent loop never read | `00d260b9` |
| Silent failure | 2 — feature-7-003: _cfg() silent VaultCfg() fallback; feature-7-005: per-doc line cap silent | `e5726383` (003 resolved); v1.1 deferred (005) |
| Behavior partial | 1 — feature-7-001: empty-state guard checked filteredRows per audit (FIXED_SINCE_AUDIT — guard was correct; audit misread). Covered by regression test @ `ccaf25aa` | `e814f7aa` + `ccaf25aa` |
| Test coverage gap | 1 — feature-7-004: vault drag-paste DragEvent path, memories chip-filter zero-rows invariant | `ccaf25aa` |
| Validator drift POST↔PATCH | 0 | — |
| Constants drift backend↔frontend | 0 | — |

## Doc correction applied this closeout

`docs/behavior/memories.md` carried a stale "System-prompt injection status (v1.0)" section (landed at `34260dba`, Fri May 8 03:46) that described injection as absent — written against pre-fix code after `00d260b9` (Thu May 7 23:39) had already wired it. The section was replaced with accurate text describing `resolve_tag_memory_blocks`, the per-turn re-read semantics, and the inspector layer split. Committed alongside this closeout report.

## v1.1 deferred items

### feature-7-005 — Vault per-doc line cap is silent

**User-visible impact:** When a vault search result hits the 500-line-per-document cap (the inner loop in `agent/vault.py:search_vault_entries` exits at `line_cap_per_doc`), the result is silently truncated. The client receives no signal that the document was cut short. The global result cap does set `SearchResult.capped = True` and the frontend surfaces a "showing first N — narrow your query" banner, but a user whose search matches lines beyond position 500 in a single large document sees a partial result with no indication that content was omitted. This is inconsistent with the `docs/behavior/vault.md §Search-cap reached` contract ("the user is asked to narrow the query rather than the UI silently truncating with no signal").

**Suggested v1.1 fix shape:** Add a `per_doc_capped: bool` field to `SearchResult` and `SearchResultOut` (keeping existing `capped` as the global-cap signal for back-compat). In `search_vault_entries`, set `per_doc_capped = True` when the inner loop exits via the `line_cap_per_doc` guard on at least one document. Expose the flag through the route. In `VaultPanel`, show a per-document truncation indicator (e.g. a small badge on the result row: "doc truncated — showing first 500 lines"). Add a unit test for `search_vault_entries` with a document whose body exceeds `line_cap_per_doc` and whose matching line is beyond the cap.

## Outstanding concerns

None beyond the v1.1 deferred item above.

## Sign-off

Feature 7 (Vault & memories) is **CLOSED**. All P0 and P1 findings resolved. One P2 finding (feature-7-005) explicitly deferred to the v1.1 backlog per ship policy.
