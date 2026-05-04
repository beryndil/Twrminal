# Bearings (v1 rebuild)

Localhost web UI that streams Claude Code agent sessions. This branch
(`v1-rebuild`) is the v0.18.0 rebuild; v0.17.x lives at
`/home/beryndil/Projects/Bearings/` and is **behavioral reference only**
past Phase 0.

## Authoritative documents

| Concern | Location |
|---|---|
| Strategic plan + 29-item build order | `~/.claude/plans/bearings-v1-rebuild.md` |
| Architectural decomposition | `docs/architecture-v1.md` |
| Routing-feature spec | `docs/model-routing-v1-spec.md` |
| Per-subsystem observable behavior | `docs/behavior/<subsystem>.md` |
| Operational coding directives | `~/.claude/coding-standards.md` |
| Release history | `CHANGELOG.md` |
| Deferred / orphaned work | `TODO.md` (this repo) |
| Reader-facing project README | `README.md` |
| FastAPI OpenAPI export | `docs/openapi.json` |

When the routing spec and coding standards both apply: spec provides
*inputs* (numbers, dataclass shapes, endpoint surfaces, UI strings),
standards provides *containers* (config module, strict typing, validation
discipline, i18n-ready string tables). Audit checks both for routing
files; coding standards alone for everything else.

## Architecture at a glance

Backend (`src/bearings/`) is eight single-responsibility packages — no
god-store, no `__init__.py` re-export wall:

| Package | Responsibility |
|---|---|
| `cli/` | Typer entrypoint surface (`bearings serve` / `init` / `gc` / `todo` / `migrate`). Handlers stay thin — every body is a single call into a domain helper. |
| `config/` | Pydantic `Settings` tree + `Final[...]` named constants. Every spec-mandated number lives in `config/constants.py`; inline literals downstream are an audit failure. |
| `db/` | `schema.sql` + per-resource async queries (`sessions.py`, `messages.py`, `tags.py`, `routing.py`, `quota.py`, …). aiosqlite, no ORM. |
| `agent/` | Claude Agent SDK loop, runner, routing engine, quota guard, override aggregator, paired chats, sentinels, prompt dispatch. The bulk of the business logic. |
| `web/` | FastAPI app + `routes/` + `models/` (Pydantic) + WebSocket streaming + static-bundle serve. `app.py:create_app()` is the OpenAPI source of truth. |
| `bearings_dir/` | `~/.local/share/bearings-v1/` filesystem layout (uploads, artifacts, vault, history.jsonl, pending.toml). |
| `metrics/` | Prometheus exposition for `GET /metrics`. |
| `migrations/` | One-shot v0.17.x → v0.18.0 cutover (driven by `scripts/migrate_v0_17_to_v0_18.py`). |

Frontend (`frontend/`) is SvelteKit on Svelte 5 + Vite + Tailwind +
TypeScript. The static build output is committed under
`src/bearings/web/dist/` so a fresh clone serves the UI without any
Node toolchain installed. Per-subsystem observable behavior lives at
`docs/behavior/<name>.md` (chat, checklists, vault, paired-chats,
themes, keyboard-shortcuts, context-menus, tool-output-streaming,
prompt-endpoint, bearings-cli).

Full decomposition (class boundaries, import graph, key interfaces,
divergences from v0.17.x): `docs/architecture-v1.md`.

## Repo invariants

* Branch: `v1-rebuild` (orphan history). Pre-commit `branch-verifier`
  hook rejects commits to any other branch.
* Worktree: `/home/beryndil/Projects/Bearings-v1/`.
* SDK: `claude-agent-sdk~=0.1.69` (compatible-release pin).
* Python: ≥ 3.12. Type-checking: `mypy --strict`, no `Any` (carve-outs
  for Pydantic metaclass surface only, declared with explicit
  `# mypy: disable-error-code=explicit-any` per file).
* Versioning: SemVer 2.0.0; package version pinned in `pyproject.toml`.
  Conventional commits (`feat:` / `fix:` / `refactor:` / `docs:` /
  `test:` / `chore:`).
* Concurrent run vs v0.17.x: port **8788** (vs 8787),
  DB `~/.local/share/bearings-v1/` (vs `~/.local/share/bearings/`),
  systemd unit `bearings-v1.service` (vs `bearings.service`).
* Inline literals downstream of `bearings.config.constants` are
  forbidden — every spec-mandated number lives in the constants
  module.

## First-time setup (per fresh checkout)

```bash
scripts/setup-worktree.sh   # idempotent — wires per-worktree hooks isolation + uv sync
```

