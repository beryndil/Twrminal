# Bearings CLI — observable behavior

The `bearings` command is the user's terminal entry point to the Bearings server, the per-directory `.bearings/` context system, garbage collection, and the TODO.md discipline tooling. This document lists the user-observable shape of every subcommand: what stdout looks like, what stderr looks like, and what each exit code means. Implementation choices are governed by `docs/architecture-v1.md`.

Sibling subsystems referenced here:
[chat](chat.md), [prompt-endpoint](prompt-endpoint.md), [vault](vault.md).

## Top-level shape

```
bearings [--version] <subcommand> [...]
```

* `--version` prints `bearings <version>` to stdout and exits 0.
* No subcommand prints the usage block to stderr and exits 2 (argparse default).
* Unknown subcommand prints an argparse error to stderr and exits 2.
* `bearings <subcommand> --help` prints that subcommand's help to stdout and exits 0.

## Subcommand summary

| Subcommand | Purpose |
|---|---|
| `serve` | Run the FastAPI server (binds host/port from config). |
| `init` | Materialize config + DB on disk; optionally apply a permission profile. |
| `window` | Open the UI in a standalone browser window (Firefox preferred, Chromium fallback). |
| `send` | Send a one-shot prompt to a session and stream events. |
| `here` | Per-directory `.bearings/` context (init, check). |
| `pending` | Manage in-flight operations in `.bearings/pending.toml`. |
| `gc` | Garbage-collect on-disk state (uploads, etc.). |
| `todo` | TODO.md discipline tooling (open, check, add, recent). |

### Common observable conventions

* Exit `0` — success.
* Exit `1` — operation-level failure (no browser found, file unreadable, target not found, etc.). Always paired with a `stderr` message naming what went wrong.
* Exit `2` — usage / validation error (mutually-exclusive flags combined, malformed arguments, unknown subcommand). Always paired with an argparse-style message on `stderr`.
* Single-line stdout outputs end with a newline.
* Multi-line outputs use a stable column ordering so downstream `grep` / `awk` pipelines remain reliable across versions.

## `bearings serve`

Starts the server. The user observes:

* Banner on stdout (suppressible via `profile.show_banner = false` in config) showing the active permission profile and a per-gate audit table — auth on/off, bypassPermissions allowed, MCP-server inheritance, hooks inheritance, working-dir defaults, FS picker root, commands palette scope, idle TTL, and the bind address.
* Uvicorn's normal access log on stderr.

Failure modes:

* **Bind/auth interlock fails.** When `server.host` is non-loopback and auth is disabled, `serve` refuses to start. stderr carries an explanatory message that says "refusing to bind <host> without auth" and points at the config keys to flip. Exit `2`.
* **Port already in use.** Uvicorn surfaces the OSError; exit non-zero. The user reads the underlying message on stderr.

## `bearings init`

Materializes `config.toml` and the SQLite DB on disk under XDG paths.

```
bearings init [--profile <name>]
```

Stdout:

* `config ready at <path>`
* `database path <path>`
* When `--profile <name>` is supplied, prints `profile '<name>' written to <path>` (before the two lines above), the auto-generated auth token (when auth ends up enabled), an empty line, and the per-gate audit banner the same shape `serve` shows.

Idempotent — re-running with no `--profile` only ensures the paths exist. Re-running with a `--profile` overlays the profile's keys onto the existing config (operator-edited keys the profile does not touch survive untouched).

Failure modes:

* **Unknown profile.** argparse rejects at parse time. Exit `2`.
* **Cannot create XDG paths.** Underlying OSError surfaces on stderr. Exit `1`.

## `bearings window`

```
bearings window [--host H] [--port P] [--browser PATH] [--plain | --profile PATH]
```

Opens the UI in a standalone browser window. Detaches the spawned process; `bearings window` returns as soon as the spawn succeeds.

Stdout: nothing.
Stderr (success): `bearings window: opened http://<host>:<port>/ via <browser-path>`.

