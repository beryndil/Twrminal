# `menus.toml` — Context-Menu Customization

Bearings ships a right-click menu on every significant surface —
session rows, message bubbles, tags, tag chips, tool calls, code
blocks, links, checkpoints, and multi-selection. The defaults are
opinionated; `menus.toml` lets you tailor them per target type without
forking the codebase.

- **File path:** `~/.config/bearings/menus.toml` (XDG config home)
- **Loaded:** once at server start
- **Reloads:** require a server restart (`systemctl --user restart
  bearings`). No hot reload in the 0.9.x train.
- **Soft-fail:** a missing, empty, or malformed file logs a warning
  and falls back to the built-in defaults. Typos never brick the UI.

---

## What you can override

Three axes per target type:

1. **`pinned`** — action IDs that should float to the top of their
   section in the listed order. Useful for promoting the
   three-to-five actions you actually reach for.
2. **`hidden`** — action IDs that should never appear in the
   right-click menu. Hidden actions remain reachable via the
   **Ctrl+Shift+P** command palette, so you can still invoke them
   occasionally without restoring them to the menu.
3. **`shortcuts`** — `{action_id = "key_chord"}` rebindings for the
   keyboard FSM. The `CheatSheet` (press `?`) reflects the rebinding.

Each axis is independent. You can pin an action without hiding
anything else; you can hide without pinning; etc.

## Example

```toml
# ~/.config/bearings/menus.toml

[session]
# Float the two actions I use ten times an hour to the top of the
# session menu. The `create` and `organize` sections each get the
# pinned ID first, then the rest of the section in declaration order.
pinned = [
  "session.pin",
  "session.save_as_template",
]
# I never use share links.
hidden = ["session.copy_share_link"]

[session.shortcuts]
"session.delete" = "ctrl+shift+d"

[message]
pinned = ["message.copy_content"]

[checkpoint]
pinned = ["checkpoint.fork"]
```

Tables are keyed on the target-type discriminator
(`session`, `message`, `tag`, `tag_chip`, `tool_call`, `code_block`,
`link`, `checkpoint`, `multi_select`). Unknown target names log a
warning and are ignored.

Unknown action IDs inside a known target are also ignored silently —
that lets a `menus.toml` written against a newer Bearings keep working
when you downgrade, and keeps typos from disabling the whole file.

---

## Action ID reference

Action IDs are a **public API**. Once shipped, they are only renamed
via the `aliases` field on the action definition with a deprecation
warning in at least one release train. Safe to hard-code in your
`menus.toml`.

Sections are the canonical ordering buckets
(`primary → navigate → create → edit → view → copy → organize →
destructive`). Pinned reordering stays within a single section — it
doesn't let you move `session.delete` out of `destructive`.

### `session` — Sidebar row / conversation header

| ID | Label | Section | Flags | Notes |
|---|---|---|---|---|
| `session.open_in.editor` | Open in editor | navigate | — | Requires `shell.editor_command` in `config.toml` |
| `session.open_in.terminal` | Open terminal here | navigate | — | |
| `session.open_in.file_explorer` | Open in file explorer | navigate | — | |
| `session.open_in.git_gui` | Open in git GUI | navigate | — | |
| `session.open_in.claude_cli` | Open Claude CLI | navigate | — | |
| `session.duplicate` | Duplicate | create | — | Disabled — lands later in the 0.9.x train |
| `session.save_as_template` | Save as template… | create | — | |
| `session.fork.from_last_message` | Fork from last message | create | advanced | |
| `session.change_model` | Change model for continuation ▸ | edit | — | Submenu parent |
| `session.change_model.claude-opus-4-7` | claude-opus-4-7 | edit | — | Submenu leaf |
| `session.change_model.claude-sonnet-4-6` | claude-sonnet-4-6 | edit | — | Submenu leaf |
| `session.change_model.claude-haiku-4-5-20251001` | claude-haiku-4-5-20251001 | edit | — | Submenu leaf |
| `session.copy_id` | Copy session ID | copy | advanced | |
| `session.copy_title` | Copy session title | copy | — | |
| `session.copy_share_link` | Copy share link | copy | advanced | Disabled until v0.10.x |
| `session.pin` | Pin session | organize | — | Hidden when already pinned |
| `session.unpin` | Unpin session | organize | — | Hidden when not pinned |
| `session.archive` | Archive session | organize | — | Alias: `session.close` |
| `session.reopen` | Reopen session | organize | — | |
| `session.delete` | Delete session | destructive | destructive | Requires confirm |

### `message` — User / assistant message bubble

| ID | Label | Section | Flags | Notes |
|---|---|---|---|---|
| `message.jump_to_turn` | Scroll into view | navigate | — | |
| `message.fork.from_here` | Fork from this message | create | advanced | Auto-creates checkpoint |
| `message.copy_content` | Copy message text | copy | — | |
| `message.copy_as_markdown` | Copy as Markdown | copy | advanced | |
| `message.copy_id` | Copy message ID | copy | advanced | |
| `message.pin` | Pin to turn header | organize | — | |
| `message.hide_from_context` | Hide from context window | organize | advanced | |
| `message.move_to_session` | Move to session… | organize | — | Opens picker |
| `message.split_here` | Split here… | organize | — | Opens picker |
| `message.delete` | Delete message | destructive | destructive, advanced | Disabled — single-message delete lands later |