Why a setup script: this worktree shares its parent `.git/` with the
v0.17.x main worktree. Without per-worktree `core.hooksPath` isolation,
installing pre-commit here would trample the v0.17.x hooks. The script
sets `extensions.worktreeConfig=true` on the shared `.git/config`, then
`core.hooksPath=$PWD/.githooks-v1` on this worktree only. The hook shim
under `.githooks-v1/` is checked in.

## Quality gates

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest -q
uv run pre-commit run --all-files
```

CI runs the same gates plus `systemd-analyze verify` on the unit and
`lychee` on every markdown file. See `.github/workflows/ci.yml`.

The 12-tool stack is wired through `.pre-commit-config.yaml`:

* **Backend (8):** ruff (lint + format), mypy `--strict`, pytest,
  vulture, radon (cyclomatic complexity ≤ 10), interrogate (docstring
  coverage ≥ 80 %), codespell, pip-audit `--strict`.
* **Frontend (6):** eslint, prettier `--check`, svelte-check, knip,
  ts-prune, depcheck. Gated on frontend file changes + the presence of
  `frontend/node_modules/`.
* **Repo-wide (1):** lychee on every Markdown file.

## Common dev commands

```bash
# Run the server (port 8788) — stopgap launcher until `bearings serve`
# ships (see TODO.md "Stopgap launcher" entry); systemd unit calls this.
.venv/bin/python ~/.local/share/bearings-v1/launch.py

# Single test by node id, by file, or by -k expression
uv run pytest tests/test_routing.py::test_priority_ladder -q
uv run pytest tests/test_routing.py -q
uv run pytest -k "override_rate" -q

# Targeted lint / type-check on a single file
uv run mypy src/bearings/agent/routing.py
uv run ruff check src/bearings/agent/routing.py
uv run ruff format src/bearings/agent/routing.py   # writes; use --check to dry-run

# Frontend dev server (only when iterating UI; the committed bundle
# at src/bearings/web/dist/ is what the backend actually serves).
cd frontend && npm run dev

# Frontend gates — mirror the 6 frontend pre-commit hooks
cd frontend && npm run lint
cd frontend && npm run check          # svelte-check + tsc
cd frontend && npm run knip
cd frontend && npm run ts-prune
cd frontend && npm run depcheck
cd frontend && npm run format:check
cd frontend && npm test               # vitest unit
cd frontend && npm run test:e2e       # playwright; one-time: `npm run test:e2e:install`

# Rebuild the committed UI bundle after frontend changes
cd frontend && npm run build          # writes src/bearings/web/dist/
```

## OpenAPI export

`docs/openapi.json` is checked in. Regenerate it (must stay
reproducible bit-for-bit on parsed-dict equality) via:

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

The CHANGELOG entry for any item that changes the OpenAPI surface MUST
include the regeneration in the same commit. `docs/openapi.json` is
excluded from codespell.

## Reference-read protocol (binding on every executor)

* Items 0.4 onward must NOT read any file under
  `/home/beryndil/Projects/Bearings/src/` or
  `/home/beryndil/Projects/Bearings/frontend/`.
* The auditor inspects the executor transcript for tool calls touching
  those paths. Any match → automatic GAPS regardless of output quality.
* Behavioral specs at `docs/behavior/<subsystem>.md` (added in item 0.3)
  are the only authoritative behavioral source past Phase 0. Doc gaps
  surfaced during execution are landed via a behavior addendum (per
  plan §"Behavioral gap escalation"), not by reading v0.17.x source.

## Item completion contract

* **Self-verification block** precedes every DONE / DONE_WITH_CONCERNS
  post. Format and rules: `~/.claude/plans/bearings-v1-rebuild.md`
  §"Self-verification". Every Done-when criterion gets evidence; every
  reference-read claim gets a transcript-grep proof; every gate gets
  the verbatim command line.
* **Status vocabulary**: `DONE` · `DONE_WITH_CONCERNS` · `BLOCKED`
  (physical / reachability / credential walls only) ·
  `HANDED_OFF → <new_id>`. `NEEDS_CONTEXT` is retired for autonomous
  executor work.
* **Decision discipline**: never ask "A or B?" on code calls — decide
  and move on per `~/.claude/rules/decision-discipline.md`.
* **Git discipline**: a commit means `git commit` AND `git push`. The
  remote (origin/v1-rebuild) is the source of truth. `git status
  --short` MUST be empty before posting DONE.

## TODO.md discipline

`TODO.md` exists at repo root for orphaned / deferred work that is not
yet scheduled into a master-checklist item. Per the global directive,
append the moment work is deferred or an error is passed on. Scheduled
work belongs in the master checklist (id `0f6e4006fb1d4340bda9983af3432064`),
not in `TODO.md`. When a deferral lands as part of a later item's
output, strike it from `TODO.md` in the same commit that resolves it
and cite the resolving commit hash in the entry's removal trailer.
