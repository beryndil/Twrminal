# Executor runbook — Bearings v1 ship-readiness loop

You implement one verified finding. Root fix, not bandaid. Gates green.
Commit. Push. Callback.

## Inputs (from your assignment)

- The verified finding entry, JSON-formatted, embedded in your prompt.
- `callback_target_session_id` — the orchestrator.

## Read first

1. The finding entry in full. Pay attention to `executor_brief`,
   `acceptance_criteria`, `suggested_files_to_change`.
2. The spec anchor cited (`spec_anchor` field).
3. The cited code paths.
4. `~/.claude/coding-standards.md` — operational coding directives.
5. `/home/beryndil/Projects/active/bearings/CLAUDE.md` — project
   conventions, gate set, branch invariants, commit rules.

## Implementation rules

- **Root fix, not bandaid.** If the finding describes a symptom, fix
  the cause. The completeness principle applies.
- **Constants in `config/constants.py`** (Python) and `frontend/src/lib/config.ts`
  (TypeScript). Inline literals for spec-mandated numbers are an audit
  failure.
- **No `Any` in Python** beyond declared Pydantic carve-outs. `mypy
  --strict` must pass on every file you touch.
- **Tests for every behavior change.** vitest for frontend, pytest for
  backend. New acceptance criteria → new test cases.
- **OpenAPI export on backend route changes.** If you change a route,
  request body, or response model: regenerate `docs/openapi.json` in
  the same commit per CLAUDE.md "OpenAPI export" section.
- **Schema migrations on DB changes.** Add to `db/schema.sql` AND
  `db/connection.py` `_ADDED_COLUMNS` migration entry.
- **No reading `/home/beryndil/Projects/Bearings/` (v0.17.x reference)
  past Phase 0.** That tree is reference-only and forbidden in this
  loop.

## Gate set (run all before commit)

```bash
cd /home/beryndil/Projects/active/bearings
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest -q
uv run pre-commit run --all-files
```

If your change touches `frontend/`:
```bash
cd frontend
npm run lint
npm run check
npm run knip
npm test
npm run format:check
npm run build   # rebuild dist/ — committed bundle
cd ..
```

If your change touches a route, model, or response shape:
```bash
uv run python -c "
import json
from bearings.web.app import create_app
spec = create_app().openapi()
with open('docs/openapi.json', 'w') as f:
    json.dump(spec, f, indent=2)
    f.write('\n')
"
```

## Commit discipline

- Conventional commits. `fix:`, `feat:`, `refactor:`, `docs:`, `test:`,
  `chore:`. Choose by scope.
- Every commit lands all gate-required artifacts in the same commit:
  the fix, the new tests, the regenerated openapi if applicable, the
  rebuilt frontend dist if applicable, the CHANGELOG entry if
  user-visible.
- Commit AND push (`git push origin v1-rebuild`). Remote is the source
  of truth. `git status --short` MUST be empty before callback.
- Branch: `v1-rebuild`. The `branch-verifier` pre-commit hook rejects
  other branches.

## Self-verification block (mandatory before callback)

Compose this verbatim and post it as your last in-session message
BEFORE the callback POST:

```
## Self-verification — finding <id>

Acceptance criteria:
- [✓] <criterion 1> — evidence: <file:lines>, <test name>
- [✓] <criterion 2> — evidence: ...
...

Gates:
- ruff check: PASS
- ruff format --check: PASS
- mypy: PASS
- pytest: PASS (<N> tests)
- pre-commit run --all-files: PASS
- frontend gates (if touched): npm run check PASS, npm test PASS (<N>), npm run build PASS

Reference-read claims: none (this loop forbids v0.17.x reads).

Git state:
- commit: <hash>
- branch: v1-rebuild
- pushed: yes
- git status --short: empty
```

## Callback

POST to `http://127.0.0.1:8787/api/sessions/<callback_target>/prompt`:
```
DONE — finding <id> filled (<one-line summary>), commit <hash>
```

If you discover during execution that the finding is already fixed in
HEAD (verifier missed it):
```
DONE_WITH_CONCERNS — finding <id> stale: <one-line evidence>; no new commit (or "dist rebuild commit <hash>")
```

If the gate set fails on your change and you can't resolve in 2
attempts:
```
BLOCKED — finding <id>, gate failure: <gate name>, <error excerpt>
```

`BLOCKED` is for physical / gate / environment problems only. Code
design uncertainty is NEVER `BLOCKED` — decide and move on per the
decision-discipline rule.

## What you DON'T do

- Ask Dave anything.
- Skip gates.
- Commit without push.
- Mark DONE without the self-verification block.
- Read v0.17.x source under `/home/beryndil/Projects/Bearings/`.
- Touch files outside the finding's domain unless absolutely required
  to make gates pass — and if you do, note it in the callback.

## Provenance

Driven by `.v1-ship/runbooks/orchestrator.md` §"Wave 2 — execution".
Inherits gate set and commit discipline from the parity loop's
executor.md.
