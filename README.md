# Bearings

Localhost web UI for Claude Code agent sessions. FastAPI backend streams
session events over WebSocket to a SvelteKit frontend; SQLite persists
history across restarts.

## Permission profiles

Bearings exposes Claude Code's full agent surface — file system access,
tool use, MCP servers, hooks. That posture is appropriate for a
single-operator workstation and dangerous on a shared box. Pick a
profile at install time so the gates start in the right position:

```bash
bearings init --profile safe          # locked-down public default
bearings init --profile workstation   # auth on, $HOME working_dir
bearings init --profile power-user    # today's permissive defaults
```

| gate                          | `safe`                        | `workstation`            | `power-user`           |
|-------------------------------|-------------------------------|--------------------------|------------------------|
| auth token                    | required, auto-generated      | required, auto-generated | off (loopback only)    |
| default `working_dir`         | `~/.local/share/bearings/workspaces/<id>` (sandbox) | `$HOME` | `$HOME` |
| `~/.claude/` settings inherit | none                          | full                     | full                   |
| MCP servers inherit           | no                            | yes                      | yes                    |
| hook scripts inherit          | no                            | yes                      | yes                    |
| `bypassPermissions` mode      | blocked                       | allowed (ephemeral)      | allowed                |
| fs picker root                | workspace sandbox             | `$HOME`                  | `$HOME`                |
| commands palette              | project `.claude/` only       | + user `~/.claude/`      | + plugin marketplaces  |
| per-session budget cap        | $5 default                    | uncapped                 | uncapped               |
| runner idle TTL               | 60 s                          | 15 min                   | 15 min                 |

Every gate is also an independent config knob — pick a profile, then
edit individual lines in `~/.config/bearings/config.toml` for
mix-and-match. The active profile name + every gate state are printed
on every `bearings serve` startup so the operator sees their posture
at a glance. `profile.show_banner = false` opts out for
systemd-user operators who already read the journal.

## Status

Alpha — `0.17.x` development. Designed for **single-operator
localhost workstation use**: this is not a multi-user shared-host
product (see *Permission profiles* above and the threat-model section
below). The 0.x line is stable enough for daily personal use but
hasn't promised API/UI stability across minor versions; tagged
0.x.0 bumps usually introduce one.

Trail of recent shipped milestones (full detail in `CHANGELOG.md`):

- **v0.2** — tags as the single organizational primitive, with
  per-tag markdown memories layered into the system prompt and
  per-tag defaults for `working_dir` / `model`.
- **v0.4** — permission-profile preset layer (`safe` / `workstation`
  / `power-user`) wraps the security-audit ship blockers.
- **v0.6** — Directory Context System (`.bearings/` on-disk
  manifest + state per directory) and replay-on-restart for
  in-flight prompts orphaned by a service stop.
- **v0.7** — severity tag group (Blocker / Critical / Medium / Low /
  QoL) with Finder-style click filtering, live-updating sidebar via
  `/ws/sessions` broadcast, and embedded chat inside checklist
  sessions.
- **v0.8** — first-class `LiveTodos` widget surfacing the agent's
  in-session TodoWrite list; checkpoints, message pin /
  hide-from-context, multi-select bulk ops, and session templates
  followed across v0.9.
- **v0.9** — registry-driven context-menu system (`menus.toml`
  override file, touch / coarse-pointer support, cheat-sheet
  discoverability), packaging fix that ships the frontend bundle
  inside the wheel, and `__version__` finally tied to package
  metadata.
- **v0.10** — tag filter combines as **OR** within a group,
  empty-selection means empty-list, severity counts scoped to the
  general selection.
- **v0.12** — token-cost survival kit: tool-output cap advisory,
  in-process MCP `bearings__get_tool_output`, PreCompact steering,
  opt-in `researcher` sub-agent, and context-pressure injection on
  the user prompt. Also: timeline virtualization above 200 items.
- **v0.13** — `bearings todo` CLI (open / check / add / recent)
  enforces the cross-project `TODO.md` discipline.
- **v0.14** — themes & skins v1 (Settings picker, no-flash boot,
  `paper-light` light theme, variable-driven shiki).
- **v0.15** — keyboard shortcuts v1 (config-driven binding registry
  with cheat-sheet rendered straight from the registry so docs
  cannot drift).
