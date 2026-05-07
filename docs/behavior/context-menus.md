# Context menus — observable behavior

Right-clicking a Bearings UI element opens a target-specific context menu. The set of actions on the menu is determined by what the user right-clicked. Every action ID is a stable public identifier (referenced from the user's `menus.toml` overrides). This document lists what the user observes; implementation choices are governed by `docs/architecture-v1.md`.

Sibling subsystems referenced here:
[chat](chat.md), [checklists](checklists.md), [paired-chats](paired-chats.md), [keyboard-shortcuts](keyboard-shortcuts.md).

## Common behavior across every menu

* **Trigger.** Right-click (or long-press on touch). On a sidebar row that is part of a multi-select selection, the right-click opens the **multi-select** menu instead of the single-row menu.
* **Sectioning.** Actions inside a menu are grouped into fixed sections, rendered top-to-bottom in this order: `primary`, `navigate`, `create`, `edit`, `view`, `copy`, `organize`, `destructive`. Empty sections are omitted; section dividers (a thin rule) appear only between non-empty sections.
* **Advanced actions.** Some entries are tagged "advanced" and only appear when the user **Shift+right-clicks**. The cheat-sheet caption at the bottom of an advanced menu reads "Advanced actions revealed (Shift)."
* **Disabled entries.** An action whose preconditions are not met renders greyed; hovering shows a tooltip explaining why it is unavailable (e.g. "no message yet to fork from").
* **Destructive entries.** Actions in the `destructive` section route through a confirmation dialog before firing. The dialog states what is about to happen and offers Cancel / Confirm. The user's confirm action is the commit point; closing the dialog with Esc cancels. The dialog includes a "Don't ask again this session" checkbox below the message. When the user ticks the box and clicks Confirm, subsequent invocations of the same action in the same browser session skip the dialog and fire immediately. Cancelling — with or without the box ticked — never records a suppression. The suppression set is in-memory only; a hard refresh or new tab resets it.
* **Closing the menu.** Esc closes (priority 1 of the global Esc cascade — see [keyboard-shortcuts](keyboard-shortcuts.md)). Clicking outside closes. Picking an action closes after the action fires. Focus moving to an editable field (`<input>`, `<textarea>`, or `contentEditable` host) outside the menu also auto-closes the menu within one event-loop tick; this prevents the menu's global keydown listener from swallowing keystrokes destined for the newly focused field.
* **Keyboard.** Up / Down navigate; Home jumps to the first enabled action; End jumps to the last enabled action; Enter activates; Right opens a submenu; Esc closes. Typing a single letter or digit jumps the highlight to the first action whose mnemonic matches (case-insensitive). Repeated presses of the same key cycle through all actions sharing that mnemonic. Each action's mnemonic is the first alphanumeric character of its label (overridable per action via the `mnemonic` field on `MenuActionDescriptor`); the matching character is rendered underlined in the menu.
* **DOM focus.** Opening the menu moves DOM focus to the first action row. Arrow navigation and mnemonic jumps call `.focus()` on the newly highlighted `<li role="menuitem">` so screen readers announce the active row and the visual focus ring follows. Closing the menu (Esc, outside click, or action pick) returns focus to the element that held focus when the menu opened.
* **Toast feedback.** Actions that don't navigate (Copy, Pin, Unpin, Resolve, etc.) show a brief stub toast describing what happened ("Copied session ID", "Pinned session"). Destructive completions show an undo toast for a few seconds: clicking it reverses the action when the operation is reversible (close, archive, detach), or restores from a soft-delete buffer (delete) when supported by the target.

## Per-target action lists

Action IDs (e.g. `session.copy_id`) are public — `~/.config/bearings/menus.toml` references them by ID to pin or hide entries. Labels here are the user-visible text.

### Session row (sidebar) and conversation header

| Section | Label | ID | Notes |
|---|---|---|---|
| navigate | Open in new tab | `session.open_in_new_tab` | |
| edit | Edit session… | `session.edit` | Opens the SessionEdit modal (Title, Description, Budget, Tags, Instructions). |
| edit | Rename… | `session.rename` | Inline edit in place. |
| edit | Edit tags… | `session.edit_tags` | Opens tag picker. |
| edit | Change model for continuation ▸ | `session.change_model` | Same dialog as the conversation-header model dropdown. |
| create | Duplicate | `session.duplicate` | Copies the session row + tags + working dir; no message history copied. |
| create | Save as template… | `session.save_as_template` | Opens the template-save dialog. |
| create | Fork from last message | `session.fork.from_last_message` | Advanced. Creates a new session sharing history up to the last message. |
| organize | Pin session | `session.pin` | Mutually exclusive with Unpin (only one renders). |
| organize | Unpin session | `session.unpin` | |
| organize | Archive session | `session.archive` | Closes the row into the sidebar's collapsed Closed group. |
| organize | Reopen session | `session.reopen` | Only renders for closed sessions. |
| copy | Copy session ID | `session.copy_id` | Advanced. |
| copy | Copy session title | `session.copy_title` | |
| copy | Copy share link | `session.copy_share_link` | Advanced. |
| destructive | Delete session | `session.delete` | Confirm dialog. Cascades to the conversation history and (per [paired-chats](paired-chats.md)) clears the back-pointer on any item paired with this chat. |
| navigate | Open in terminal | `session.open_in_terminal` | Advanced. Calls `POST /api/shell/exec` with `working_dir`. Greyed when `working_dir` is empty. |

### Message bubble (user or assistant)

| Section | Label | ID | Notes |
|---|---|---|---|
| navigate | Scroll into view | `message.jump_to_turn` | |
| copy | Copy message text | `message.copy_content` | |
| copy | Copy as Markdown | `message.copy_as_markdown` | Advanced. Includes role + timestamp. |
| copy | Copy message ID | `message.copy_id` | Advanced. |
| organize | Pin to turn header | `message.pin` | Floats the bubble in the conversation header. |
| organize | Hide from context window | `message.hide_from_context` | Advanced. Greys the bubble in place; drops it from the next prompt context. |
| organize | Move to session… | `message.move_to_session` | Opens session picker. |
| organize | Split here… | `message.split_here` | Carves the conversation into a fresh sibling session at this point. |
| create | Fork from this message | `message.fork.from_here` | Advanced. |
| create | Regenerate from this message… | `message.regenerate` | Inserts a re-roll boundary. |
| create | Regenerate (rewrite in place) | `message.regenerate.in_place` | Advanced. |
| destructive | Delete message | `message.delete` | Advanced. Confirm dialog. |

### Tag (sidebar tag chip in the filter panel)

| Section | Label | ID |
|---|---|---|
| organize | Pin tag | `tag.pin` |
| organize | Unpin tag | `tag.unpin` |
| copy | Copy tag name | `tag.copy_name` |
| edit | Edit tag… | `tag.edit` |
| destructive | Delete tag | `tag.delete` (advanced) |

The filter panel renders three sections — Project, Severity, Other —
each scoped to one tag class. Selections within a section apply OR
semantics; selections across sections apply AND. An empty section
emits no constraint (it does not exclude rows). The "Edit tag…"
action lands on `/tags`, where a class selector lets the operator
reassign a tag between project / severity / other; severity-class
tags surface their `default_model` / `working_dir` inputs disabled
and cleared because the backend rejects non-null inheritance fields
on severity rows.

### Tag chip (attached to a session, inside SessionEdit / NewSessionForm)

| Section | Label | ID |
|---|---|---|
| copy | Copy tag name | `tag_chip.copy_name` |
| destructive | Remove tag from session | `tag_chip.detach` |

### Tool call (row inside a tool-work drawer — see [chat](chat.md))

| Section | Label | ID |
|---|---|---|
| copy | Copy tool name | `tool_call.copy.name` |
| copy | Copy tool input | `tool_call.copy.input` |
| copy | Copy tool output | `tool_call.copy.output` |
| copy | Copy tool call ID | `tool_call.copy.id` (advanced) |
| edit | Retry tool call | `tool_call.retry` (advanced) |

### Code block (rendered fenced block inside a message body)

| Section | Label | ID |
|---|---|---|
| copy | Copy code | `code_block.copy` |
| copy | Copy with Markdown fence | `code_block.copy_with_fence` (advanced) |
| edit | Save to file… | `code_block.save_to_file` |
| edit | Open in editor | `code_block.open_in.editor` (advanced) |

### Link (Markdown anchor inside a message body)

| Section | Label | ID |
|---|---|---|
| copy | Copy link URL | `link.copy_url` |
| copy | Copy link text | `link.copy_text` (advanced) |
| navigate | Open in new tab | `link.open_new_tab` |
| navigate | Open in editor | `link.open_in.editor` (advanced — for `file://` and resolved-path links) |

### Checkpoint (gutter chip — Phase 14 surface)

| Section | Label | ID |
|---|---|---|
| primary | Fork from here | `checkpoint.fork` |
| copy | Copy label | `checkpoint.copy_label` |
| copy | Copy checkpoint ID | `checkpoint.copy_id` (advanced) |
| destructive | Delete checkpoint | `checkpoint.delete` |

### Multi-select (≥1 sidebar row selected)

| Section | Label | ID |
|---|---|---|
| navigate | Clear selection | `multi_select.clear` |
| organize | Add tag ▸ | `multi_select.tag` |
| organize | Remove tag ▸ | `multi_select.untag` (advanced) |
| organize | Close sessions | `multi_select.close` |
| copy | Export as JSON | `multi_select.export` |
| destructive | Delete sessions | `multi_select.delete` |

The submenu arrows (`▸`) on Add tag / Remove tag open lists of tags currently in the user's tag set; selecting one applies it to every selected session.

### Attachment (`[File N]` chip in composer or transcript) — Phase 15 surface

| Section | Label | ID |
|---|---|---|
| copy | Copy path | `attachment.copy_path` |
| copy | Copy filename | `attachment.copy_filename` |
| view | Open in editor | `attachment.open_in.editor` |
| view | Reveal in file explorer | `attachment.open_in.file_explorer` (advanced) |
| destructive | Remove from message | `attachment.remove` |

`Remove from message` only renders for composer-staged chips (the chip lives in the composer pre-send). For chips inside a transcript user bubble, the action is greyed with the explanation "message already sent."

### Pending operation (row inside the floating pending-ops card) — Phase 16 surface

| Section | Label | ID |
|---|---|---|
| primary | Mark resolved | `pending_operation.resolve` |
| destructive | Dismiss | `pending_operation.dismiss` |
| copy | Copy name | `pending_operation.copy_name` |
| copy | Copy command | `pending_operation.copy_command` (advanced) |
| view | Open directory in editor | `pending_operation.open_in.editor` (advanced) |

The Phase 14-16 actions (checkpoint, attachment, pending operation) are listed above; they share the same sectioning and confirmation rules as the other targets.

Also added in Phase 16 (gap-cycle-03-002): `session.open_in_terminal` (navigate, advanced) — opens the session's `working_dir` via `xdg-open`; only rendered when `working_dir` is non-empty.

## Shell-open integration

The following actions call `POST /api/shell/exec` with `argv: ["xdg-open", <path>]`:

| Action ID | Target | Path passed to xdg-open |
|---|---|---|
| `code_block.open_in.editor` | Code block (advanced) | Code content, only when it is a single-line absolute path |
| `link.open_in.editor` | Link (advanced) | Resolved `file://` URL path or bare absolute path; greyed for `http(s)://` |
| `attachment.open_in.editor` | Attachment chip | `attachment.path` |
| `attachment.open_in.file_explorer` | Attachment chip (advanced) | Parent directory of `attachment.path` |
| `pending_operation.open_in.editor` | Pending op row (advanced) | `op.dir`; action greyed when `dir` is absent |
| `session.open_in_terminal` | Session row (advanced) | `session.working_dir`; action greyed when `working_dir` is empty |

All openers use `xdg-open` (the only command on the default `DEFAULT_ALLOWED_SHELL_COMMANDS` allowlist). The user's desktop environment determines what application opens: a code editor for file paths, a file manager for directories. Users who configure `xdg-open` to launch a terminal emulator for directories will get that behavior for the `open_in_terminal` action.

A non-2xx response from `POST /api/shell/exec` surfaces a transient error toast with the server's `detail` message. The menu closes regardless.

## Where context menus do NOT appear

* **Inside the cheat-sheet modal.** Right-clicking inside it opens the browser's native menu — Bearings does not own that surface.
* **Inside iframes.** The browser's native menu fires.
* **On native browser scroll bars / OS-drawn window chrome.** Bearings cannot intercept those.
* **On the linkified parts of plain text** that happen not to belong to a Markdown body (e.g. text inside a tool-output block). The user can still select-and-copy via the OS clipboard but Bearings does not surface its own menu there.

## Failure modes

* **Action handler error.** A toast surfaces the error message; the action is not retried automatically. The state of the underlying object is whatever the partial run left behind — actions are written to be safe to retry by the user.
* **Stale target.** A right-click on a row that was deleted between mouse-down and the menu opening shows the menu with every action greyed and the explanation "this object no longer exists." Esc / outside-click closes.
* **Confirmation dialog dismissed by closing the tab.** No commit; the destructive action does not fire. The user re-opening the menu next time sees the original state.
* **Shift+right-click without an advanced action available.** The menu opens normally with no "Advanced actions revealed" caption — the user is not penalized for the modifier.
