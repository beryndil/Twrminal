# Orchestrator runbook — Bearings v1 ship-readiness loop

You dispatch and track. You never do feature work yourself. You never ask
Dave for input on feature decisions.

Driving document: `/home/beryndil/Projects/active/bearings/V1_FEATURE_AUDIT.md`
State file: `/home/beryndil/Projects/active/bearings/.v1-ship/state.json`
Bearings endpoint (your host): `http://127.0.0.1:8787`

## Mission

Drive V1_FEATURE_AUDIT.md to ship-clean: all 14 features CLOSED with
artifact evidence, all 5 cross-cutting work-streams (CCW-1..5) landed,
analytics v1 implemented per `BEARINGS_ANALYTICS_v1.md`. Definition of
done: the audit register has zero INTERIM rows and zero open ship-blockers.

## Roles

### Verifier (one per feature)
Reads V1_FEATURE_AUDIT.md feature N findings, re-verifies each against
current HEAD by reading code + tests + docs. Emits one of three statuses
per finding: `STILL_OPEN`, `FIXED_SINCE_AUDIT`, `SUPERSEDED`. Output:
`.v1-ship/verified/feature-NN.jsonl` (one line per finding) plus
`.v1-ship/verified/feature-NN.log` (verification reasoning). Never trust
the audit at face value. If a finding's described code path no longer
exists, mark it SUPERSEDED with a note. If the bug is fixed, mark
FIXED_SINCE_AUDIT with the resolving commit (best-effort `git log -S`
search).

### Executor (one per STILL_OPEN finding)
Implements the fix. Reads the verified finding, the cited spec section,
the code in question. Per the completeness principle: root fix, not
bandaid. Runs the project's gate set (`uv run ruff check`,
`uv run ruff format --check`, `uv run mypy src tests`, `uv run pytest`,
plus frontend gates if frontend touched: `npm run check`, `npm run lint`,
`npm run knip`, `npm test`). Commits and pushes. Self-verification block
precedes every callback per `~/.claude/plans/bearings-v1-rebuild.md`
§"Self-verification".

### CCW Worker (one per cross-cutting work-stream, CCW-1..5)
Same shape as an Executor but scoped to a horizontal pattern instead of a
single finding. CCW-1 = doc correction pass. CCW-2 = POST↔PATCH validator
grep. CCW-3 = broadcaster correctness. CCW-4 = utility scaffolding
(`db/_validators.py`, `web/routes/_deps.py`). CCW-5 = spec internal
consistency.

### Closer (one per feature, after all its STILL_OPEN findings are DONE)
Re-reads the feature's findings file, confirms every finding has a
resolution (DONE / FIXED_SINCE_AUDIT / SUPERSEDED). Runs a final
end-to-end behavior check against the feature's spec doc(s). Writes
`.v1-ship/closed/feature-NN.md` with the final closeout report. POSTs
`CLOSED — feature N`. Then orchestrator marks the feature CLOSED in
state.json and updates V1_FEATURE_AUDIT.md status table.

## Dispatch sequencing

### Wave 0 — sequential prerequisites
1. **CCW-4 utility scaffolding.** Build `db/_validators.py` and
   `web/routes/_deps.py`. Dependency of CCW-2 and several feature fixes.
2. **CCW-5 spec internal consistency.** Resolves
   `model-routing-v1-spec.md` self-contradictions (advisor_disabled_reason,
   missing reorder endpoint). Re-introduced drift after CCW-1 if skipped.

### Wave 1 — feature verification (parallel)
Dispatch all 14 feature Verifiers concurrently. They are read-only audits
with zero file conflicts. As each callbacks with its findings file:
- If `STILL_OPEN_count == 0`: feature is already clean → dispatch its
  Closer.
- If `STILL_OPEN_count > 0`: queue the feature's executors, dispatch the
  first.

### Wave 2 — execution (per-feature serial, cross-feature parallel)
Within a feature: executors fire serially to avoid commit conflicts on
shared files. Across features: parallel where files don't overlap.
Orchestrator tracks file-domain conflicts in
`state.in_flight_file_domains` — when a candidate executor's
`suggested_files_to_change` overlaps an in-flight executor's domain,
queue it instead of dispatching.

### Wave 3 — cross-cutting work-streams (parallel with Wave 2)
Once CCW-4 and CCW-5 land, dispatch CCW-1, CCW-2, CCW-3 in parallel with
the feature execution wave. Each touches a distinct horizontal pattern;
file conflicts with feature executors are managed via the same domain
tracker.

### Wave 4 — closeout (per-feature)
When a feature's executors all return DONE/DONE_WITH_CONCERNS, dispatch
its Closer. On CLOSED callback, update state.json and patch the
V1_FEATURE_AUDIT.md status table (in-band file edit).

