# Contributing

Thanks for working on Bearings. Conventions below come from the global `~/.claude/coding-standards.md` and the project's own `CLAUDE.md`.

## Setup

```sh
uv sync
uv run pre-commit install
```

`pre-commit install` wires the `pre-commit` AND `commit-msg` git hooks in one shot (see `default_install_hook_types` in `.pre-commit-config.yaml`).

## Verification loop

Run before claiming any change is done:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

All four must pass. CI: **none until v1.0.0** (per global CI Discipline in `~/.claude/CLAUDE.md`); the verification loop above + pre-commit hooks are the only gate while pre-1.0.

## Commit messages — conventional commits

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/). The `commitizen` pre-commit hook on the `commit-msg` stage enforces this; messages that don't match the regex are rejected.

Allowed types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `style`, `ci`, `build`, `revert`. Format:

```
<type>(<scope>): <subject>

<body — optional, wrap at 100 chars>

<footer — optional, BREAKING CHANGE: ... here>
```

Examples:
- `feat(db): add migration runner with schema_version tracking`
- `fix(errors): exit non-zero after logging uncaught exception`
- `docs: clarify build-phase status table in CLAUDE.md`

## Versioning — SemVer 2.0.0

Releases follow [SemVer](https://semver.org/). Use `cz bump` to:

1. Read commits since the last tag.
2. Decide the SemVer increment (`feat` → minor, `fix` → patch, `BREAKING CHANGE:` → major).
3. Update `[project] version` in `pyproject.toml`.
4. Append a section to `CHANGELOG.md`.
5. Tag the commit.

## Pedagogy directives

Code reviews follow three directives from `CLAUDE.md`:

1. **Concept-naming** — name the concepts a reader needs before walking through code.
2. **Standard-naming** — name the rule from `coding-standards.md` before walking through code that follows it.
3. **Boilerplate-vs-recipe-vs-app** — flag code that should live in a higher generality tier (`python-base` boilerplate, `python-recipes` patterns library, or this project) and propose extraction.

## Standards

The standards enforced are listed and explained in `~/.claude/coding-standards.md`. Highlights every contributor should internalize:

- **Op: Zero-Crash** — global exception handler, structured logging (no `print()`), defensive coding at boundaries.
- **Op: Configuration** — no hardcoded values; use `bearings.config.Settings`.
- **Op: Testing** — 80%+ business-logic coverage; TDD for domain and API logic.
- **Q1a/Q1b** — functions ≤ 40 lines, files ≤ 400 lines.
- **Q6a** — type annotations on all public function signatures.
- **Sec rule 1** — no secrets in source; use pydantic-settings + env vars.

The pre-commit hooks and the verification loop encode most of these mechanically. Anything they can't catch lives in code review.

## Vendor-risk audit

When working in code that imports the Anthropic SDK (lands in §10), keep imports confined to `src/bearings/agent/anthropic_client.py`. Audit gate before push:

```sh
grep -r "from claude_agent_sdk\|import claude_agent_sdk\|from anthropic\|import anthropic" src/ | grep -v anthropic_client.py
```

Must return zero matches.
