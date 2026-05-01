# Bearings

[![CI](https://github.com/Beryndil/Bearings/actions/workflows/ci.yml/badge.svg?branch=v1-rebuild)](https://github.com/Beryndil/Bearings/actions/workflows/ci.yml)
[![Coverage ≥ 80%](https://img.shields.io/badge/coverage-%E2%89%A580%25-brightgreen.svg)](docs/architecture-v1.md)
[![Python ≥ 3.12](https://img.shields.io/badge/python-%E2%89%A53.12-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey.svg)](#license)

Localhost web UI that streams Claude Code agent sessions. Bearings surfaces
each running agent as a sidebar row, captures its conversation transcript
in SQLite, and exposes a typed HTTP/WebSocket API for paired chats,
checklists, vault, and per-message routing/usage.

This branch (`v1-rebuild`) is the **v1.0.0 release** — the stability
commitment after a two-week dogfood window on the v0.18.0 cutover, with
model-routing v1 shipped from day one. v0.17.x lives at
`/home/beryndil/Projects/Bearings/` and is **behavioral reference only**
past Phase 0.

## Highlights

* **Routing v1** — per-tag and system-wide rules, advisor consultation,
  quota guard with downgrade banner, override-rate aggregator. Spec at
  [`docs/model-routing-v1-spec.md`](docs/model-routing-v1-spec.md).
* **Per-message routing/usage** persisted on every assistant turn:
  executor + advisor model usage, source, reason, matched rule.
* **Five-tab inspector** (Agent / Context / Instructions / Routing /
  Usage) with 7-day headroom chart, by-model table, advisor-effectiveness
  widget, and rules-to-review list.
* **Checklists + auto-driver** — paired chats spawn from checklist items;
  sentinels surface item state in the sidebar.
* **Vault + memories** — system-prompt overlays per tag, vault search.
* **Themes + keybindings + context menus** — theme provider with
  no-flash boot, keybinding registry with cheat-sheet, right-click
  palette per [`docs/behavior/context-menus.md`](docs/behavior/context-menus.md).
* **Migration script** — one-shot `~/.local/share/bearings/` →
  `~/.local/share/bearings-v1/` cutover with dry-run mode.

## Quickstart

```bash
# Clone + per-worktree hooks isolation + uv sync
scripts/setup-worktree.sh

# Quality gates
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest -q
uv run pre-commit run --all-files

# Run the server (defaults to port 8788)
uv run bearings serve
```

The static frontend bundle lands at `src/bearings/web/dist/` and is
committed alongside the wheel — a fresh clone serves the UI without a
Node toolchain.

## Concurrent run with v0.17.x

| | v0.17.x | v1 |
|---|---|---|
| Port | 8787 | **8788** |
| DB | `~/.local/share/bearings/` | `~/.local/share/bearings-v1/` |
| systemd unit | `bearings.service` | `bearings-v1.service` |

Both can run side-by-side on the same machine; nothing is shared at
runtime.

## Documentation

| Concern | Location |
|---|---|
| Architectural decomposition | [`docs/architecture-v1.md`](docs/architecture-v1.md) |
| Model-routing v1 specification | [`docs/model-routing-v1-spec.md`](docs/model-routing-v1-spec.md) |
| Per-subsystem observable behavior | [`docs/behavior/`](docs/behavior/) — chat, checklists, vault, paired chats, themes, keyboard shortcuts, context menus, tool-output streaming, prompt endpoint, bearings CLI |
| FastAPI OpenAPI export | [`docs/openapi.json`](docs/openapi.json) |
| Project + agent contract | [`CLAUDE.md`](CLAUDE.md) |
| Release history | [`CHANGELOG.md`](CHANGELOG.md) |
| Deferred / orphaned work | [`TODO.md`](TODO.md) |

## Repository invariants

* Branch: `v1-rebuild` (orphan history). Pre-commit `branch-verifier`
  hook rejects commits to any other branch.
* SDK pin: `claude-agent-sdk~=0.1.69` (compatible-release).
* Python: ≥ 3.12. Type-checking: `mypy --strict`, no `Any`.
* Versioning: SemVer 2.0.0; `1.0.0` reserved for stability commitment
  after dogfood.

## Contributing

The build is driven by an autonomous executor pipeline anchored in
`~/.claude/plans/bearings-v1-rebuild.md`. Outside contributors:

1. Read [`CLAUDE.md`](CLAUDE.md) for the project contract.
2. Open a discussion before sending a PR — the rebuild is currently
   sequenced through the master checklist and ad-hoc patches collide
   with in-flight items.
3. Follow conventional-commit messages
   (`feat:` / `fix:` / `refactor:` / `docs:` / `test:` / `chore:`).
4. Run the full quality-gate suite before pushing
   (`uv run pre-commit run --all-files`).

## License

MIT (declared in `pyproject.toml`). The full SPDX text applies.
