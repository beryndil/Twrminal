# Closer runbook — Bearings v1 ship-readiness loop

You sign off one feature. All its STILL_OPEN findings have been resolved
by executors (DONE / DONE_WITH_CONCERNS / SUPERSEDED). You verify the
sum-of-fixes and write the closeout report.

## Inputs (from your assignment)

- `feature_number`
- `feature_name`
- `verified_findings_path` — `.v1-ship/verified/feature-NN.jsonl`
- `executor_log` — list of `{finding_id, status, commit, summary}` from
  state.json (embedded in your prompt as JSON).
- `closeout_path` — `.v1-ship/closed/feature-NN.md`
- `callback_target_session_id`

## Step 1 — Coverage check

Open the verified findings file. For every finding:
- STILL_OPEN → must have an executor entry with status DONE or
  DONE_WITH_CONCERNS and a commit hash.
- FIXED_SINCE_AUDIT → no executor needed; the resolving commit is in
  the verified entry.
- SUPERSEDED → no executor needed.

If any STILL_OPEN finding has no resolving entry, halt and post
`HALTED — feature N, finding <id> has no resolution`. The orchestrator
will dispatch the missing executor.

## Step 2 — Behavior end-to-end check

Pick the feature's primary spec doc(s) — typically one or two under
`docs/behavior/`. Pick three behaviors from the spec that exercise
multiple findings' fixes together (e.g. "create a session with two
project tags" exercises tag-cardinality validation AT POST and AT
PATCH plus broadcast). Read the relevant code paths and test files;
confirm the integrated behavior is wired end-to-end.

You don't run the app. You don't run tests. You read the integration
points and confirm the code paths align with the spec. Note unresolved
concerns in the closeout report.

## Step 3 — Defect-typology cross-check

V1_FEATURE_AUDIT.md §"Defect typology" lists 11 classes. For your
feature, list which classes appeared and confirm each instance was
addressed. Especially:
- "Behavior partial" — confirm the full state machine fires now, not
  just the formerly-broken branch.
- "Validator drift POST↔PATCH" — confirm both POST and PATCH paths
  call the validator.
- "Constants drift backend↔frontend" — confirm both sides agree.
- "Module exists, unwired" — confirm the integration point now imports
  / mounts / dispatches.

## Step 4 — Closeout report

Write `.v1-ship/closed/feature-NN.md` with this template:

```markdown
# Feature N closeout — <name>

**Closed:** <ISO timestamp>
**Closer session:** <your session id>
**Verifier session:** <verifier id from state.json>
**Executor sessions:** <list with finding ids and commits>

## Findings register

| ID | Verdict | Status | Commit | Notes |
|---|---|---|---|---|
| feature-N-001 | STILL_OPEN | DONE | abc123 | <summary> |
| ... |

## Behavior-spec coverage

Primary spec: `docs/behavior/<name>.md`
End-to-end behaviors verified:
1. <behavior 1> — code path: <file:lines> · test: <test name>
2. <behavior 2> — ...
3. <behavior 3> — ...

## Defect-typology cross-check

| Class | Instances in feature N | Resolved by |
|---|---|---|
| <class> | <count> | <commits> |

## Outstanding concerns

(Empty if clean. Otherwise enumerate DONE_WITH_CONCERNS notes from
executors and any unresolved P2 polish.)

## Sign-off

Feature N is **CLOSED**. All P0 and P1 findings resolved. P2 findings
either resolved or explicitly deferred (listed above).
```

## Step 5 — Patch V1_FEATURE_AUDIT.md status table

In-band Edit on `/home/beryndil/Projects/active/bearings/V1_FEATURE_AUDIT.md`:
the row for your feature in the §"Status table" changes from `INTERIM`
to `**CLOSED** (closer <your session id> · <ISO date>)`.

If your feature was already CLOSED in the May-7 register (#4, #13, #14),
your work is to re-verify and re-close: confirm the original closeout
holds against current HEAD, append `re-verified <date>` to the row, and
note in the closeout report whether anything has regressed since.

## Step 6 — Commit the closeout

Conventional commit:
```
docs(audit): close feature N — <name>
```

Includes:
- `.v1-ship/closed/feature-NN.md`
- `V1_FEATURE_AUDIT.md` (status table row update)

Push.

## Step 7 — Callback

POST to `http://127.0.0.1:8787/api/sessions/<callback_target>/prompt`:
```
CLOSED — feature N, report at .v1-ship/closed/feature-NN.md, commit <hash>
```

If you halted at Step 1:
```
HALTED — feature N, missing resolution for finding <id>
```

## What you DON'T do

- Re-implement fixes the executors already landed.
- Run gates (executors did that per finding).
- Re-verify findings (verifier already did that).
- Touch code in `src/` or `frontend/` beyond doc edits.

## Provenance

Driven by `.v1-ship/runbooks/orchestrator.md` §"Wave 4 — closeout".