- **v0.16** — context-menu phases 14-16 (attachment menu, fork-only
  `message.regenerate`, pending-operations floating card),
  auto-register `Write` image artifacts for inline display, and
  tool-output linkifier (clickable URLs and file paths in tool
  output).
- **v0.17** — Bearings-owned `mcp__bearings__bash` with intra-call
  line streaming so long shell commands stream output to the terminal
  pane live instead of dumping one block on exit, and a refactor
  pass on `Conversation.svelte` (2023 → 389 lines into 3
  subcomponents + 3 controllers).

## Features

### Streaming Claude agent sessions

Token deltas, thinking blocks, tool-call start/end, message-complete
cost. Run via `claude-agent-sdk`; pipe over WebSocket to the frontend.

### Tags, tag memories, tag defaults (v0.2)

- **Tags** — global, named, pinned or unpinned, with a `sort_order`.
  Many-to-many with sessions. Attach at create time or through the
  session edit modal.
- **Tag memories** — short markdown per tag, injected into the system
  prompt whenever the tag is on a session. Edited in the TagEdit
  modal (hover-reveal ✎ on each sidebar tag row). Precedence
  follows sidebar sort order — **the tag lower in the sort wins**
  when memories conflict. `tag_memories` table, `ON DELETE CASCADE`
  keyed to the tag.
- **Tag defaults** — optional `default_working_dir` and
  `default_model` per tag. The new-session form pre-fills from the
  highest-precedence attached tag. Pin a `bearings` tag with
  `default_working_dir = ~/Projects/Bearings` and it behaves like a
  "project" in any tool that has them.
- **Every session has ≥1 tag.** The new-session form gates on this;
  the API rejects `tag_ids: []` with a 400.
- **Layered system prompt** — base → tag memories (sort order) →
  session instructions. Inspectable in the Inspector Context tab
  with per-layer content + approximate token counts via
  `GET /api/sessions/{id}/system_prompt`.

### Severity tags + Finder-click filter (v0.7)

Every session also carries exactly one severity tag — Blocker,
Critical, Medium, Low, or Quality of Life — seeded by migration
0021 and enforced at the app layer. The sidebar splits into a
General section and a Severity section, each with shield medallions
painted from the tag's `color`. Click semantics mirror macOS
Finder: plain click single-selects, Shift-click toggles within the
group, solo re-click clears. Severity is OR-within-group on the
wire; general is OR-within-group as of v0.10; the two groups AND
together. A virtual "No severity" row catches sessions orphaned by
a deleted severity tag.

### Session lifecycle

Session CRUD, rename, delete, JSON import/export (single + bulk
drag-drop), Enter-to-send / Shift+Enter newline, Stop button (SDK
`interrupt()` with a 3-second undo toast before the WS frame fires),
⌘/Ctrl+K sidebar search with match highlighting, `?` cheat-sheet
modal, message pagination. Per-session `max_budget_usd` cap enforced
via `ClaudeAgentOptions`; running total cost stored on the session
and rendered with amber/rose pressure coloring at ≥80% / ≥100%.
Per-session `session_instructions` override edited inline in the
Inspector Context tab — always the last-wins layer of the prompt.

The sidebar updates in sub-second time via a server-wide
`/ws/sessions` broadcast channel (v0.7.0); a 3-second `softRefresh`
poll runs alongside as a belt-and-suspenders reconcile. Sessions
running in another tab — or sessions already active when the tab
loaded — surface their state changes (cost bumps, completion,
rename) without a manual reload.

### Right-click everywhere (v0.9 → v0.16)

Registry-driven context menus across the app: sessions, tags, tag
chips, messages, tool calls, code blocks, links, attachments,
pending operations. Every action is keyed by a public ID and pinned
by snapshot tests (renames must go through `Action.aliases` with a
deprecation warning). `Ctrl+Shift+P` opens a flat command palette
that reuses the same registry. `Ctrl+Shift+right-click` passes
through to the browser's native menu.

Customize via `~/.config/bearings/menus.toml` — pin actions to the
top of a target's menu, hide the ones you never want, rebind chord
shortcuts. Loaded once at server start; restart to apply. The cheat
sheet enumerates everything you've bound under "Your shortcuts
(menus.toml)" so you can see what actually wired up. See
`docs/menus-toml.md` for the full action-ID reference.

