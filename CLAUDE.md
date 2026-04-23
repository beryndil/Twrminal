# Bearings — Localhost Web UI for Claude Code Sessions

## Project
- **Platform**: Python 3.11+ (FastAPI) backend, SvelteKit (static) frontend,
  SQLite/aiosqlite persistence
- **Purpose**: Localhost web UI that runs Claude Code agent sessions via
  `claude-agent-sdk`, streams events over WebSocket, and keeps history in a
  local SQLite database
- **License**: MIT (deliberate deviation from the Unlicense used elsewhere —
  per spec)
- **Status**: Pre-release (0.x.x development). v0.1.0 is scaffold-only.
- **Repository**: `Beryndil/Bearings` (decided 2026-04-22)

## Tech Stack
- Python 3.11+ (floor), 3.12 pinned via `.python-version`
- uv + `pyproject.toml` (hatchling backend) — first Beryndil Python project on
  this toolchain. Patina/Sentinel/Fortress stay on `requirements.txt`.
- FastAPI + `uvicorn[standard]` + `websockets`
- `claude-agent-sdk` for agent orchestration
- Pydantic v2 + `pydantic-settings` for config
- `aiosqlite` for persistence (raw SQL + numbered migrations, no ORM)
- `prometheus-client` for `/metrics`
- SvelteKit with `@sveltejs/adapter-static` (SPA behind FastAPI mount)
- Tailwind CSS, shiki + marked for message rendering
- Linting: ruff. Types: mypy (strict). Tests: pytest + pytest-asyncio.

## Layout

```
Bearings/
├── src/bearings/       # Python package (CLI, server, agent, api, db)
├── frontend/           # SvelteKit app; build output → src/bearings/web/dist/
├── config/             # systemd user unit
├── tests/              # pytest suite
├── .github/workflows/  # CI
└── pyproject.toml      # uv project definition
```

## Development workflow

```bash
uv sync                                # resolve + install deps
uv run bearings serve                  # start FastAPI on 127.0.0.1:8787
cd frontend && npm install && npm run dev   # frontend dev mode
npm run build                          # produce static bundle (FastAPI serves it)
```

Quality gates (run before every commit):

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

## Database conventions

- Raw SQL via `aiosqlite`. No ORM.
- Schema in `src/bearings/db/schema.sql` describes the canonical shape.
- Migrations in `src/bearings/db/migrations/NNNN_*.sql`, applied in order.
- `db/store.py` owns connection bootstrap and query helpers.

## Configuration

- XDG paths. Config at `~/.config/bearings/config.toml`.
- `pydantic-settings` loads + validates. Defaults are declared in
  `src/bearings/config.py` — override only the keys you need in the TOML file.
- Never read env vars for secrets; wire them through config or keyring.

## Service install

Systemd `--user` unit at `config/bearings.service`. Install with
`systemctl --user enable --now bearings`.

## Task completion workflow

Write → Build → Test → Deploy (localhost) → Commit + Push + Version Bump.
Commit and push regularly as work progresses — no per-commit approval needed.

## Beryndil Development Standards

The full Beryndil standards apply. See `~/.claude/CLAUDE.md` and
`~/.claude/rules/`. Project-specific notes:

- Functions: max 40 lines. Files: max 400 lines. No magic numbers.
- No hardcoded secrets. Localhost binding only in v0.1.0; no auth gate yet.
- Route bodies return `501` until backed by real logic — keep the protocol
  surface stable while implementations land.
- UI changes: run the dev server and exercise in a browser before claiming
  done. Type-checks and unit tests don't verify feature behavior.
