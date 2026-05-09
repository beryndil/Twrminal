# Getting started

This guide takes a fresh checkout from "I just cloned this" to
"I have a chat session running and I know where to look next."

If you only read one page of the user docs, this is it.

## What you can do here

* [Install Bearings from the repo](#1-install)
* [Run the server for the first time](#2-run-the-server)
* [Open the web UI](#3-open-the-web-ui)
* [Create your first chat session](#4-create-your-first-chat-session)
* [Send a message and watch the agent respond](#5-send-a-message)
* [Find the inspector and read what the agent is doing](#6-find-the-inspector)
* [Stop a turn (and undo the stop)](#7-stop-a-turn)
* [Where to go next](#where-to-go-next)

---

## Walkthrough

### 1. Install

Bearings is a Python package + a committed SvelteKit static bundle.
A fresh clone needs no Node toolchain to serve the UI.

```bash
git clone <repo-url> bearings
cd bearings
scripts/setup-worktree.sh    # idempotent — wires hooks, runs uv sync
```

`scripts/setup-worktree.sh` sets `core.hooksPath` for this worktree
to `.githooks-v1/` (so it does not trample any sibling worktree's
hooks) and runs `uv sync --extra dev` to materialise the venv.

Verify the install:

```bash
.venv/bin/bearings --version
```

Should print `bearings <version>` and exit `0`.

### 2. Run the server

```bash
.venv/bin/bearings serve --host 127.0.0.1 --port 8788
```

You'll see a banner with the active permission profile and a
per-gate audit table (auth on/off, bypassPermissions allowed, MCP
inheritance, hooks inheritance, working-dir defaults, FS picker
root, commands palette scope, idle TTL, bind address).

The server listens on `127.0.0.1:8788` by default, persists state
under `~/.local/share/bearings-v1/`, and serves the UI bundle from
`src/bearings/web/dist/` (committed in the repo — no build step
needed).

If port 8788 is taken (Bearings v0.17.x runs on 8787, v1 on 8788
— they can coexist), pass `--port` to override.

For the full `bearings serve` failure modes — bind/auth interlock
refusals, port-in-use messages, profile auditing — see
[../behavior/bearings-cli.md](../behavior/bearings-cli.md)
§"`bearings serve`".

### 3. Open the web UI

Navigate to `http://127.0.0.1:8788/` in any browser, or use the
helper:

```bash
.venv/bin/bearings window
```

`bearings window` autodetects Firefox (preferred) or any Chromium
browser, opens the UI as a chromeless application window
(`--app=URL` for Chromium families; `--new-window` + Bearings'
bundled SSB userChrome for Firefox), and detaches.

When the UI loads you'll see:

* a **sidebar** on the left (empty on first run);
* a **primary nav rail** above the session list with entries:
  Sessions, Memories, Vault, Analytics, Tags, Settings;
* a **conversation pane** in the centre (empty until a session is
  selected);
* an **inspector drawer** on the right (toggled with the chevron
  button or the keyboard shortcut documented in
  [keyboard-shortcuts](../behavior/keyboard-shortcuts.md)).

### 4. Create your first chat session

Click the **+** button at the top of the sidebar (or press the
new-session keyboard shortcut). The new-session dialog opens.

Required fields:

* **At least one tag.** Tags are partitioned into three classes —
  `project` (at most one), `severity` (at most one), `general`
  (any number). Type a name in the inline filter and press Enter
  to create-and-attach a new tag, or click an existing chip in the
  Available column. See [sessions guide §Creating a session](sessions.md#creating-a-session).
* **Working directory.** Free-text path or browse via the FS picker.
* **Routing selection.** Defaults populate from the most-recently-
  used session (first-time users get the per-instance defaults).
  You can override the executor model, advisor model, advisor
  `max_uses`, or effort level inline. The dialog renders a live
  **routing-preview line** ("Routed from tag rule …") that updates
  as you change tags or message content.
* **First message body.**

Pressing **Start Session** creates the row, attaches the tags, sends
the first message, and opens the new chat in the conversation pane.

> The dialog also shows a **quota bar pair** (overall + Sonnet) at
> the top. The bars turn yellow at 80% and red at 95%. If the quota
> guard would downgrade the routed choice, a yellow banner appears:
> *"Routing downgraded to Sonnet (overall quota at NN%). [Use Opus
> anyway]"*. Clicking the override link records the override for
> analytics. See the [routing guide](routing.md) for the full
> picture.

### 5. Send a message

The composer at the bottom of the conversation pane is a multi-
line text area. Enter sends; Shift+Enter inserts a newline.

While the agent is responding, you'll see:

* The **assistant bubble** streams in tokens as they arrive.
* A **tool-work drawer** (collapsible `<details>`) shows each tool
  call: tool name, a live elapsed-time readout, a chevron to expand
  the streamed output. Failed calls render in red.
* A **routing badge** appears in the assistant bubble's corner:
  `Sonnet`, `Sonnet → Opus×2`, `Haiku → Opus×1`, `Opus xhigh`. Hover
  reveals the matched rule and reason.
* Each tool call's output streams in as it arrives — see
  [../behavior/tool-output-streaming.md](../behavior/tool-output-streaming.md)
  for the soft-cap / hard-cap / scrollback behaviour.

When the turn finishes, the cost-USD readout in the header
updates, and the sidebar pip transitions through colours:

| Pip | Meaning |
|---|---|
| Red, flashing | Agent parked waiting for input (tool approval / `AskUserQuestion`) |
| Orange, flashing | Agent turn actively running |
| Green, solid | Session has new output you have not opened |
| (none) | Idle, caught up |

Selecting the row marks the session viewed (the green pip clears).

### 6. Find the inspector

Click the chevron at the right edge of the conversation pane (or
use the keyboard shortcut). Eight tabs in render order:

| Tab | What it shows |
|---|---|
| **Agent** | Executor model, permission mode, working dir, budget, total cost, message count. |
| **Context** | Last-turn context-window pressure, token count, max; full title + description. |
| **Instructions** | Per-session instructions + the assembled system prompt (per-tag `CLAUDE.md` layers + tag memories + directory brief). |
| **Files** | Every distinct file path the agent has touched (Read / Write / Edit / NotebookEdit / Grep). |
| **Changes** | Chronological list of WRITE-side tool calls with excerpts (Created / Edited / Notebook-edited). |
| **Metrics** | Per-session token totals + tool-call counters (Total / Running / Failed / elapsed). |
| **Routing** | Per-message routing decision chain: source, matched rule, executor + advisor, quota state, "Why this model?" expander. |
| **Usage** | App-wide rollups: 7-day quota headroom, by-model, advisor effectiveness, rules to review. |

The active tab is sticky across reloads via `localStorage`. Full
tab walkthrough: [inspector guide](inspector.md). (The repo
README still references a five-tab layout — that text is ahead of
this guide; the inspector ships eight tabs in v1.0.0.)

### 7. Stop a turn

While a turn is in flight the composer area shows a **■ Stop**
button. Click it.

Stop **does not fire immediately** — it arms a 3-second grace
window. The button is replaced (same DOM slot, no layout shift) by
a countdown chip *"Stopping 3s"* and an **Undo** button.

* Click **Undo** within the window → the pending stop is
  cancelled. No `POST /stop` is issued; the turn continues.
* Let the window expire → a single `POST /api/sessions/{id}/stop`
  fires. The agent interrupts at the next safe boundary; the
  partial assistant bubble is preserved as-is.

Switching sessions while a stop is pending **commits** the stop on
the original session (the safer default — you already asked for it).

The grace duration and tick cadence are `STOP_UNDO_GRACE_MS` /
`STOP_UNDO_TICK_MS` in `frontend/src/lib/config.ts`. See
[../behavior/chat.md §Stopping or interrupting a turn](../behavior/chat.md#stopping-or-interrupting-a-turn).

---

## Where to go next

You now know how to install, run, create a session, send a message,
read the inspector, and stop a turn cleanly. The next pages take
each surface deeper:

| If you want to … | Read |
|---|---|
| Understand what a session, tag, paired-chat, or memory actually is | [../concepts.md](../concepts.md) |
| See every per-session action in the sidebar (rename, archive, fork, merge, duplicate, export, import, drag-drop import) | [sessions.md](sessions.md) |
| Configure routing rules per tag, override mid-conversation, read override-rate analytics | [routing.md](routing.md) |
| Drive the inspector drawer | [inspector.md](inspector.md) |
| Walk a checklist with the autonomous driver | [checklists.md](checklists.md) and [paired-chats.md](paired-chats.md) |
| Add tag-keyed system-prompt overlays | [vault-and-memories.md](vault-and-memories.md) |
| Read the analytics dashboard | [analytics.md](analytics.md) |
| Tweak themes, keybindings, preferences, tags | [settings.md](settings.md) |
| Run Bearings from the terminal (`serve` / `gc` / `todo`) | [cli.md](cli.md) |
| Curl the HTTP API directly | [../api.md](../api.md) |

If something does not match what the UI is doing — that's a doc
bug. The behavior reference lives at
[../behavior/](../behavior/); the implementation reference at
[../architecture-v1.md](../architecture-v1.md). File an issue
through the megaphone glyph in the conversation header.

---

## See also

* [Concepts overview](../concepts.md) — the connected mental model.
* [behavior/chat.md](../behavior/chat.md) — full conversation-pane
  observable behavior.
* [behavior/sessions.md](../behavior/sessions.md) — session-level
  actions beyond the conversation.
* [behavior/bearings-cli.md](../behavior/bearings-cli.md) — every
  CLI subcommand's stdout/stderr contract.
* [behavior/keyboard-shortcuts.md](../behavior/keyboard-shortcuts.md)
  — full keybinding registry (also reachable via `?` in the UI).