### `tag` — Sidebar tag row

| ID | Label | Section | Flags | Notes |
|---|---|---|---|---|
| `tag.edit` | Edit tag… | edit | — | Disabled — use the pencil icon for now |
| `tag.copy_name` | Copy tag name | copy | — | |
| `tag.pin` | Pin tag | organize | — | Hidden when already pinned |
| `tag.unpin` | Unpin tag | organize | — | Hidden when not pinned |
| `tag.delete` | Delete tag | destructive | destructive, advanced | Disabled — lands later in 0.9.x |

### `tag_chip` — Tag chip attached to a session

| ID | Label | Section | Flags | Notes |
|---|---|---|---|---|
| `tag_chip.copy_name` | Copy tag name | copy | — | |
| `tag_chip.detach` | Remove tag from session | destructive | — | Hidden on unsaved sessions |

### `tool_call` — Tool-call row inside the assistant's tool-work drawer

| ID | Label | Section | Flags | Notes |
|---|---|---|---|---|
| `tool_call.retry` | Retry tool call | edit | advanced | Disabled until v0.10.x |
| `tool_call.copy.name` | Copy tool name | copy | — | |
| `tool_call.copy.input` | Copy tool input | copy | — | Pretty-printed JSON |
| `tool_call.copy.output` | Copy tool output | copy | — | Prefers error text; gated while running |
| `tool_call.copy.id` | Copy tool call ID | copy | advanced | |

### `code_block` — Fenced code block in a message body

| ID | Label | Section | Flags | Notes |
|---|---|---|---|---|
| `code_block.save_to_file` | Save to file… | edit | — | Disabled — tempfile primitive in v0.10.x |
| `code_block.open_in.editor` | Open in editor | edit | advanced | Disabled — tempfile primitive in v0.10.x |
| `code_block.copy` | Copy code | copy | — | |
| `code_block.copy_with_fence` | Copy with Markdown fence | copy | advanced | Includes fence + language tag |

### `link` — Markdown link in a message body

| ID | Label | Section | Flags | Notes |
|---|---|---|---|---|
| `link.open_new_tab` | Open in new tab | navigate | — | `rel="noopener,noreferrer"` |
| `link.open_in.editor` | Open in editor | navigate | advanced | Only enabled for `file://` URLs |
| `link.copy_url` | Copy link URL | copy | — | |
| `link.copy_text` | Copy link text | copy | advanced | |

### `checkpoint` — Checkpoint chip in the conversation gutter

| ID | Label | Section | Flags | Notes |
|---|---|---|---|---|
| `checkpoint.fork` | Fork from here | primary | — | Disabled on orphaned checkpoints (no anchor message) |
| `checkpoint.copy_label` | Copy label | copy | — | Disabled when label empty |
| `checkpoint.copy_id` | Copy checkpoint ID | copy | advanced | |
| `checkpoint.delete` | Delete checkpoint | destructive | destructive | Undo toast, no confirm |

### `multi_select` — Multi-session selection

Fires from any sidebar row right-click when more than one session is
selected. The `multi_select.tag.<tag.id>` and
`multi_select.untag.<tag.id>` submenu leaves are generated
dynamically per tag; pinning them in `menus.toml` is supported but
the IDs change when the tag is deleted/renamed.

| ID | Label | Section | Flags | Notes |
|---|---|---|---|---|
| `multi_select.clear` | Clear selection | navigate | — | |
| `multi_select.close` | Close sessions | organize | — | |
| `multi_select.tag` | Add tag ▸ | organize | — | Submenu parent |
| `multi_select.untag` | Remove tag ▸ | organize | advanced | Submenu parent |
| `multi_select.export` | Export as JSON | copy | — | Timestamped download |
| `multi_select.delete` | Delete sessions | destructive | destructive | Confirm with count |

---

## Notes on override semantics

- **Pinned > declaration order**: pinned IDs come first in their
  section, in the listed order; the remaining actions follow in their
  declaration order.
- **Hidden beats pinned**: if the same ID appears in both, it is
  hidden. (Pinning a hidden action makes no sense — file a bug if the
  opposite behaviour would help you.)
- **Advanced actions stay advanced**: pinning an action marked
  `advanced` does not unhide it in normal mode; Shift-right-click is
  still the gate.
- **`requires` still applies**: if a handler gates itself off (for
  example `session.reopen` only appears on closed sessions), pinning
  won't force it to render.
- **Shortcuts can collide**: the CheatSheet renders whichever binding
  `menus.toml` declares last. Ctrl+Shift+P still works to find any
  action.
- **Unknown IDs are ignored**: no error, no log spam — keeps forward
  compatibility simple when you shuttle a `menus.toml` between
  Bearings versions.

## Debugging

- Tail the server log during startup; a malformed file produces a
  `menus.toml: parse error at <path>` warning and continues with
  defaults.
- `curl localhost:8787/api/ui-config | jq .context_menus` shows the
  parsed shape the frontend sees. Empty `by_target` means either the
  file doesn't exist or every table was dropped as unknown/malformed.
- `Ctrl+Shift+P` confirms actions you hid are still reachable.
