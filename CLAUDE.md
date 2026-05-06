# bearings

Localhost UI to drive Claude Code agent sessions. Self-hosted dev tool, single-user, BYO Anthropic credentials. The plan-of-record for v1 is `~/.claude/plans/bearings-v1-setup.md` — every gating decision (problem statement, vendor-risk hedge, stack picks, charter sweep, build phases) is recorded there. Read that file before starting work that touches scope or architecture.

Operational coding directives apply via `~/.claude/coding-standards.md` (loaded on every turn through the global profile). This file adds Bearings-specific stack pins and the **pedagogy directives** carried from the python-base template.

---

## Pedagogy directives

These three directives govern every code-review and code-walkthrough interaction in this project. They are not optional and not context-dependent. Apply them on the first relevant turn of every new session, without being prompted.

### 1. Concept-naming (explain-then-walkthrough)

When reviewing code, before explaining what code does, name the concepts a reader needs to understand it. If a concept hasn't come up before, explain it in 2-3 sentences before walking through the code that uses it.

A "concept" here means anything a reader has to already know — language features (decorators, context managers, async generators), library idioms (FastAPI dependency injection, Pydantic validators, structlog processors), patterns (repository, unit-of-work, migration runner), or domain primitives specific to Bearings (sessions, tags, routing, vault). **When a concept has a familiar cross-language analogue, name it** — e.g. ESLint ↔ `ruff check`, Prettier ↔ `ruff format`, npm ↔ `uv`, `package.json` ↔ `pyproject.toml`, `tsconfig.json` ↔ `[tool.mypy]`. The parallel often makes the concept land faster than abstract definition. If the same concept comes up twice in one session, don't re-explain — assume it landed.

### 2. Standard-naming (name the rule, then explain why)

When code follows a coding standard, name the standard and explain in plain language why it exists before walking through the code. When a quality-gate tool flags something, explain what the tool is checking for and why that property matters.

Applies to `~/.claude/coding-standards.md` rules ("Zero-Crash," "Configuration," "Input Validation," function-length limits, type-annotation requirements, etc.) and to tool output from `ruff`, `mypy`, `pytest`, or any other gate this project runs. Don't say "ruff flagged this" — say "ruff's `B008` checks for function-call defaults in argument lists, because Python evaluates those once at definition time and they leak state across calls; here's the line."

### 3. Boilerplate-vs-recipe-vs-app (extraction triage)

Flag anything that should live in a project boilerplate or recipes library instead of in this repo. When extracting to boilerplate/recipes, walk through making it generic — what project-specific assumptions had to be removed.

Three tiers, in order of generality:

1. **Boilerplate** (`~/Projects/templates/python-base`) — code every Python project of this shape needs. Exception handlers, logger setup, config loaders, base FastAPI app factory, CI skeleton. Most of `bearings/src/bearings/{config,log,errors,app}.py` came from here.
2. **Recipes** (`~/Projects/templates/python-recipes`) — patterns that solve a recurring need but aren't universal. Auth flows, rate-limiter implementations, retry decorators, hand-rolled migration runners.
3. **App** — code that depends on Bearings's domain. Sessions / tags / routing / vault / agent control. Stays here.

When tier-1 or tier-2 code shows up in this repo, name the tier and propose extraction back to its template. When extracting, list the project-specific assumptions removed (hardcoded paths, domain types, env-var names, business-rule constants).

---

## Stack pins (Bearings v1)

These come from `bearings-v1-setup.md` §3 and are non-negotiable for v1:

- Python ≥ 3.12, `uv` for env + deps. Not `pip` / `poetry` / `pdm`.
- Config: `pydantic-settings` (env prefix `BEARINGS_`). Not inline literals or env-soup.
- Logging: `structlog` (three-categories: programmer / operational / user-caused). Not `loguru`, `print()`, `logging` raw.
- DB: `aiosqlite` + raw SQL + per-resource query module + versioned migrations. **No ORM** (no SQLAlchemy, no peewee, no Tortoise).
- Web (lands in §8): FastAPI + thin handlers + service-layer business logic. Not Flask / Django.
- Frontend (deferred to §1/§4): likely SvelteKit static + Tailwind, carrying from v0.18.0.
- Auth (lands in §8): shared-token via `APIKeyHeader` (single token from config). Not JWT / OAuth2 / sessions / cookies.
- Quality: ruff + mypy `--strict` + pytest, pre-commit, full gate before push.

## Vendor-risk hedge (carry-forward, §2)

The entire `claude-agent-sdk` call surface lives in **one file** — `src/bearings/agent/anthropic_client.py` (added in §10). Every other module talks to Bearings's in-house interface. Audit gate:

```sh
grep -r "from claude_agent_sdk\|import claude_agent_sdk\|from anthropic\|import anthropic" src/ | grep -v anthropic_client.py
```

Must return zero matches. The §7 foundation has zero Anthropic dependencies — that's by design.

## Verification loop

```sh
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

All four must pass before claiming done. CI is **off until v1.0.0** — pre-commit + the loop above are the only gate.

## Build-phase status

| § | Phase | Status |
|---|---|---|
| 7 | Foundation (config + log + errors + DB migrations) | **Shipping in v0.1.0** |
| 8 | Web layer + auth + sessions CRUD | Pending |
| 9 | BYO Anthropic credentials | Pending |
| 10 | Agent SDK + streaming | Pending |
| 11 | Network surface for multi-device | Pending |
| 12 | Cross-platform support | Pending |
| 13 | Distribution & public release | Pending |
| 15 | Extension API | Pending |

See `~/.claude/plans/bearings-v1-setup.md` for the full table.
