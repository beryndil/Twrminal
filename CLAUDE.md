# Bearings — Localhost Web UI for Claude Code Sessions

## Project
- **Platform**: Python 3.11+ (FastAPI) backend, SvelteKit (static) frontend,
  SQLite/aiosqlite persistence
- **Purpose**: Localhost web UI that runs Claude Code agent sessions via
  `claude-agent-sdk`, streams events over WebSocket, and keeps history in a
  local SQLite database
- **License**: MIT (deliberate deviation from the Unlicense used elsewhere —
  per spec)
- **Status**: **v1.0.0 (2026-04-29)** — dashboard redesign complete.
  The v1.0.0 mockup landed across 8 versions (v0.24 → v1.0.0): the
  forest-green Evergreen theme is the default; the left sidebar is
  banded into brand / New Session pill / nav rail / tools / system
  status / user identity; the right inspector is a 4-tab surface
  (Context / Files / Changes / Metrics); accent cards above chat
  surface token-cache savings + recovery; a bottom status bar
  carries version + working_dir + connection chrome; Memories
  (`/memories`) and Analytics (`/analytics`) are real surfaces
  backed by `tag_memory` and per-instance aggregates respectively.
  Plan archive: `~/.claude/plans/evergreen-redesigning-dashboard.md`.

  Pre-v1 highlights (post-v0.10): tag-filter sidebar OR semantics +
  Finder-click filter (v0.10), token-cost survival kit (v0.12),
  `bearings todo` CLI (v0.13), themes & skins v1 (v0.14), keyboard
  shortcuts v1 (v0.15), context-menu phases 14-16 + auto-register
  Write image artifacts + tool-output linkifier (v0.16), intra-call
  tool-output streaming + Conversation.svelte split (v0.17). v0.1
  closed at v0.1.40; tags landed in v0.2; permission profiles in
  v0.4; checkpoints / templates / vault / paired chats / live todos
  across v0.6 → v0.9.
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

## Session liveness signals (audits)

When auditing whether a session is "in use" / "complete" / safe to close:

- `last_viewed_at` is **NOT** a liveness signal. It only records that
  Dave clicked the row in the sidebar. Glancing at a row during an
  audit, scrolling past it, or opening it to read its plug all stamp
  `last_viewed_at` without producing any work.
- The real liveness signal is `message_count` (does it have a
  conversation?) plus actual transcript content (is the conversation
  ongoing or finished?). A 0-msg session is empty regardless of when
  it was last viewed.
- Corollary: don't move a session out of a "safe to close" bucket just
  because `last_viewed_at` is recent. Re-bucket only on message
  count / transcript evidence.

## Checklists ("create a checklist" — what Dave means)

When Dave says **"create a checklist"** he means a Bearings
**`kind="checklist"` session**, not a markdown TODO and not a `TodoWrite`
call. Canonical reference: `docs/checklists.md`. Read it before improvising.

Quick rules:

- **Two session kinds.** `chat` (default) has a *read-only* `/todos` view
  mirroring the agent's `TodoWrite`. `checklist` has the writable
  `/checklist/items` API. `POST /checklist/items` against a chat-kind
  session returns **400 "session is not a checklist session"**.
- **Format = §36 of `~/.claude/coding-standards.md`.** Every item needs a
  `Done when:` clause in its `notes`. Pack `Context` / `Files` /
  `Done when` / `Notes` into the single `notes` field, joined by ` | ` or
  newlines. The picking-up agent reads `label` for what to do and `notes`
  for how to verify.
- **Multi-fix audit pattern (default).** N chat sessions (one per fix,
  each with a self-contained plug) + 1 master checklist session indexing
  them. Each top-level item links to its chat via
  `POST /checklist/items/{iid}/link {"chat_session_id": "..."}`. Steps
  nest as children with `parent_item_id`. Worked Python recipe in
  `docs/checklists.md`.
- **Tag every checklist.** Minimum: one project tag + one severity tag
  (Blocker=8 / Critical=9 / Medium=10 / Low=11 / QoL=12). Look up live
  IDs via `GET /api/tags`; do not guess.
- **Title prefixes.** Master checklist: `[Audit]`, `[Roadmap]`,
  `[Refactor]`. Linked chat sessions: `[Bug]` / `[Feature]` /
  `[Security]` / `[A11y]` / `[UX]` / `[Code Quality]`.

If asked to create a checklist for follow-up work, default to the
multi-fix audit pattern unless Dave says otherwise.

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
