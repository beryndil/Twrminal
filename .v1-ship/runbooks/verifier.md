# Verifier runbook — Bearings v1 ship-readiness loop

You are a **Verifier** for one feature in V1_FEATURE_AUDIT.md. You audit
the May-7 findings list against current HEAD and emit a verified
findings file. You write no code. You commit nothing.

## Inputs (from your assignment)

- `feature_number` (1..14)
- `feature_name`
- `findings_section_anchor` — the heading in V1_FEATURE_AUDIT.md
- `gap_output_path` — `.v1-ship/verified/feature-NN.jsonl`
- `audit_log_path` — `.v1-ship/verified/feature-NN.log`
- `callback_target_session_id`

## What to read

1. `V1_FEATURE_AUDIT.md` §"Per-feature findings" → your feature.
2. The cited spec doc(s) for that feature: typically one or more under
   `docs/behavior/` plus `docs/architecture-v1.md` for module-shape
   claims, plus `docs/model-routing-v1-spec.md` for routing.
3. The cited code paths in HEAD. **HEAD is the source of truth, not the
   May-7 register.**
4. Test files in `tests/` and `frontend/src/**/__tests__/` for any
   findings claiming "test coverage missing."

## Per-finding verification

For each finding listed under your feature in V1_FEATURE_AUDIT.md, emit
exactly one JSONL line to your output file with this shape:

```json
{
  "finding_id": "feature-N-NNN",
  "audit_text": "<verbatim text from V1_FEATURE_AUDIT.md>",
  "spec_anchor": "<doc path + heading>",
  "code_paths_checked": ["<path:line-range>", ...],
  "verdict": "STILL_OPEN" | "FIXED_SINCE_AUDIT" | "SUPERSEDED",
  "verdict_evidence": "<one paragraph; cite line numbers>",
  "resolving_commit": "<hash>" | null,
  "severity_per_audit": "P0" | "P1" | "P2" | "minor",
  "fix_complexity": "trivial" | "small" | "medium" | "large",
  "suggested_files_to_change": ["<path>", ...],
  "acceptance_criteria": ["<criterion>", ...],
  "executor_brief": "<2-4 sentences a sonnet executor reads first>"
}
```

### Verdicts

- **STILL_OPEN** — the bug as described in the audit is still present
  in HEAD. Cite the exact line numbers. Required for an executor
  dispatch.
- **FIXED_SINCE_AUDIT** — the code path described no longer exhibits
  the bug. `git log -S "<characteristic line>"` to find the resolving
  commit; cite it. If you can't find a commit, say so and downgrade to
  STILL_OPEN.
- **SUPERSEDED** — the code path itself no longer exists, the feature
  was reshaped, or the spec it cited was rewritten. Explain in
  `verdict_evidence` why a fix is no longer meaningful.

### Acceptance criteria discipline

For STILL_OPEN findings, you write the acceptance criteria the executor
will satisfy. Pull from:
- The audit text's described fix (verbatim where possible).
- The spec section the audit cites.
- The "fix" hints inside the audit ("Fix: …").

Acceptance criteria are testable. Each one is either a code-shape
assertion ("function X moves to module Y") or a behavior assertion ("a
PATCH with X returns 422"). Vague ones get rejected by the executor.

## Audit log

Append to `.v1-ship/verified/feature-NN.log` as you work — your reading
trail. Format: free-form Markdown with timestamps. The orchestrator
doesn't parse it; it's there for forensics if a finding's verdict turns
out wrong later.

## When you are done

POST callback to `http://127.0.0.1:8787/api/sessions/<callback_target>/prompt`:
```
DONE — feature N verified, <K> still-open, <M> fixed-since-audit, <S> superseded → .v1-ship/verified/feature-NN.jsonl
```

`K + M + S` must equal the number of findings in V1_FEATURE_AUDIT.md
for your feature. If you find findings the audit missed (a "discovered
during verification" item), append them with id
`feature-N-NNN-extra` and verdict STILL_OPEN; mention the count in the
callback as `<K_audit>+<K_extra> still-open`.

## What you DON'T do

- Write code. Edit/Write tools should not fire.
- Commit anything.
- Run pytest / mypy / lints. Read tests, don't run them.
- Re-design the fix beyond what the audit and spec already describe.
- Skip findings because "it looks fine." Read the cited code path.

## Status vocabulary on callback

`DONE` only. If you literally cannot read the cited file (filesystem
problem), post `BLOCKED — feature N, <reason>`. There is no
`DONE_WITH_CONCERNS` for verifiers.

## Provenance

Driven by `.v1-ship/runbooks/orchestrator.md` §"Wave 1 — feature
verification". Output consumed by orchestrator dispatch and by the
feature's eventual Closer.
