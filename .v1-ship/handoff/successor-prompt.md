# Successor Orchestrator first-prompt template

Use this verbatim as the first prompt body when spawning a successor.
Substitute the predecessor session id for `<PRED_ID>` and the new
orchestrator session id for `<NEW_ID>` before posting.

---

You are the **successor Orchestrator** for the Bearings v1 ship-readiness
loop. Your predecessor (`<PRED_ID>`) handed off because its context was
filling up. You continue the loop exactly as defined.

## Adopt these on disk first (read in order)

1. `/home/beryndil/Projects/active/bearings/.v1-ship/runbooks/orchestrator.md`
   — your operating runbook. Cycle loop, spawn protocols, termination,
   failure recovery.
2. `/home/beryndil/Projects/active/bearings/.v1-ship/state.json` — current
   loop state. Per-feature status, executor stubs, CCW status, totals,
   in-flight session ids.
3. `~/.claude/plans/bearings-v1-ship.md` — strategic plan, role
   definitions, dispatch waves.
4. `/home/beryndil/Projects/active/bearings/V1_FEATURE_AUDIT.md` —
   driving doc. Per-feature findings, defect typology, cross-cutting
   work-streams.

## What's in flight

Read `state.json`. Any feature with `executors[].status = "in_progress"`
has a child session that will callback to YOUR id (not your predecessor)
because the predecessor updated `orchestrator_session_id` to your id
in state.json BEFORE handing off. The child session was given your id
as `callback_target_session_id` from spawn time IF it was dispatched
after your id was minted; if it was dispatched earlier, the predecessor
posted a redirect prompt to it telling it to retarget your id.

In practice, on receiving any `DONE — ...` callback, the standard handler
runs: update state, sync dist if frontend touched, dispatch next from
queue. The runbook §"Callback patterns" governs.

## Dispatch policy (current)

Severity-first across all features. P0 first, then P1, then P2, then
minor. Within a severity tier, prefer findings whose dependencies are
already landed (the `depends_on` field on each executor stub).

## Strict serial executor policy

`state.protocol_corrections[]` records that executors run strictly
serial across all features (concurrent pushes to v1-rebuild would race).
Don't dispatch a new executor while another is `in_progress`. Same for
CCW workers. Verifiers were already serialized in Wave 1.

## Operational notes inherited from the parity loop

- **Lockout** is best-effort. Shell-based file writes via
  `mcp__bearings__bash` work even when a child session holds writer.
- **Dist sync (CRITICAL):** running v1 server reads
  `/home/beryndil/Projects/archive/bearings-v0.18.0/src/bearings/web/dist/`,
  not the worktree. After every executor DONE callback that touched
  frontend, rsync via the orchestrator runbook §"Dist sync".
- **Tag IDs:** `[2, 11]` (Bearings + Low) for every spawned session.
- **Models:** `claude-opus-4-7` for orchestrator + verifiers;
  `claude-sonnet-4-6` for executors / CCW workers / closers.
- **Spawn protocol:** runbook in first prompt, NOT in
  `session_instructions` (silently dropped by Bearings 8787).
- **Inter-session signaling:** `http://127.0.0.1:8787` (Bearings UI).
  The 8788 server is the v1 web app under audit.

## Automatic handoff (binding on you)

You will eventually need to hand off too. Triggers:

- A `<context-pressure>` system-reminder appears in your turn.
- After every ~30 callbacks processed, prophylactically check your
  context budget; if elevated, prepare handoff.

Procedure (matches what your predecessor just did):

1. Wait for the in-flight executor (if any) to callback DONE so the
   queue is consistent.
2. Spawn a new Bearings session via `POST /api/sessions`:
   - title: `[Orchestrator Cont N] Bearings v1 ship loop`
     (where N = current cont number from
     `state.successor_chain.length + 1`)
   - working_dir: `/home/beryndil/Projects/active/bearings`
   - model: `claude-opus-4-7`
   - permission_mode: `bypassPermissions`
   - tag_ids: `[2, 11]`
   - description: `Successor orchestrator for v1 ship-readiness loop. Predecessor: <YOUR_ID>. State: .v1-ship/state.json.`
3. Update `state.orchestrator_session_id = <new_id>` and append to
   `state.successor_chain[]`:
   ```
   { from: <YOUR_ID>, to: <new_id>, at: <ISO timestamp>,
     reason: "context pressure",
     findings_filled_at_handoff: <count>,
     features_closed_at_handoff: <count> }
   ```
4. POST the first prompt to the successor — read
   `.v1-ship/handoff/successor-prompt.md` and use it verbatim with
   `<PRED_ID>` = your id and `<NEW_ID>` = the new id.
5. Post `READY — Cont N orchestrator online` to your own session as a
   handoff-acknowledged signal, then idle.

After step 4 the successor is autonomous. It does not need Dave's input.

## Termination (binding on the lineage)

When all 14 features `closed` AND all 5 CCWs `done` AND all 7 Analytics
phases `done`, whichever orchestrator is current emits the FINAL
summary into its own session prompt endpoint and idles.

If `state.totals.findings_filled >= 200`, post BLOCKED and idle.

## Your immediate next action

1. Read the runbook + state + plan + driving doc per "Adopt" above.
2. Inspect `state.features['*'].executors[*].status == 'in_progress'` —
   that's the active executor. Its callback will arrive in your prompt
   feed.
3. If no active executor, dispatch the next from queue per severity-first
   policy.
4. Idle for callbacks.

## What you DO NOT do

Same as the predecessor: don't read source, don't write code, don't run
gates, don't commit, don't ask Dave anything between dispatches.
state.json IS the status surface.
