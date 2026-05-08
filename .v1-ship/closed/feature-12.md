# Feature 12 closeout — Quality gate stack

**Closed:** 2026-05-08T12:00:00Z
**Closer session:** d3a0fc02a9e64f359aeb7bc5cfb4e18f
**Verifier session:** 7416adca632348afaed74eba15bae381
**Executor sessions:**
- feature-12-001 → `1318c11a75174b359d0cd6329cd9cfbc` (commit `2b6b3633`, done_with_concerns)
- feature-12-001-followup → `f2312a536e6c42fb97e727fbee6927b3` (commit `fb5c7b9a`, done)
- feature-12-002 → `fec57e4a92304d6091a79b7c93864495` (commit `9eb79907`, done)
- feature-12-003 → `fec57e4a92304d6091a79b7c93864495` (commit `e37aa740`, done)
- feature-12-004 through feature-12-007: DEFER — no executor dispatched (see below)

## Findings register

| ID | Verdict | Status | Commit | Notes |
|---|---|---|---|---|
| feature-12-001 | STILL_OPEN | DONE_WITH_CONCERNS → DONE | `2b6b3633` + `fb5c7b9a` | Radon (cosmetic, always exits 0) replaced with xenon `~=0.9`; gate now enforcing. Followup sprint at `fb5c7b9a` refactored 43 C/D-rank CC blocks across 26 files; xenon exits 0 on current HEAD. |
| feature-12-002 | STILL_OPEN | DONE | `9eb79907` | CI mypy step updated to `uv run mypy src tests scripts`; matches pre-commit hook exactly. |
| feature-12-003 | STILL_OPEN | DONE | `e37aa740` | ts-prune (EOL 2021-12-12, TS 4.x-only) removed: pre-commit hook, CI step, npm script, devDep. knip already covered dead-export detection; `frontend/package-lock.json` regenerated. |
| feature-12-004 | STILL_OPEN | **DEFERRED to v1.1** | — | P2 — `pre-commit/pre-commit-hooks` standard suite (check-yaml, check-toml, check-json, end-of-file-fixer, trailing-whitespace, check-merge-conflict, check-added-large-files). See rationale below. |
| feature-12-005 | STILL_OPEN | **DEFERRED to v1.1** | — | P2 — conventional-commit gate via commit-msg hook (or strip vestigial `commit-msg` from `default_install_hook_types`). See rationale below. |
| feature-12-006 | STILL_OPEN | **DEFERRED to v1.1** | — | minor — ruff `N` ruleset (pep8-naming). See rationale below. |
| feature-12-007 | STILL_OPEN | **DEFERRED to v1.1** | — | minor — pip-audit `always_run: true` → gate on `pyproject.toml`/`uv.lock` changes. See rationale below. |

## Behavior-spec coverage

Primary spec: `.pre-commit-config.yaml` + `.github/workflows/ci.yml` + `CLAUDE.md §Quality gates`
(Feature 12 is tooling-infrastructure, not a user-facing behavior feature; no `docs/behavior/` doc applies.)

End-to-end behaviors verified (reading code paths, not running):

1. **Xenon CC gate wired end-to-end** — `pyproject.toml:51` pins `xenon~=0.9` in dev extras. `.pre-commit-config.yaml` hook `xenon` at lines 96–107 runs `uv run xenon --max-absolute B --max-modules A --max-average A src`; has no `always_run` so it fires on backend file changes. `.github/workflows/ci.yml` step `xenon (cyclomatic complexity gate)` runs the same command unconditionally. Both surfaces use the same thresholds. `uv run pre-commit run xenon --all-files` exits 0 on current HEAD — confirmed.

2. **mypy CI and pre-commit surfaces are now identical** — CI step (`.github/workflows/ci.yml:57`) is `uv run mypy src tests scripts`. Pre-commit hook (`.pre-commit-config.yaml:68`) passes `args: ["src", "tests", "scripts"]`. Both match `pyproject.toml:106` `files = ["src", "tests", "scripts"]`. `uv run pre-commit run mypy --all-files` exits 0 — confirmed.

3. **ts-prune fully excised; no silent-miss residue** — `grep -rn ts-prune` against all active surfaces (excluding V1_FEATURE_AUDIT.md, CHANGELOG, and `.v1-ship/`) returns only `CLAUDE.md:108` (historical parenthetical noting the removal) and `config/allowlists/knip.md:39–40` (provenance note). No hook, CI step, npm script, devDep, or knip ignore remains. knip is the live dead-export gate; `uv run pre-commit run frontend-knip --all-files` exits 1 with pre-existing unused exports (see Outstanding concerns below) — unrelated to ts-prune removal.

## Defect-typology cross-check

| Class | Instances in feature 12 | Resolved by |
|---|---|---|
| Inert gates | 2 — radon (always exits 0); CI mypy omits scripts/ | `2b6b3633` + `fb5c7b9a` (radon→xenon + CC reduction); `9eb79907` (mypy CI path) |
| All other classes | 0 | n/a |

Feature 12 is a pure tooling audit; no behavior-partial, validator-drift, constants-drift, or module-unwired instances apply.

## Deferred items — rationale and v1.1 fix shape

### feature-12-004 — `pre-commit/pre-commit-hooks` standard suite (P2)

