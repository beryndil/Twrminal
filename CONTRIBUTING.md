# Contributing to Bearings

Bearings is a single-operator localhost web UI for Claude Code agent
sessions. This file covers the basics: how to set up a working tree,
run the app, satisfy the quality gates, and land a change.

Project-specific conventions and the deeper "why" live in
[`CLAUDE.md`](CLAUDE.md). Cross-cutting Beryndil standards
(error handling, security, testing, agent-first docs, etc.) live in
`~/.claude/CLAUDE.md` and `~/.claude/rules/` on Dave's workstation.
Read those before making non-trivial changes.

## Prerequisites

- **Python ≥ 3.11** (3.12 pinned via `.python-version`).
- **Node ≥ 20** (CI runs on Node 20; the toolchain pulls
  `@types/node@^25` and Vite 6, so Node 18 is no longer supported
  even though older docs may still mention it).
- **[uv](https://docs.astral.sh/uv/)** for the Python toolchain.
- A locally authenticated **Claude Code** install — the agent SDK
  reads its credentials from your existing `~/.claude/` setup.

## Setup

Clone, then resolve both halves of the project:

```bash
uv sync
cd frontend && npm install
```

`uv sync` installs the Python package and its dev group (pytest,
ruff, mypy, pytest-asyncio, etc.). `npm install` brings in the
SvelteKit + Vite + Tailwind frontend toolchain.

## Run

Two processes — one for the backend, one for the frontend dev server:

```bash
# Terminal 1: FastAPI backend on http://127.0.0.1:8787
uv run bearings serve

# Terminal 2: SvelteKit dev server on http://127.0.0.1:5173
cd frontend && npm run dev
```

For a production-shape run, build the frontend bundle once and let
FastAPI serve it from `src/bearings/web/dist/`:

```bash
cd frontend && npm run build
uv run bearings serve   # now serves the built bundle at /
```

## Quality gates

Run all six before every commit. CI runs the same set
(`.github/workflows/ci.yml`).

```bash
# Backend
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest

# Frontend
cd frontend && npm run check
cd frontend && npm run test
```

`mypy` is strict-typed (configured in `pyproject.toml`); new code is
expected to type-check cleanly without `# type: ignore` escape
hatches unless there is a specific upstream-typing reason.

`npm run check` runs `svelte-kit sync` then `svelte-check` — the
type-checking pass for Svelte components.

## Commit conventions

[Conventional Commits](https://www.conventionalcommits.org/) — same
rule set as the rest of the Beryndil ecosystem (see
`~/.claude/rules/git-workflow.md`):

```
feat(api): add POST /api/sessions/{id}/prompt for cross-session injection
fix(frontend): stop softRefresh from clobbering open edit dialogs
docs(contributing): document the six quality-gate commands
refactor(checklist): split ChecklistView render path into 3 subcomponents
test(messages): cover replay-on-restart fail-closed path
chore(deps): bump claude-agent-sdk to 0.1.66
```

Allowed types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`,
`style`, `build`, `ci`, `perf`. Scope is optional but encouraged for
larger commits — pick one of `api`, `frontend`, `backend`,
`checklist`, `tags`, `auth`, `db`, `cli`, `docs`, etc.

A "commit" means **both** `git commit` AND `git push`. The remote is
the source of truth. Don't stack uncommitted work for a per-commit
approval round; commit and push as you go.

## Pull-request process

1. **Branch from `main`**. Use a short topical name —
   `feat/cross-session-prompt-injection`, `fix/softrefresh-churn`,
   `docs/contributing`.
2. **Run the quality gates locally** (the six commands above) before
   pushing. CI runs the same set against your PR branch.
3. **Open a PR with a Conventional-Commits-shaped title** — the
   title becomes the squash-merge commit on `main`. Body should
   describe what the change does, why, and any verification
   commands you ran beyond the standard gates.
4. **CI must be green** before merge. The `backend` and `frontend`
   jobs in `.github/workflows/ci.yml` are required.
5. **At least one reviewer pass** for non-trivial changes (anything
   beyond a typo fix, a docs touch-up, or a self-contained green-CI
   refactor). For solo maintenance work, use a self-review pass:
   re-read the diff with the goal of finding the obvious flaw, fix
   it, then merge.
6. **One logical change per PR.** Multiple unrelated fixes get
   split. Keep the diff reviewable.

There is no PR template at present. If you find yourself writing the
same boilerplate three PRs in a row, propose adding `.github/PULL_REQUEST_TEMPLATE.md`.

## Code style

- **Functions: max 40 lines. Files: max 400 lines.** Hard caps —
  split before you cross them.
- **Named constants**, not magic numbers. The few unavoidable raw
  numbers (HTTP status codes, well-known port `8787`) get an inline
  comment explaining what they are.
- **Follow the formatter.** `ruff format` for Python; the frontend
  follows whatever Svelte/TS conventions `svelte-check` enforces.
  Don't hand-tune formatting.
- **`mypy` strict**. Type every public function signature; prefer
  precise types (`list[Tag]`, not `list[Any]`).
- **No hardcoded secrets**, ever. Wire credentials through config
  or the keyring — never through environment variables checked in
  to CI, and never into the repo.
- **Reuse approved patterns** already established in the codebase.
  Before introducing a new infra/framework pattern, search for an
  existing solution in `src/bearings/` and `frontend/src/` first
  (see `~/.claude/rules/search-before-build.md`).
- **Brownfield discipline**: keep diffs minimal in files you don't
  own. New behavior goes in new files when reasonable.

The deeper rationale for these rules — why 40-line functions,
why named constants, why `mypy` strict — is in
[`CLAUDE.md`](CLAUDE.md) and `~/.claude/coding-standards.md`. This
file is the contributor-facing summary; that file is the
authoritative spec.

## Where to ask

Bearings is a single-operator project. There is no issue tracker
discipline yet; if something's broken or unclear, file it in the
project's `TODO.md` and surface it to Dave directly.