### Wave 5 — Analytics v1 (post-feature-cleanup)
Once features 1-13 are CLOSED, dispatch Analytics v1 implementation per
`BEARINGS_ANALYTICS_v1.md` §4 phases. Six executor sessions, one per
phase. Phase 0 (cache_creation_tokens column) → Phase 1 (schema) →
Phase 2 (capture module) → Phase 3 (extend usage routes) → Phase 4
(analytics routes) → Phase 5 (frontend tab) → Phase 6 (promote actions).

## Spawn protocol (same as parity loop — proven)

`POST http://127.0.0.1:8787/api/sessions`:
```json
{
  "kind": "chat",
  "title": "[<role>] <id>",
  "working_dir": "/home/beryndil/Projects/active/bearings",
  "model": "<model>",
  "permission_mode": "bypassPermissions",
  "tag_ids": [2, 11],
  "description": "<role> for <target>. Runbook: .v1-ship/runbooks/<role>.md. Orchestrator: <ORCH_ID>."
}
```

Then `POST /api/sessions/{id}/prompt` with content:
```
Your runbook: /home/beryndil/Projects/active/bearings/.v1-ship/runbooks/<role>.md

Assignment:
- <key>: <value>
...
- callback_target_session_id: <ORCH_ID>

Read the runbook in full first. Then go.
```

`session_instructions` in spawn body is silently dropped — never put
runbooks there.

### Models
- Orchestrator (you): `claude-opus-4-7`.
- Verifiers: `claude-opus-4-7` (read-and-reason).
- Executors / CCW workers / Closers: `claude-sonnet-4-6`.

### Tag IDs
`[2, 11]` (Bearings + Low) for every spawned session.

## Callback patterns

### A. Verifier callback
Format: `DONE — feature N verified, K still-open, M fixed-since-audit, S superseded → .v1-ship/verified/feature-NN.jsonl`

- Append feature entry to `state.features[N]`: `verified_at`,
  `still_open_count`, `fixed_since_audit_count`, `superseded_count`.
- If K == 0: mark feature `verified_clean`; dispatch Closer.
- If K > 0: queue executors for the K STILL_OPEN findings; dispatch the
  first one whose file-domain doesn't overlap an in-flight executor.

### B. Executor callback
Format: `DONE — finding <feat-N>-<MMM> filled, commit <hash>` (or
DONE_WITH_CONCERNS / BLOCKED).

- Update finding entry: `status`, `commit`, `completed_at`.
- Sync dist if frontend touched (see Dist Sync below).
- Bump `total_findings_filled` and `total_commits` only when the callback
  names a real fix commit. Stale-finding (FIXED_SINCE_AUDIT discovered
  during execution) DWC with no new commit → record concern, do NOT bump
  counters.
- Release the executor's file domain.
- Dispatch the next queued executor whose domain is now free.
- If feature has no more STILL_OPEN findings pending and no in-flight
  executors → dispatch its Closer.

### C. CCW worker callback
Format: `DONE — CCW-N landed, commits <h1>,<h2>,...`
- Update `state.ccw[N].status = "done"`, `state.ccw[N].commits = [...]`.
- If CCW-4: unblocks the queue waiting on it; dispatch Wave 1 verifiers.
- If CCW-5: unblocks CCW-1.

### D. Closer callback
Format: `CLOSED — feature N, report at .v1-ship/closed/feature-NN.md`
- `state.features[N].status = "closed"`, `closed_at = now`.
- Patch V1_FEATURE_AUDIT.md status table: feature N row → `**CLOSED**`
  with `closed_at` date and closer session id (in-band Edit).
- If all 14 features are CLOSED and all 5 CCWs are done → advance to
  Wave 5 (Analytics).

### E. Anything else
Dave directives (`stop`, `status`, `pause`): respond concisely, do not
mutate loop state unless explicitly told. Malformed callbacks → log to
`state.parse_errors[]` and idle.

## Dist sync (CRITICAL — proven in parity loop)

The running v1 server reads `/home/beryndil/Projects/archive/bearings-v0.18.0/src/bearings/web/dist/`,
not the worktree. After every executor DONE callback that touched
frontend, sync:
```bash
rsync -a --delete /home/beryndil/Projects/active/bearings/src/bearings/web/dist/ \
                  /home/beryndil/Projects/archive/bearings-v0.18.0/src/bearings/web/dist/
```

## File-domain tracking

Every executor's `suggested_files_to_change` set is recorded in
`state.in_flight_file_domains[exec_id]`. A new executor is dispatched
only when its domain is disjoint from every in-flight set. Otherwise it
queues. On callback, the dispatching path always re-checks the queue
head against current in-flight sets.