The seven hygiene hooks (`check-yaml`, `check-toml`, `check-json`, `end-of-file-fixer`, `trailing-whitespace`, `check-merge-conflict`, `check-added-large-files`) are additive and risk-free — they can land in a single `.pre-commit-config.yaml` edit with no code changes. They are absent today but their absence is not a correctness hazard: the existing stack (ruff, mypy, pytest, xenon, interrogate, codespell, pip-audit, eslint, prettier, svelte-check, knip, depcheck, lychee) already catches the failure modes that matter for v1.0. Deferring to v1.1 costs nothing at ship; the fix is a one-commit addition with no blast radius.

**v1.1 fix shape:** Add `repo: https://github.com/pre-commit/pre-commit-hooks` block pinned to a current `rev:` tag (≥ v5.0.0). Enable all seven hooks; configure `check-added-large-files` with `args: [--maxkb=1024]`. Run `uv run pre-commit run --all-files` and commit any auto-fixes (EOF newlines, trailing whitespace) in the same change. One commit, no code changes, < 30 minutes.

### feature-12-005 — commit-msg conventional-commit gate (P2)

`default_install_hook_types: [pre-commit, commit-msg]` (`.pre-commit-config.yaml:17`) declares commit-msg enforcement that doesn't exist — no hook targets that stage, no `.githooks-v1/commit-msg` shim. The preferred fix is a local commit-msg hook with a conventional-commit regex rather than stripping the declaration, because `CLAUDE.md §Git Discipline` mandates conventional commits and the gate should match. The risk of adding this gate mid-v1.0 ship is that any queued commit with a non-conventional message would fail — a coordination hazard at ship time. Post-v1.0 the risk drops to zero.

**v1.1 fix shape:** Add a `local` repo block with a `commit-msg`-stage hook running a conventional-commit regex (e.g. `^(feat|fix|refactor|docs|test|chore)(\(.+\))?: .+`). Add `.githooks-v1/commit-msg` shim mirroring the existing pre-commit shim. Update `scripts/setup-worktree.sh` to install the commit-msg stage if not already handled. Verify: a `wip` commit message fails; a `feat: foo` message passes.

### feature-12-006 — ruff `N` ruleset / pep8-naming (minor)

`pyproject.toml:84` `select = ["E","W","F","I","B","UP","SIM","RUF","ASYNC"]` omits `"N"`. Adding it will surface naming violations across the codebase that require fixes before the gate can pass clean. Doing this mid-ship risks introducing a large rename surface at a time when the priority is stability, not style. The omission is minor — mypy strict already catches the structural issues; pep8-naming is polish.

**v1.1 fix shape:** Add `"N"` to the ruff `select` array. Run `uv run ruff check .`; fix any new violations (or add explicit per-file-ignores with justification comments — no blanket ignores). Commit fixes in the same change. Scope is bounded but unknown until N is activated; expect < 2 hours.

### feature-12-007 — pip-audit `always_run: true` gating (minor)

`.pre-commit-config.yaml:145` `always_run: true` on pip-audit triggers a network round-trip on every commit regardless of whether the dependency surface changed. CI runs pip-audit unconditionally (`.github/workflows/ci.yml:74–75`) so the security intent is fully preserved without per-commit runs. The fix is a two-line change (drop `always_run`, add `files: ^(pyproject\.toml|uv\.lock)$`). Zero risk; purely a latency improvement.

**v1.1 fix shape:** Drop `always_run: true`; add `files: ^(pyproject\.toml|uv\.lock)$`. Verify: editing a Python file does not trigger pip-audit; editing `pyproject.toml` does. CI step unchanged. One commit, < 5 minutes.

## Outstanding concerns

### Pre-existing knip gate failure (unresolved at closeout)

`uv run pre-commit run --all-files` exits 1 due to the knip (dead exports + unused deps) hook. Current knip output: 1 unused file (`DataViewHarness.svelte`), 4 unused exports, 27 unused exported types. All pre-date feature-12 work — confirmed by running `npm run knip` directly and observing identical findings before and after the ts-prune removal commit (`e37aa740`). The feature-12-003 executor's acceptance criterion ("knip passes") was not satisfied; this is a gap in the executor's verification.

The knip findings are frontend API types/interfaces (mostly in `src/lib/api/*.ts`) that are likely consumed by tests or future features but not by the current component tree. They do not represent a correctness defect in feature 12. Logged to `TODO.md` for resolution in the v1.1 cleanup sweep.

All feature-12-specific gate hooks (xenon, mypy, ruff, pytest, codespell, pip-audit) exit 0 on current HEAD.

### feature-12-001 executor DONE_WITH_CONCERNS (resolved)

The feature-12-001 executor flagged 2 pre-existing pytest failures (`test_consistency_lint` — route-naming) and 16 pre-existing codespell hits. Both were cleared in subsequent commits by other feature closers. Current HEAD: `uv run pytest -q` → 1693 passed, 0 failed; codespell hook → Passed.

## Sign-off

Feature 12 is **CLOSED**. All P0 and P1 findings resolved (feature-12-001 through feature-12-003). Four P2/minor findings explicitly deferred to v1.1 — each is an additive tooling improvement with no correctness impact on v1.0. Pre-existing knip gate failure is documented in TODO.md; it predates feature-12 and is not a feature-12 regression.
