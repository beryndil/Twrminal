# CLI

The `bearings` console-script is the user's terminal entry point.
This guide covers the **shipped** v1.0.0 surface — `serve`, `gc`,
`todo` — plus the v1.0.0-planned subcommands documented in the
behavior spec but not yet wired in code (`init`, `window`, `send`,
`here`, `pending`).

For the per-subcommand stdout/stderr/exit-code contract see
[../behavior/bearings-cli.md](../behavior/bearings-cli.md). For
the configuration model the CLI reads see
[../architecture-v1.md §1.1.2](../architecture-v1.md#112-bearingsconfig--configuration--named-constants).

## What you can do here

* [Run the server](#bearings-serve)
* [Garbage-collect old uploads](#bearings-gc-uploads)
* [Walk every TODO.md in the project tree](#bearings-todo)
  * [Open / In Progress only](#bearings-todo-open)
  * [Lint for format and staleness](#bearings-todo-check)
  * [Append a new entry](#bearings-todo-add)
  * [Recently-changed entries](#bearings-todo-recent)
* [Subcommands documented but not yet shipped in v1.0.0](#planned-subcommands)

---

## Walkthrough

### Top-level shape

```
bearings [--version] <subcommand> [...]
```

* `--version` prints `bearings <version>` and exits `0`.
* No subcommand → prints usage to stderr, exits `2` (argparse default).
* Unknown subcommand → argparse error on stderr, exits `2`.
* `bearings <subcommand> --help` → that subcommand's help on
  stdout, exits `0`.

Common observable conventions across every subcommand:

| Exit | Meaning |
|---|---|
| `0` | success |
| `1` | operation-level failure (browser autodetect failed, file unreadable, …) — paired with a stderr message naming the failure |
| `2` | usage/validation error (mutually-exclusive flags combined, malformed arguments, unknown subcommand) — paired with an argparse-style stderr message |

Single-line stdout outputs end with a newline. Multi-line outputs
use stable column ordering so `grep` / `awk` pipelines stay
reliable across versions.

### `bearings serve`

```bash
bearings serve [--host H] [--port P]
```

Starts the FastAPI server. Banner on stdout (suppressible via
`profile.show_banner = false` in config) lists the active
permission profile and a per-gate audit table. Uvicorn's normal
access log goes to stderr.

Failure modes:

* **Bind/auth interlock fails.** When `server.host` is non-loopback
  and auth is disabled, `serve` refuses to start. stderr says
  `refusing to bind <host> without auth`. Exit `2`.
* **Port already in use.** Uvicorn's OSError surfaces on stderr.

The systemd unit `bearings-v1.service` invokes the same binary; if
you've enabled the unit, you don't need to start the server manually.

### `bearings gc uploads`

Sweep on-disk upload subdirs older than the retention window.

```bash
bearings gc uploads [--retention-days N] [--dry-run]
```

Default retention is the value of `uploads.retention_days` in
`config.toml`. `--dry-run` lists what would be removed without
deleting.

Output (with matches):

```
bearings gc uploads: pruning 12 subdir(s) under ~/.local/share/bearings-v1/uploads
  ~/.local/share/bearings-v1/uploads/abcd1234  (4.2 MiB, 31d old)
  ~/.local/share/bearings-v1/uploads/ef560987  (812 KiB, 28d old)
  …
  removed: 12 subdir(s), freed 18.4 MiB
```

Dry-run footer:

```
  total: 12 subdir(s), 18.4 MiB (dry-run, nothing removed)
```

Output (no matches):

```
bearings gc uploads: nothing to prune under <dir>
  retention: 30 days, scanned <dir>
```

Per-subdir failures (permissions, disk error) print one line on
stderr per failure (`failed to remove <path>: <message>`) and bump
the exit code to `1`. The success summary is still printed so a
recurring permissions issue is visible across runs without needing
to parse stderr.

`--retention-days` rejects negative values at parse time
(stderr, exit `2`).

### `bearings todo`

The TODO.md discipline tooling. All four subcommands walk the
project tree starting from CWD; you typically run them from the
project root (or any subdirectory inside it).

#### `bearings todo open`

```bash
bearings todo open [--status S] [--area A] [--format text|json]
```

Lists every Open / In Progress entry across every TODO.md in scope.
Default `--status` is `Open,In Progress`; supply `any` to include
Blocked entries.

* `--format text` — one block per entry, human-readable.
* `--format json` — one JSON array; each entry has the parsed
  structured fields (status, area, body, file path, line span).

Always exits `0`.

#### `bearings todo check`

```bash
bearings todo check [--max-age-days N] [--format text|json] [--quiet]
```

Lints every TODO.md for format and staleness. Exit `0` for clean
runs, `1` if at least one finding. `--quiet` suppresses per-finding
text lines and prints only the summary — convenient for CI.

#### `bearings todo add`

```bash
bearings todo add <title> [--status S] [--area A] [--body B] [--file PATH]
```

Appends a properly-formatted stub entry. Default `--status` is
`Open`. Default target is `./TODO.md`; `--file` overrides. Stdout
reports the file appended to and the entry's heading.

Exits `1` if the target file is unwritable.

#### `bearings todo recent`

```bash
bearings todo recent [--days N] [--format text|json]
```

Lists entries that changed in the last N days (default 7). Output
shape mirrors `open`. Always exits `0`.

---

## Planned subcommands (documented, not yet shipped in v1.0.0)

The behavior spec at
[../behavior/bearings-cli.md](../behavior/bearings-cli.md)
documents these; the implementation under
`src/bearings/cli/` carries a TODO comment indicating they land in
subsequent items. They will become available without behavior
changes when the implementation lands.

### `bearings init`

```
bearings init [--profile <name>]
```

Materializes `config.toml` and the SQLite DB on disk under XDG
paths. Idempotent. `--profile` overlays the named permission
profile (`safe` / `workstation` / `power-user`) onto the existing
config without touching keys the profile does not own.

Stdout includes the auto-generated auth token (when auth ends up
enabled) and the per-gate audit banner.

### `bearings window`

```
bearings window [--host H] [--port P] [--browser PATH] [--plain | --profile PATH]
```

Opens the UI in a standalone browser window. Detaches the spawned
process and returns immediately on success.

Browser-flavor handling:

* **Firefox-family** browsers get Bearings' bundled SSB profile
  (collapsed tabs / nav / bookmarks via `userChrome.css`) and a
  `--new-window` flag.
* **Chromium-family** browsers get `--app=URL` (their native
  chromeless mode).

Escape hatches `--plain` (no Bearings customisation) and
`--profile <dir>` (point at a user-supplied profile dir) are
mutually exclusive.

### `bearings send`

```
bearings send --session <id> [--host H] [--port P] [--token T] [--format json|pretty] <message>
```

Send a one-shot prompt to an existing session and stream the agent
events to stdout. `--format json` produces one JSON object per
line; `--format pretty` renders tokens inline with `↳ tool …` /
`← ok: …` markers and a per-turn cost-USD footer.

Auth: `--token` overrides config. With auth disabled no token is
sent.

### `bearings here`

```
bearings here init [--dir PATH]
bearings here check [--dir PATH]
```

Per-directory `.bearings/` context. `init` runs the onboarding
ritual against the target dir, prints the brief, and writes
`manifest.toml` / `state.toml` / empty `pending.toml`. `check` re-
validates the dir's environment + git state and bumps
`state.last_validated`.

### `bearings pending`

```
bearings pending add <name> [--description D] [--command C] [--dir PATH]
bearings pending resolve <name> [--dir PATH]
bearings pending list [--dir PATH]
```

Manage in-flight operations in `.bearings/pending.toml`. The
frontend's `PendingOpsCard` exposes the same surface via
`POST /api/pending/{name}/resolve` and `DELETE /api/pending/{name}`
— see [../api.md §pending](../api.md#pending).

---

## Reference

### Config-file resolution

Every subcommand resolves the active config the same way:

1. The XDG path `~/.config/bearings/config.toml`.
2. When that file is absent, defaults are used. Subcommands that
   need a writable path (`init`, `gc`) create the directory tree as
   needed.
3. `--host` / `--port` / `--token` flags on `serve`, `window`,
   `send` override the corresponding config values for that
   invocation only.

Editing the config between two `bearings serve` invocations takes
effect on the next serve; there is no mid-process reload.

### What the CLI does NOT do

* Does not edit message history. (Use the API or the UI.)
* Does not bypass auth — `--token` is forwarded; it cannot disable
  auth on a server that requires it.
* Does not write to `.bearings/` outside `pending.toml`,
  `manifest.toml`, and `state.toml`.
* Does not run agent loops in-process — `bearings send` is a thin
  streaming client over the WebSocket; everything else delegates
  to the running `serve` server.

---

## See also

* [behavior/bearings-cli.md](../behavior/bearings-cli.md) — full
  per-subcommand stdout/stderr contract and exit-code matrix.
* [architecture-v1.md §1.1.1](../architecture-v1.md#111-bearingscli--entrypoint-surface) — CLI package decomposition.
* [api.md §pending](../api.md#pending) — HTTP surface for the
  same `.bearings/pending.toml` operations.
* `src/bearings/cli/` — implementation. Currently contains
  `app.py`, `serve.py`, `gc.py`, `todo.py`, `_todo_io.py`. The
  planned subcommands (`init.py`, `window.py`, `send.py`,
  `here.py`, `pending.py`) land in subsequent items.