Failure modes:

* **`--plain` and `--profile` both passed.** stderr: "bearings window: --plain and --profile are mutually exclusive." Exit `2`.
* **No supported browser found** (autodetect failed and `--browser` not supplied). stderr lists the autodetect candidates and offers a manual override + a paste-ready URL the user can put in any browser. Exit `1`.

Observable browser-flavor choices: Firefox-family browsers get Bearings' bundled SSB profile (collapsed tabs / nav / bookmarks via `userChrome.css`) and a `--new-window` flag. Chromium-family browsers get `--app=URL` (their native chromeless mode). The escape hatches `--plain` (no Bearings customization) and `--profile <dir>` (point at a user-supplied profile dir) are mutually exclusive.

## `bearings send`

Send a one-shot prompt to an existing session and stream agent events.

```
bearings send --session <id> [--host H] [--port P] [--token T] [--format json|pretty] <message>
```

Stdout (default `--format json`): one JSON object per line, in arrival order, ending with a `message_complete` (or `error`) frame. Tokens stream as `{"type":"token","text":"..."}` frames per chunk.

Stdout (`--format pretty`): tokens stream inline without per-frame newlines; tool calls render as `↳ tool <name> (<input>)` and `← ok: <output>` (or `← error: <body>`); each turn ends with a 40-character horizontal rule and a cost-USD readout when known.

Exit codes:

* `0` on `message_complete`.
* `1` on `error` event in the stream.

Auth: `--token` overrides config; otherwise `auth.token` from config is used when `auth.enabled`. With auth disabled, no token is sent.

## `bearings here`

```
bearings here init [--dir PATH]
bearings here check [--dir PATH]
```

* `init` runs the onboarding ritual against the target dir (default CWD), prints the brief, and writes `.bearings/manifest.toml`, `.bearings/state.toml`, an empty `.bearings/pending.toml`. Final stdout line: `Wrote .bearings/ to <root>`. Exit `0`.
* `check` re-validates the directory's environment + git state, bumps `state.toml.last_validated`. Stdout: `Revalidated <path>: branch <name>, <clean|dirty>.` and `last_validated = <iso8601>`. One additional line per environment note. Exit `0`.

Failure modes:

* **`.bearings/` missing on `check`.** stderr surfaces a FileNotFoundError; exit `1`.

## `bearings pending`

```
bearings pending add <name> [--description D] [--command C] [--dir PATH]
bearings pending resolve <name> [--dir PATH]
bearings pending list [--dir PATH]
```

* `add` writes (or updates) the named row in `.bearings/pending.toml`. Stdout: `Pending: <name> (started <iso8601>)`. Exit `0`.
* `resolve` removes the named row. Stdout: `Resolved: <name>`. **Failure mode:** unknown name → stderr `No pending op named '<name>'.`, exit `1`.
* `list` prints all pending operations oldest-first. Stdout: one row per op (`<iso8601>  <name> — <description>`); empty case prints `(no pending operations)`. Exit `0`.

## `bearings gc uploads`

Sweep on-disk upload subdirs older than the retention window.

```
bearings gc uploads [--retention-days N] [--dry-run]
```

Stdout (with matches):

* Header: `bearings gc uploads: <pruning|would prune> N subdir(s) under <dir>`
* One line per matched subdir: `  <path>  (<human-bytes>, <age-days>d old)`
* Footer:
  * Live mode — `  removed: N subdir(s), freed <human-bytes>`. Exit `0` on full success; exit `1` if any individual subdir failed (the failures are also surfaced one-per-line on stderr `failed to remove <path>: <message>` so a recurring permissions issue is visible across runs without parsing the success summary).
  * Dry-run — `  total: N subdir(s), <human-bytes> (dry-run, nothing removed)`. Exit `0`.

Stdout (no matches): `bearings gc uploads: nothing to prune under <dir>` and `  retention: <N> days, scanned <dir>`. Exit `0`.