This is the critical discipline that lets feature executors run in
parallel with CCW workers and across features without commit-conflict
chaos.

## Automatic handoff (binding)

You will hit your own context budget before the 80-finding sweep
completes. Handoff is autonomous — Dave is NOT a relay. Triggers:

- `<context-pressure>` system-reminder appears in your turn.
- Every ~30 callbacks, prophylactic check: if context feels heavy,
  initiate handoff at the next clean point (after current executor
  callbacks DONE).

Procedure:

1. Wait for any in-flight executor / CCW worker to callback DONE so
   queue state is consistent. Do NOT initiate handoff while a child
   session is mid-flight.
2. POST to `http://127.0.0.1:8787/api/sessions`:
   ```json
   {
     "kind": "chat",
     "title": "[Orchestrator Cont N] Bearings v1 ship loop",
     "working_dir": "/home/beryndil/Projects/active/bearings",
     "model": "claude-opus-4-7",
     "permission_mode": "bypassPermissions",
     "tag_ids": [2, 11],
     "description": "Successor orchestrator for v1 ship-readiness loop. Predecessor: <YOUR_ID>. State: .v1-ship/state.json."
   }
   ```
   Use `N = state.successor_chain.length + 1`.
3. Update `state.json`:
   - `orchestrator_session_id` = the new id (so future executors
     spawn pointing at the successor)
   - append to `state.successor_chain[]`:
     `{from, to, at, reason, findings_filled_at_handoff,
       features_closed_at_handoff}`
4. POST first prompt to the successor: content =
   `.v1-ship/handoff/successor-prompt.md` rendered with `<PRED_ID>`
   = your id, `<NEW_ID>` = the new id.
5. Post `READY — Cont N orchestrator online` to your OWN session
   prompt endpoint. Then idle. Successor takes over.

The successor autonomously reads runbook + state + plan + driving doc,
inspects in-flight executors, and resumes dispatching. No Dave input.

## Termination — pivot to Phase 2

When all of:
- All 14 features in `state.features` are `closed`.
- All 5 entries in `state.ccw` are `done`.
- All Analytics v1 phases (Phase 0..6) are `done`.

Phase 1 (audit-driven gap closure) is complete. **Do NOT idle.** Pivot
into Phase 2 (runtime QA) per `.v1-ship/runbooks/qa-loop.md`. Procedure:

1. Append a `phase_transition` entry to `state.successor_chain[]`:
   `{ at, from_phase: 1, to_phase: 2, findings_filled, features_closed,
     ccw_done, analytics_phases_done }`.
2. Initialize `state.phase_2 = { preflight: null, cross_cutting: {},
   feature_surveys: {}, totals: {bugs_filed: 0, bugs_fixed: 0,
   features_qa_clean: 0} }`.
3. Set `state.current_phase = 2`.
4. Spawn the QA Doctor session per qa-loop.md §"Wave 0 — Preflight".
5. On Doctor PASS callback, dispatch Wave 1 cross-cutting surveys
   per qa-loop.md.
6. Continue per qa-loop.md until QA-CLEAN final state.

Phase 2 termination:
- All 14 features QA-CLEAN AND all cross-cutting reports green →
  emit `FINAL — Bearings v1 ship-ready` to your own session AND POST
  the same message to Dave's primary chat session if one is wired in
  state. Then idle. This is the user-facing handoff.
- Phase 2 wall (browser install failed, security critical, etc.) →
  post BLOCKED with wall description AND notify Dave's session.
  Idle. This IS Dave-blocking by design — runtime walls require
  human triage.

## Hard cap

If `state.total_findings_filled >= 200` and not yet terminated, post
`BLOCKED — 200-finding cap reached. See state.json.` to your own session
and idle. (Heuristic guard against runaway dispatch — the audit register
has ~80 findings; 200 leaves headroom for newly-surfaced ones.)

## Failure recovery

If a child session shows no activity for >30 minutes per its
last-message timestamp, GET its messages; if crashed, spawn replacement.

If state.json is corrupt: post `BLOCKED — state.json corrupt` and idle.

## What you DON'T do

- Read source to compose verification logic. Verifiers do that.
- Write code. Executors do that.
- Run gates. Executors do that.
- Commit. Executors do that.
- Ask Dave anything between dispatches.
- Post status updates to Dave between cycles. state.json IS the status.

## Provenance

Inherits proven protocols from the v17→v18 parity loop
(`.audit-loop/runbooks/orchestrator.md`): callback port 8787, spawn
protocol, dist sync, lockout-best-effort. Differs in unit of dispatch
(per-feature vertical, not per-angle horizontal) and verification
posture (always re-verify HEAD; never trust the May-7 register).
