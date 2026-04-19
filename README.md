# Twrminal

Localhost web UI for Claude Code agent sessions. FastAPI backend streams
session events over WebSocket to a SvelteKit frontend; SQLite persists
history across restarts.

## Status

Alpha — `0.1.x` development. The v0.1 line is feature-complete and
closed out at v0.1.38; v0.1.39 is documentation/housekeeping. The v0.2
milestone (projects, tags, memory-backed system prompts) is specced in
`V0.2.0_SPEC.md`.

## Features (v0.1.x)

- Streaming Claude agent sessions via `claude-agent-sdk`: token
  deltas, thinking blocks, tool-call start/end, message-complete cost.
- Session CRUD, rename, delete, JSON import/export (single + bulk
  drag-drop), Enter-to-send / Shift+Enter newline, Stop button (SDK
  `interrupt()`), ⌘/Ctrl+K sidebar search with match highlighting,
  `?` cheat-sheet modal, message pagination.
- Per-session `max_budget_usd` cap enforced via `ClaudeAgentOptions`;
  running total cost stored on the session and rendered with amber/rose
  pressure coloring at ≥80% / ≥100%.
- Opt-in bearer-token auth (`auth.token`) across REST + WS + CLI +
  frontend AuthGate modal; 401/4401 flips the store back to `invalid`.
- Prometheus `/metrics` (sessions, messages, tool calls, WS events,
  active connections) + JSON history export/daily/search routes.
- CLI subcommands: `twrminal serve | init | send`. `send` supports
  `--format=pretty` for human-readable output and `--token` for
  authenticated servers.

## Requirements

- Python ≥ 3.11 (3.12 recommended via `.python-version`)
- Node ≥ 20
- [uv](https://docs.astral.sh/uv/)
- Claude Code authenticated locally (for the agent SDK to find credentials)

## Install

```bash
uv sync
cd frontend && npm install && npm run build
```

The frontend build writes static assets into `src/twrminal/web/dist/`, which
FastAPI mounts at `/`.

## Run

```bash
uv run twrminal serve
# then open http://127.0.0.1:8787
```

Health probe:

```bash
curl -s http://127.0.0.1:8787/api/health
```

## Service install

```bash
install -Dm644 config/twrminal.service ~/.config/systemd/user/twrminal.service
systemctl --user daemon-reload
systemctl --user enable --now twrminal.service
```

## Config

`~/.config/twrminal/config.toml`. Defaults are baked in; override only the
keys you need.

| Section    | Key                  | Default                          | Purpose                          |
|------------|----------------------|----------------------------------|----------------------------------|
| `server`   | `host`               | `127.0.0.1`                      | Bind address                     |
| `server`   | `port`               | `8787`                           | Bind port                        |
| `auth`     | `enabled`            | `false`                          | Gate REST + WS behind bearer     |
| `auth`     | `token`              | *(unset)*                        | Shared secret when `enabled`     |
| `agent`    | `working_dir`        | `~/`                             | CWD for agent sessions           |
| `agent`    | `model`              | `claude-opus-4-7`                | Default model                    |
| `storage`  | `db_path`            | `~/.local/share/twrminal/db.sqlite` | Persistence                 |
| `metrics`  | `enabled`            | `false`                          | Prometheus `/metrics` endpoint   |

## License

MIT. See `LICENSE`.