Failure modes:

* **Negative `--retention-days`.** stderr: `bearings gc uploads: --retention-days must be ≥ 0 (got <n>).` Exit `2`.

## `bearings todo`

The TODO.md discipline tooling. Four subcommands; all of them walk the project tree starting from the CWD.

### `bearings todo open`

```
bearings todo open [--status S] [--area A] [--format text|json]
```

Lists every Open / In Progress entry across every TODO.md in scope. Default `--status` is `Open,In Progress`; supply `any` to get every status (Open, Blocked, In Progress).

* `--format text` — one block per entry; human-readable.
* `--format json` — one JSON array; each entry has the parsed structured fields.

Exit `0`.

### `bearings todo check`

```
bearings todo check [--max-age-days N] [--format text|json] [--quiet]
```

Lints every TODO.md for format and staleness. Exit codes:

* `0` — no findings.
* `1` — at least one finding.

`--quiet` suppresses per-finding text lines; only the summary is printed.

### `bearings todo add`

```
bearings todo add <title> [--status S] [--area A] [--body B] [--file PATH]
```

Appends a properly-formatted stub entry. Default `--status` is `Open`. Default target is `./TODO.md`; `--file` overrides. Stdout reports the file appended to and the entry's heading. Exit `0` on success; exit `1` if the target file is unwritable.

### `bearings todo recent`

```
bearings todo recent [--days N] [--format text|json]
```

Lists entries that changed in the last N days (default 7). Output shape mirrors `open`. Exit `0`.

## Config-file resolution observable behavior

Every subcommand resolves the active config the same way:

1. The XDG config path under the user's `~/.config/bearings/` (canonical location).
2. When that file is absent, defaults are used; the subcommands that need a writable path (`init`, `gc`) create the directory tree as needed.
3. `--host` / `--port` / `--token` flags on `serve`, `window`, and `send` override the corresponding config values for that invocation only.

The user observes:

* `bearings init` is the canonical bootstrap; running any other subcommand without first running `init` works as long as the defaults suffice for that subcommand.
* Editing `~/.config/bearings/config.toml` between two `bearings serve` invocations takes effect on the next serve; there is no mid-process reload.
* `bearings init --profile <name>` reapplied after manual edits will only overwrite the keys the profile owns. User-edited keys outside the profile's scope survive.

## HTTP action endpoints for pending operations

The frontend fires these endpoints directly rather than shelling out to
the CLI (`POST /api/shell/exec`). Both endpoints mutate
`.bearings/pending.toml` in the given project directory and return 204
on success.

| Method | Path | Semantic |
|---|---|---|
| `POST` | `/api/pending/{name}/resolve?directory=<abs>` | Mark as resolved |
| `DELETE` | `/api/pending/{name}?directory=<abs>` | Dismiss |

Both endpoints:

* Remove the named entry from the `[ops.*]` TOML table and persist the
  file immediately (no buffered writes).
* Return `204 No Content` on success.
* Return `404` when the named op does not exist in the file (or the
  file is absent).
* Return `500` on OS-level write failures.

The `directory` query parameter is the absolute path to the project
root (the session's `working_dir`). The `name` path segment is URL-
encoded.

The frontend's `PendingOpsCard` only removes a row from the in-memory
store after receiving a `2xx` response. A non-2xx response leaves the
row visible and renders an inline error message inside the card.
Closing and re-opening the card re-fetches `.bearings/pending.toml`
from disk, so resolved/dismissed entries do not re-appear.

## What the CLI does NOT do

* It does not edit message history.
* It does not bypass auth — `--token` is forwarded; it cannot disable auth on a server that requires it.
* It does not write to `.bearings/` outside `pending.toml`, `manifest.toml`, and `state.toml`.
* It does not run agent loops in-process (everything is delegated to the `serve` server). `bearings send` is a thin streaming client over the WebSocket.
