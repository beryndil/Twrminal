# CCW Worker runbook — Bearings v1 ship-readiness loop

You own one cross-cutting work-stream from V1_FEATURE_AUDIT.md
§"Cross-cutting work-streams". Same shape as an Executor but scoped
horizontally — your fix-pattern hits multiple files / modules /
features in one work item.

## Inputs (from your assignment)

- `ccw_id` — one of `CCW-1`, `CCW-2`, `CCW-3`, `CCW-4`, `CCW-5`.
- `ccw_brief` — the V1_FEATURE_AUDIT.md text for your CCW (embedded in
  your prompt verbatim).
- `dependencies_landed` — list of CCW ids whose commits you can rely
  on. (E.g. CCW-2 sees CCW-4's `db/_validators.py` already in tree.)
- `callback_target_session_id`.

## Per-CCW scope

### CCW-1 — Behavior-doc / release-notes correction pass
Eight surfaces with doc-vs-reality gaps. Concrete tasks:
1. Create `docs/behavior/routing.md` (referenced by `daily_probe.py:33`
   and `cutover_smoke.py:173`; missing entirely).
2. Memories injection: rewrite `docs/behavior/memories.md` to match
   actual behavior — defer the rewrite IF feature 7's executors land
   the missing injection. If memories injection stays unimplemented
   (DONE_WITH_CONCERNS), update the doc to say so explicitly.
3. Spawn-from-reply: add behavior doc covering
   `routes/spawn_from_reply.py`. Mention frontend pill is unwired
   if feature 6 hasn't landed it.
4. Stop-undo: align doc and code. After feature 2 lands the fix,
   re-read `chat.md` §"Stopping or interrupting" against
   `StopUndoInline.svelte` and `routes/sessions.py` recover route.
5. ANSI / soft-cap / copy-text / `[stopped]`: align
   `tool-output-streaming.md` and `chat.md` with whatever feature 2
   lands.
6. `session.merge_into` and `session.export_json`: document in
   `docs/behavior/context-menus.md`.
7. `[Unreleased]` features (tag classes, import, SDK history,
   preferences, permission-mode): one paragraph each in the relevant
   behavior doc per CHANGELOG §[Unreleased] entries.
8. Run `lychee` against the docs tree before commit.

### CCW-2 — POST↔PATCH validator-drift grep + fix
Three confirmed instances. Pattern: every POST handler in
`web/routes/*.py` calling a `_validate_*` function whose PATCH
counterpart skips it.
1. `grep -nE 'def (post|create|add)_' src/bearings/web/routes/*.py` —
   list every POST handler.
2. For each, find `_validate_*` calls.
3. For each, find the matching PATCH handler in the same module.
4. Confirm the PATCH calls the same validators. Add the missing call
   where it doesn't.
5. Add a pytest case per fix: PATCH path with the invalidating input
   returns 422.
6. Confirmed instances: tag cardinality (sessions PATCH),
   `DISPLAY_NAME_MAX_LENGTH` (preferences PATCH).

### CCW-3 — Broadcaster correctness work-stream
WebSocket fan-out has at least three independent gaps. Build a
broadcaster contract: every mutation handler MUST publish, no skips,
test-enforced.
1. Fix `sessions_bulk.py:333-340` — capture rows before commit (race
   with concurrent delete).
2. Add `publish_upsert` to `PUT/DELETE /api/sessions/{sid}/tags/{tid}`.
3. Add broadcasts to tag CRUD: `POST/PATCH/DELETE /api/tags`,
   sort-order endpoint.
4. Snapshot `_fan_out` iteration with `list()`.
5. Cap subscriber queues; drop on overflow with structured log line.
6. Write a contract test: every public mutation route in
   `web/routes/*` matches a paired publish call (grep-asserted).

### CCW-4 — Utility-module scaffolding
Two missing shared modules. Land first; CCW-2 and several feature
fixes depend on them.
1. `src/bearings/db/_validators.py` — extract `_is_known_model` from
   `db/tags.py` and `db/templates.py`. Both call sites import from
   `_validators`. Test: each call site continues to behave identically.
2. `src/bearings/web/routes/_deps.py` — extract `_db()` and
   `_quota_poller()` duplicated in `routes/routing.py`,
   `routes/quota.py`, `routes/usage.py`. All three import from
   `_deps`.

### CCW-5 — Spec internal-consistency audit
`docs/model-routing-v1-spec.md` contradicts itself in two places.
1. `advisor_disabled_reason` appears in spec body but absent from
   frozen Appendix A `RoutingDecision` shape. Code follows Appendix A.
   Decision: either add the field to Appendix A and code, or strike
   from body. Preferred: strike from body (Appendix A is frozen and
   load-bearing).
2. No system-rule reorder endpoint in spec; frontend uses N PATCHes.
   Add the reorder endpoint to the spec at the appropriate section.
   The implementation lands as part of feature 3 cleanup, not here —
   CCW-5 is doc-only.
3. Ensure spec table-of-contents anchors resolve. lychee-equivalent
   internal-link check.

## Implementation rules

Same as `.v1-ship/runbooks/executor.md`:
- Root fix, not bandaid.
- Constants in `config/constants.py` / `frontend/src/lib/config.ts`.
- Tests for every behavior change.
- OpenAPI regen on route changes.
- Schema migrations on DB changes.
- Conventional commits, push.
- Self-verification block before callback.

## Multi-commit work

CCWs typically need 2-6 commits. That's fine. Push each as you go.
Your callback names every commit hash:
```
DONE — CCW-N landed, commits abc123,def456,...
```

## Self-verification block

Before callback, post:
```
## Self-verification — CCW-N

Tasks completed:
- [✓] <task 1> — commit <hash>, evidence: <file:lines>
- [✓] <task 2> — ...
...

Cross-feature impact:
- <feature M>: <which finding(s) this enables / closes>
- ...

Gates: PASS (full set)
Branch: v1-rebuild, all commits pushed.
```

## Status vocabulary

`DONE` · `DONE_WITH_CONCERNS` · `BLOCKED` (physical/gate only).
Code-design uncertainty → decide and move on.

## What you DON'T do

- Touch findings outside your CCW scope.
- Re-implement what feature executors are working on.
- Skip the dependency check (CCW-2 needs CCW-4 in tree first).

## Provenance

Driven by `.v1-ship/runbooks/orchestrator.md` §"Wave 0" and §"Wave 3".
