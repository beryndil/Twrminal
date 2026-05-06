# bearings

Localhost UI to drive Claude Code agent sessions — sessions, tags, routing, streaming, vault, checklists.

Bearings is a self-hosted dev tool. Run it on your workstation, point a browser at the localhost UI, and use it to launch and steer Claude Code agent sessions: route prompts by effort, tag and replay flows, stream tool output, manage paired chats and checklists. The agent control surface is what Bearings does that no editor does — the user keeps their real editor (VS Code, Neovim, JetBrains, Zed, …) for everything editor-shaped.

Status: **v0.1.0 — foundation only.** This release ships the bootstrap layer (config + structured logging + global exception handler + SQLite schema migrations) and exits cleanly. The web layer, agent integration, and UI land in subsequent phases. Plan-of-record: `~/.claude/plans/bearings-v1-setup.md`.

## Stack

- Python 3.12+, [`uv`](https://docs.astral.sh/uv/) for env + deps.
- [`hatchling`](https://hatch.pypa.io/latest/) build backend, src-layout.
- [`pydantic`](https://docs.pydantic.dev/) v2 + [`pydantic-settings`](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — single config module, env-driven.
- [`structlog`](https://www.structlog.org/) — JSON in prod, coloured console in dev; PII redaction processor on every event.
- [`aiosqlite`](https://aiosqlite.omnilib.dev/) + raw SQL + per-resource query module + hand-rolled versioned migrations. **No ORM.**
- [`ruff`](https://docs.astral.sh/ruff/) (lint + format), `mypy`, `pytest` + `pytest-asyncio` + `pytest-cov` (80% gate), `commitizen`.

The web layer (FastAPI), Anthropic SDK isolation (single `anthropic_client.py`), and the SvelteKit frontend land in §8–§13 of the plan.

## Verification loop

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

All four must pass before claiming a change is done. CI is **off until v1.0.0** per the global CI Discipline rule — pre-1.0 the verification loop above plus pre-commit are the only gate.

## Run the foundation

```sh
uv run bearings
```

Output (development mode, default): a coloured `app.starting` event, a `db.migrations.applied` event for `0001_initial.sql` on first run, an `app.ready` event with the resolved DB path, and clean exit. Subsequent runs log `db.migrations.up_to_date` instead.

## Configuration

All tunables come from `BEARINGS_*` env vars (or a `.env` file at the repo root). See `.env.example` for the committed contract. Defaults assume an `XDG_DATA_HOME`-style data directory at `~/.local/share/bearings/`.

## License

[MIT](LICENSE).