Touch + coarse-pointer support: 500ms long-press opens the menu as a
viewport-anchored bottom sheet with 44px touch targets when the
viewport reports `pointer: coarse`. Desktop-mouse path is untouched.

### Sub-session primitives (v0.9.2)

- **Checkpoints + fork.** Right-click any message in the
  `CheckpointGutter` strip to anchor it; right-click an anchor →
  Fork spawns a fresh session branched from that message. The
  source session is untouched, so attempts compare side-by-side.
- **Session templates.** Save a session's working_dir / model /
  instructions / tag set as a template (`📋` picker in the sidebar
  header); instantiate with optional per-call overrides.
- **Bulk multi-select.** Cmd/Ctrl-click toggle and Shift-click
  range on sidebar rows; right-click for delete / close / reopen /
  pin / unpin / tag / untag in one dispatch (`POST
  /api/sessions/bulk` returns `{succeeded, failed}` per id so a
  stale id doesn't 400 the whole batch).
- **Message pin / hide-from-context.** Pinned messages always reach
  the agent regardless of the context-trim window; hidden messages
  stay in the UI but are excluded from the turn payload.
- **Regenerate from message (fork-only, v0.16).** Walks back to the
  user-turn boundary, copies the prefix into a fresh session,
  inherits parent tags + `permission_mode`, seeds the boundary
  prompt into the new composer for a fresh `sdk_session_id` re-run.
  Title prefix `↳ regen: `.

### Checklists — structured work that outlives any one conversation

**This is one of the features that makes Bearings worth running.** A
checklist in Bearings is not a markdown TODO buried in a chat; it is a
first-class **session kind** (`kind="checklist"`) that holds a structured
tree of items with notes, nesting, and links to paired chat sessions. It
survives compactions, restarts, forks, and the heat death of any single
context window.

**What you get:**

- Persistent item tree, rendered live in the right pane. Two levels of
  nesting in practice (top-level area + child step). Auto-cascade closes
  parents when all children check off (v0.9).
- Embedded `ChecklistChat` panel above the list — talk to Claude about
  the checklist itself; the prompt assembler injects the title, notes,
  and current item tree with `[x]`/`[ ]` glyphs into every turn so the
  agent stays grounded in *what's actually done*.
- **Paired chat sessions per item.** Right-click → *Open paired chat*
  spawns a dedicated chat-kind session linked back to the item. Each
  item's work has its own scrollback; the checklist is the index.
- **Fix-and-return.** Drop into a paired chat, do the work, check the
  item — Bearings tracks completion across the link.
- **Tour mode + autonomous run.** Hit `▶︎ Run` to walk the items in
  order. The auto-driver opens each linked chat, drives it to its
  Done-when criterion, marks the item, and moves on. Stop anytime.
- **Severity tags + Finder-click filter** apply to checklist sessions
  too. Pin a `[Roadmap]` master to the top of your sidebar.

**How to create one:**

In the UI: sidebar `📋 New checklist` (or `Ctrl+Shift+P → New
checklist`). Pick at least one project tag and one severity tag.

Via REST (every Bearings install exposes this):

```bash
# 1. Create the master
curl -sS -X POST http://127.0.0.1:8787/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"title":"[Roadmap] Q3","working_dir":"/abs/path","model":"claude-opus-4-7","tag_ids":[2,9],"kind":"checklist"}'

# 2. Add an item
curl -sS -X POST http://127.0.0.1:8787/api/sessions/<id>/checklist/items \
  -H 'Content-Type: application/json' \
  -d '{"label":"Add CONTRIBUTING.md","notes":"Files: CONTRIBUTING.md (new). Done when: covers setup/test/style + linked from README."}'
```

Full reference — schema, REST endpoints, the §36 format mapping, the
"audit-master + N linked chat sessions" recipe, best practices for
writing items — lives in [`docs/checklists.md`](docs/checklists.md).

**LiveTodos vs checklist sessions vs `TODO.md` — three surfaces, one
discipline:**

| Surface | What it is | Lifetime |
|---|---|---|
| **Checklist session** | Persistent structured tree, optionally linked to chats. Human + API editable. | Forever, across restarts. |
| **`LiveTodos` widget** (v0.8) | Sticky card at the top of the Conversation pane mirroring the agent's in-conversation `TodoWrite` list. Tri-state glyphs ○/●/✓. Read-only from your side. | Per-conversation, ephemeral. |
| **Cross-project `TODO.md`** | Markdown at each project root for deferred work. Surfaced and lint-checked by the `bearings todo` CLI (v0.13). | Forever, in git. |

All three coexist. Reach for a checklist session when you need
structured work tracking that outlives any single chat.

### `bearings todo` CLI (v0.13)

First layer of the cross-project `TODO.md` discipline enforcement
plan in `~/.claude/specs/todo-discipline-v1.md`:

- `bearings todo open` — list every Open / In Progress entry from
  every `TODO.md` in scope, sorted by Logged date.
- `bearings todo check` — lint for §1.3 schema violations and
  staleness (E001-E008 hard rules, W101/W102 soft rules).
- `bearings todo add "<title>"` — append a properly-formatted stub
  that round-trips through the parser.
- `bearings todo recent` — entries that changed in the last N days
  via `git log -p` walked newest-commit-first; non-git fallback
  uses `Logged:` date.

JSON output (`--format json`) is stable so a `UserPromptSubmit`
hook can pipe findings into `additionalContext` once that layer
ships.

### Themes & keyboard shortcuts v1 (v0.14, v0.15)

- **Themes** — Settings picker bound to `preferences.theme`
  (Midnight Glass / Default / Paper Light), no-flash boot script in
  `app.html` reads `bearings:preferences-cache` from localStorage
  and pins the theme before first paint, semantic alias layer in
  `tokens.css` (`--color-bg-root`, `--color-text-primary`, etc.) so
  components using raw shade utilities flip on theme change without
  rewrites, variable-driven shiki for instant code-block reflow.
- **Keyboard shortcuts** — config-driven binding registry; cheat
  sheet renders directly from `groupedBindings()` so docs cannot
  drift from the wiring. v1 subset: `c` / `Shift+C` (new chat),
  `t` (template picker), `j` / `k` (next / prev session),
  `Alt+1..9` (jump to Nth session), `Alt+[` / `Alt+]` (modifier
  variants that fire even with focus in an input), `Esc` (cascade:
  palette → overlay → blur input), `?` (cheat sheet, ignored when
  an input has focus), `Ctrl+Shift+P` (palette). Letters compare
  against `e.code` so non-US layouts and AltGr remaps still match.

### Context-cost survival kit (v0.12)

When a long-lived session runs hot, Bearings layers in mitigations
beyond the SDK's own compactor:

- **Tool-output cap advisory.** Outputs over
  `agent.tool_output_cap_chars` (default 8000) trigger a PostToolUse
  hook that attaches an `additionalContext` advisory carrying the
  `tool_use_id` and a retrieval hint, steering the model to
  summarize + use `bearings__get_tool_output` instead of replaying
  bytes.
- **In-process MCP server.** `bearings__get_tool_output(tool_use_id)`
  pulls any prior tool call's full persisted output out of SQLite
  with a 200 KB return cap. Session-scoped — refuses cross-session
  reads.
- **PreCompact steering.** Hands the CLI's compactor a
  `customInstructions` block telling it to preserve research-dense
  turns and unanswered questions verbatim while dropping duplicate
  Reads and failed Bash retries.
- **`researcher` sub-agent (opt-in).** Read-only allowlist
  (Read / Grep / Glob / Bash), runs in isolated context; only its
  summary reaches the parent turn so a parent at 60% pressure can
  delegate a 20-file survey without blowing its own window. Default
  off until the researcher prompt has more iteration on it.
- **Context-pressure injection.** When the last persisted
  `last_context_pct` ≥ 50, the user's prompt is prefixed with a
  `<context-pressure pct=… tokens=… max=…>` block carrying
  band-specific steering (≥50% prefer researcher, ≥70% recommend
  checkpoint, ≥85% surface to user and recommend fork).

### Directory Context System (v0.6)

`.bearings/` on-disk manifest per directory: any session landing in
a tracked directory can read it and know what's happening here
without relying on ephemeral chat memory. Five Pydantic v2 schemas
(`Manifest`, `State`, `EnvironmentBlock`, `Pending`,
`PendingOperation`, `HistoryEntry`) with field caps so a malicious
or hand-edited file can't blow the per-turn prompt budget. Atomic
TOML IO via tempfile + `os.replace` + `fsync` + `fcntl.flock`;
corrupt files are renamed to `corrupted-…` with a `.reason`
sidecar and the next session re-onboards cleanly. `history.jsonl`
append-only with line-atomic writes (200-char summary cap keeps
each line under `PIPE_BUF`).

### Reliability — replay on restart (v0.6.1)

When `bearings.service` is stopped mid-turn (SIGTERM, crash, deploy)
the user's submitted prompt was previously orphaned silently — no
follower, no recovery. Now: the runner scans for orphan prompts on
boot once before its first `queue.get()`, marks
`messages.replay_attempted_at` (fail-closed against replay loops),
re-enqueues the prompt, and emits a `turn_replayed` wire event so
the UI shows "resuming prompt from previous session" instead of
silently starting work the user didn't just submit.

### Performance (v0.12.2)

- **Reducer-owned `turns` / `timeline` / `audits` arrays.** Per-WS-
  event paths mutate the existing tail Turn in place instead of
  rebuilding the whole array; cuts the streaming hot path from
  227 rebuilds per tool-heavy turn to zero.
- **Timeline virtualization above 200 items.** `VirtualItem.svelte`
  lazy-mounts each entry via IntersectionObserver +
  ResizeObserver; off-screen items render as a `min-height`
  placeholder. Streaming tail and bottom-30 warm band stay
  force-mounted so auto-scroll lands on real DOM.

### Discoverability

- `?` cheat sheet modal renders directly from the keyboard-shortcut
  registry plus a Context Menus group documenting right-click /
  Shift+right-click / Ctrl+Shift+right-click / long-press
  conventions, plus a dynamic "Your shortcuts (menus.toml)" section
  enumerating bindings with resolved action labels.
- Inspector Context tab shows the layered system prompt — base →
  tag memories (in sort order) → checklist overview (if applicable)
  → session instructions — with per-layer content + approximate
  token counts via `GET /api/sessions/{id}/system_prompt`.
- Tool-output linkifier (v0.16.2): URLs and file paths in tool
  output are rendered as clickable `<a href>` anchors with
  `target="_blank" rel="noopener noreferrer"`. Right-click an
  anchor opens the link menu (`link.open_new_tab`,
  `link.copy_url`, `link.open_in.editor`) instead of the
  tool-call menu.
- File Display Phase 1 (v0.16.1): when a `Write` tool produces an
  image-MIME file under `[artifacts] serve_roots`, the runner
  auto-registers an artifact row and injects
  `![filename](/api/artifacts/{id})` into the assistant's reply so
  the image renders inline without a reload.
- **Vault** — read-only markdown surface under `/api/vault/*` that
  aggregates planning docs (`~/.claude/plans/`) and per-project
  `TODO.md` files into a browsable index inside the Bearings UI.
  Paths are expanded at request time. The configured `plan_roots` /
  `todo_globs` ARE the allowlist — `/api/vault/doc` only returns
  bytes for paths the scan currently surfaces; adding or removing
  patterns is equivalent to granting / revoking read exposure
  (treat like `fs.allow_root`).

### Infrastructure

- Opt-in bearer-token auth (`auth.token`) across REST + WS + CLI +
  frontend AuthGate modal; 401/4401 flips the store back to `invalid`.
- Prometheus `/metrics` (sessions, messages, tool calls, WS events,
  active connections, checkpoints, bulk ops, templates) + JSON
  history export / daily / search routes.
- CLI subcommands: `bearings serve | init [--profile NAME] | send |
  todo {open,check,add,recent}`. `init --profile
  {safe|workstation|power-user}` materializes the preset into
  `config.toml` and prints the active gate audit. `send` supports
  `--format=pretty` for human-readable output and `--token` for
  authenticated servers.

## Threat model

Bearings is built for a **single-operator localhost workstation**.
The whole permission-profile system above exists because the
default agent surface is what makes the app useful AND what makes
it dangerous on a shared box.

### What running Bearings exposes

- **Full Claude agent surface.** File system access (Read / Write /
  Edit / Bash via the SDK), tool use, MCP server invocation, hook
  scripts. Every Claude Code capability. By default Bearings
  inherits your `~/.claude/` settings, MCP server registrations,
  and hook scripts (`agent.inherit_mcp_servers`,
  `agent.inherit_hooks` — both default `true`).
- **`bypassPermissions` mode is reachable** by default
  (`agent.allow_bypass_permissions = true`). Sessions opened in
  bypass mode skip per-tool confirmation entirely.
- **`working_dir` defaults to `~/`** unless overridden by a tag
  default or a per-session value. The `safe` profile narrows this
  to a per-session sandbox under
  `~/.local/share/bearings/workspaces/<id>` — every other profile
  gives the agent your home directory.
- **No auth gate by default.** `auth.enabled = false`. The server
  binds to `127.0.0.1` and trusts every loopback request.

### Why loopback-only is not a substitute for auth

If your machine is shared, multi-user, or running other localhost
services that proxy or fetch URLs, "loopback-only" buys you
nothing:

- Any other process on the box (or any other user account, on a
  shared host) can `curl http://127.0.0.1:8787` and submit
  prompts, read history, fork sessions, escalate to
  `bypassPermissions`.
- A browser open to *any* page can hit
  `http://127.0.0.1:8787/api/sessions` via fetch; CORS protects
  the response from the page reading it, but a CSRF-style
  POST with an empty body still triggers state changes if the
  endpoint is unauth'd. Bearings does not currently rely on a
  CSRF token — auth is the gate.
- A reverse-proxy or DNS-rebinding attack on the loopback
  binding bypasses the literal-127.0.0.1 check entirely.

If you are not the only user of this machine, set
`auth.enabled = true` and `auth.token = <random>` (or use
`bearings init --profile workstation` which generates one for
you).

### What each profile defends against

| profile         | defends against                                                                       | does NOT defend against                                                                 |
|-----------------|---------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| `safe`          | shared-host neighbors, browser CSRF, accidental writes outside the sandbox            | a privileged attacker on the same box, supply-chain compromise of an inherited tool     |
| `workstation`   | shared-host neighbors, browser CSRF, accidental escalation to `bypassPermissions`     | filesystem damage from a Bash invocation the operator approves; supply-chain compromise |
| `power-user`    | (nothing — you have set every gate to permissive on purpose)                          | (everything above, plus everything else)                                                |

`power-user` is appropriate when you are the only user on the
machine, the network is trusted, and you want zero-friction tool
use. `safe` is the install-time default precisely because it is
the only posture safe to recommend for someone who hasn't read
this section.

### What Bearings does NOT try to be

- **Not a multi-user product.** There is no per-user permission
  model, no audit log keyed to a user identity, no session
  isolation across operators. Every authenticated request acts as
  the single operator behind the token.
- **Not a hosted SaaS.** Designed to bind to loopback on your
  workstation. Running it on a public IP or behind a public
  reverse proxy is unsupported; the threat model assumptions above
  do not survive that change.
- **Not a sandbox for adversarial prompts.** If you paste a prompt
  from an untrusted source into the composer with `bypassPermissions`
  enabled, you are running arbitrary code as yourself. The
  permission-profile system mitigates the easy-mode attacks; it
  does not turn the agent surface into a safe playground.

## Privacy / Telemetry

Bearings collects **nothing**. No analytics, no crash reporting, no
remote logging, no usage pings. Every session, message, tool output,
cost, tag, attachment, and counter stays on the machine running the
server (under `~/.local/share/bearings/`). The optional Prometheus
`/metrics` endpoint exposes **local** counters for a scraper you run
yourself; it makes no outbound calls. Full posture, the
versioned-acknowledgment commitment for any future opt-in surface,
and the bug-reporting redaction note live in
[`TELEMETRY.md`](TELEMETRY.md).

## Upgrading from v0.1

v0.2 migrations (`0006_tag_primitives.sql` through
`0009_tag_defaults.sql`) are additive except for v0.2.9's projects
teardown. Existing v0.1 sessions survive untouched *except* that
v0.2.9 wiped the sessions table — this was deliberate, done before
v0.2 had any production data. A fresh v0.2 install will auto-apply
every migration in sequence.

New sessions require ≥1 tag going forward. Existing tag-less
sessions (if any were restored from a v0.1 export after v0.2.0
shipped) are still readable but can't be created that way anymore
via the HTTP API.

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

The frontend build writes static assets into `src/bearings/web/dist/`, which
FastAPI mounts at `/`.

## Run

```bash
uv run bearings serve
# then open http://127.0.0.1:8787
```

Health probe:

```bash
curl -s http://127.0.0.1:8787/api/health
```

## Service install

```bash
install -Dm644 config/bearings.service ~/.config/systemd/user/bearings.service
systemctl --user daemon-reload
systemctl --user enable --now bearings.service
```

## Config

`~/.config/bearings/config.toml`. Defaults are baked in; override only the
keys you need.

| Section    | Key                          | Default                          | Purpose                                              |
|------------|------------------------------|----------------------------------|------------------------------------------------------|
| `profile`  | `name`                       | *(unset)*                        | Active permission profile (info only — set by `init`)|
| `profile`  | `show_banner`                | `true`                           | Print gate audit on `serve` startup                  |
| `server`   | `host`                       | `127.0.0.1`                      | Bind address                                         |
| `server`   | `port`                       | `8787`                           | Bind port                                            |
| `auth`     | `enabled`                    | `false`                          | Gate REST + WS behind bearer                         |
| `auth`     | `token`                      | *(unset)*                        | Shared secret when `enabled`                         |
| `agent`    | `working_dir`                | `~/`                             | Legacy default cwd when `workspace_root` unset       |
| `agent`    | `workspace_root`             | *(unset)*                        | Per-session sandbox parent (sets `safe` posture)     |
| `agent`    | `model`                      | `claude-opus-4-7`                | Default model                                        |
| `agent`    | `default_max_budget_usd`     | *(unset)*                        | Per-session spend cap when caller doesn't pass one   |
| `agent`    | `allow_bypass_permissions`   | `true`                           | Allow header selector to escalate to `bypassPermissions` |
| `agent`    | `setting_sources`            | *(unset)*                        | SDK settings inheritance — `[]` = none, `null` = SDK default |
| `agent`    | `inherit_mcp_servers`        | `true`                           | Pass through `~/.claude/` MCP server registrations   |
| `agent`    | `inherit_hooks`              | `true`                           | Pass through `~/.claude/` hook scripts               |
| `agent`    | `tool_output_cap_chars`      | `8000`                           | PostToolUse advisory threshold (v0.12)               |
| `agent`    | `enable_bearings_mcp`        | `true`                           | Register `bearings__get_tool_output` MCP (v0.12)     |
| `agent`    | `enable_precompact_steering` | `true`                           | Hand the compactor a custom-instructions block (v0.12) |
| `agent`    | `enable_researcher_subagent` | `false`                          | Register the read-only `researcher` sub-agent (v0.12)|
| `commands` | `scope`                      | `"all"`                          | Slash-command palette scope (`all` / `user` / `project`) |
| `fs`       | `allow_root`                 | `~/`                             | `/api/fs/list` clamp                                 |
| `runner`   | `idle_ttl_seconds`           | `900`                            | Idle runner reaper threshold                         |
| `storage`  | `db_path`                    | `~/.local/share/bearings/db.sqlite` | Persistence                                       |
| `metrics`  | `enabled`                    | `false`                          | Prometheus `/metrics` endpoint                       |
| `uploads`  | `allowed_mime_types`         | *(empty list)*                   | Allowlist; empty = legacy denylist behavior          |
| `uploads`  | `allowed_extensions`         | *(empty list)*                   | Per-extension fallback for `application/octet-stream`|
| `uploads`  | `max_per_turn_count`         | `10`                             | Max attachments per submitted turn                   |
| `uploads`  | `max_per_turn_bytes`         | `52428800`                       | Per-turn byte cap (default 50 MB)                    |
| `artifacts`| `serve_roots`                | *(unset)*                        | Roots under which Write outputs auto-register (v0.16.1) |
| `shell`    | `editor_command`             | *(unset)*                        | Command for `link.open_in.editor` / `attachment.open_in.editor` |
| `shell`    | `terminal_command`           | *(unset)*                        | Command dispatched by `/api/shell/open` terminal verb |
| `shell`    | `file_explorer_command`      | *(unset)*                        | Command for `attachment.open_in.file_explorer`       |

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for prerequisites, setup,
the six quality-gate commands, commit conventions, the PR process,
and code-style rules. Project-specific overlays (function/file size
caps, `mypy` strict, the brownfield discipline) live in
[`CLAUDE.md`](CLAUDE.md).

## License

MIT. See `LICENSE`.
