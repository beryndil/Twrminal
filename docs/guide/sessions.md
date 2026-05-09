# Sessions

A session is a row in the sidebar that ties together a conversation
(or checklist) with its tags, working directory, routing, messages,
checkpoints, and metadata. This guide walks every per-session
action exposed in the UI — beyond just "send a message," which is
covered in [getting-started](getting-started.md).

For the conceptual picture see [../concepts.md §2](../concepts.md#2-the-session-model).
For the full observable contract see
[../behavior/sessions.md](../behavior/sessions.md) and
[../behavior/chat.md](../behavior/chat.md).

## What you can do here

* [Create a session](#creating-a-session)
* [Navigate between sessions](#navigating-between-sessions)
* [Mark sessions viewed](#mark-sessions-viewed)
* [Rename a session inline](#rename-a-session-inline)
* [Pin / unpin a session](#pin--unpin-a-session)
* [Archive (close) a session](#archive-close-a-session)
* [Reopen a closed session](#reopen-a-closed-session)
* [Delete a session permanently](#delete-a-session-permanently)
* [Export a session as JSON](#export-a-session-as-json)
* [Import a session from JSON](#import-a-session-from-json)
* [Drag-drop import multiple JSONs](#drag-drop-import-multiple-jsons)
* [Fork a session from a specific message](#fork-a-session-from-a-specific-message)
* [Spawn a new chat from an assistant reply](#spawn-a-new-chat-from-an-assistant-reply)
* [Bulk operations on multiple sessions](#bulk-operations-on-multiple-sessions)
* [Save a session as a template](#save-a-session-as-a-template)

---

## Walkthrough

### Creating a session

Click the **+** button at the top of the sidebar (or use the
keyboard shortcut documented in
[../behavior/keyboard-shortcuts.md](../behavior/keyboard-shortcuts.md)).

The new-session dialog **pre-fills** the working directory and
executor model from the most-recently-updated session. First-time
users (no prior session) get the per-instance preferences defaults.

Either source is overridable. To explicitly start fresh — useful
when starting unrelated work — press **Shift+C** (or Shift-click
the **+** button) and the dialog opens with all defaults cleared.

The dialog requires:

| Field | Notes |
|---|---|
| Tags | At least one. At most one `project`-class, at most one `severity`-class, any number of `general`. Cardinality is enforced — extra `project` or `severity` tags return `422`. Type a name in the inline filter to create-and-attach a new tag without leaving the form. |
| Working directory | Free-text path or browse via the FS picker. |
| Routing selection | Executor model, optional advisor model with `max_uses` (default 5), effort level. The dialog renders a live **routing-preview line** that updates ~300ms after each keystroke; "Routed from tag rule …" or "Manual override" once you touch the routing controls. |
| First message | Multi-line textarea. |

Live indicators visible in the dialog:

* **Quota bar pair** (overall + Sonnet) at the top — yellow at 80%,
  red at 95%.
* **Quota-guard downgrade banner** — yellow banner above the Start
  button when the routed choice would be downgraded:
  *"Routing downgraded to Sonnet (overall quota at NN%). [Use Opus
  anyway]"*. Clicking the override link records the override for
  analytics.

Press **Start Session** to create the row, attach the tags, send
the first message, and open the chat in the conversation pane. The
session appears in the sidebar under each of its tags.

### Navigating between sessions

* **Click** any sidebar row to select.
* **`j` / `k`** move down / up in the sidebar list.
* **`Alt+1` … `Alt+9`** jump to the Nth session.
* The full keybinding registry is reachable via **`?`** — see
  [../behavior/keyboard-shortcuts.md](../behavior/keyboard-shortcuts.md).

### Mark sessions viewed

Selecting a row stamps `last_viewed_at` server-side
(`POST /api/sessions/{id}/viewed`) and emits a sessions-broadcast
upsert so the green pip clears in any other open tab/window within
the same WebSocket tick. Refocusing the tab while the session is
already selected fires the same POST (tab visibility-change).

### Rename a session inline

Double-click the session-row title. The title text is replaced by
an `<input>` pre-filled with the current title. **Enter** commits
via `PATCH /api/sessions/{id}` (the same endpoint the right-click
**Rename** action uses); **Esc** cancels; blur commits.

A plain single-click within the dblclick window is consumed by the
title span and deferred 300ms; if no second click follows, normal
row activation (navigation + viewed-mark) fires after the guard
expires. Modifier-clicks (Ctrl / Meta / Shift) on the title are
passed through to the row anchor for multi-select.

### Pin / unpin a session

Right-click any sidebar row → **Pin session** (or **Unpin** when
already pinned). Pinned sessions stay at the top of their sidebar
group regardless of `updated_at`. The pin state is persisted on the
session row.

### Archive (close) a session

Three paths:

* Right-click → **Close session**.
* Multi-select → **Close** (see [Bulk operations](#bulk-operations-on-multiple-sessions)).
* Implicit close — checking the last paired-leaf in a checklist
  closes the paired chat; cascades up to close the parent checklist
  when every root item is complete.

A closed session moves to the collapsed **Closed** group in the
sidebar. The conversation pane stays readable and exportable, but
the prompt endpoint returns `409` for closed sessions.

Closing a `kind='checklist'` session via the close endpoint returns
`422` — checklists auto-close only via the cascade. This is a
deliberate guard.

### Reopen a closed session

Right-click → **Reopen session**, or expand the Closed group and
click the row to select it (selecting alone does not reopen — you
must use the action). A reopened session re-enters its tag-grouped
position in the sidebar; the conversation pane re-enables the
composer.

Reopening a paired chat does not reopen the parent checklist
(auto-close is one-directional — see [paired-chats](paired-chats.md)).

### Delete a session permanently

Right-click → **Delete session**. A confirm dialog appears because
the action is destructive and irreversible. Delete cascades to
messages, tool-call rows, SDK transcript entries, checkpoints, and
any paired-chat link the session participates in.

Multi-select → **Delete** is also available (see
[Bulk operations](#bulk-operations-on-multiple-sessions)).

### Export a session as JSON

Right-click → **Export session JSON**. The browser downloads
`<slug>.json` (slug is the title lowercased, non-alphanumeric runs
collapsed to `-`, leading/trailing `-` stripped; falls back to
`session.json` if the slug is empty).

The exported JSON object carries:

```json
{
  "session":     { ...SessionOut shape... },
  "messages":    [ ...MessageExport... ],
  "tool_calls":  [ ...SDK transcript blobs... ],
  "checkpoints": [ ...CheckpointExport... ],
  "attachments": []
}
```

`attachments` is reserved for future use — uploads are content-
addressed and shared globally; there is no per-session attachment
linking table yet.

Closed sessions are exported the same as open sessions; the
endpoint returns `200` for any existing session regardless of close
state.

Backend: `GET /api/sessions/{id}/export`. See
[../api.md §sessions](../api.md#sessions).

### Import a session from JSON

Click the **Import session…** button below the New Session pill in
the sidebar. The `SessionImportDialog` opens; either paste JSON
into the textarea or use **Choose file…** to pick a `.json` file.

* Success → dialog closes, the imported session opens in the
  conversation pane.
* Validation error (`422`) → dialog stays open, error detail shows
  inline.
* Conflict (`409`) → the JSON's `session.id` matches an existing
  row. The dialog offers a **force replace** affordance which
  re-submits with `?force=true`, deleting the existing row first.

The imported session is created with its **original UUID** so the
round-trip is identity-preserving. `checklist_item_id` is cleared
(the destination has no matching parent). Routing-decision columns
are reset to their schema defaults because `SessionOut` does not
carry them. Messages, checkpoints, and SDK transcript entries are
inserted with their original ids / fields.

Backend: `POST /api/sessions/import[?force=true]`. See
[../api.md §sessions](../api.md#sessions).

### Drag-drop import multiple JSONs

Drag one or more `.json` export files onto the sidebar. The aside
gains a visible accent ring while files are dragged over it.

On drop, files import sequentially:

1. A `Importing N of M…` progress line appears.
2. Each file's text is read, JSON-parsed, POSTed to
   `/api/sessions/import`.
3. Per-file failures (parse error / `ApiError`) are recorded but
   the batch continues — one bad file does not abort the rest.
4. After all files: the progress line clears; failures (if any)
   show in a single-line summary; the first successful import
   becomes the active session.

This is the canonical way to bulk-import a directory exported via
**Export selected** without repeating the dialog flow.

### Fork a session from a specific message

Right-click any message → **Fork from here**. A new session is
created sharing the parent's history up to and including the
clicked message. The parent retains its full history; both rows
appear in the sidebar.

### Spawn a new chat from an assistant reply

Hover any completed assistant message in a non-paired chat. A
**＋ SPAWN** action pill appears in the reply-action row. Clicking
it forks a new chat:

1. `POST /api/sessions/{parent_id}/spawn_from_reply/{message_id}`.
2. The new session's first user message is the clicked assistant
   body as a Markdown blockquote (each line prefixed with `> `).
3. The new session records `parent_session_id` and
   `pivot_message_id` for back-link rendering.
4. The UI navigates to the new chat.

The spawn is **idempotent**: clicking again on the same assistant
message while the spawned chat is open returns the existing session.

The pill is suppressed in paired chats (`checklist_item_id != null`)
— those are dedicated work surfaces and do not expose the reply-
thread affordance.

### Bulk operations on multiple sessions

Multi-select sidebar rows (Ctrl-click, Shift-click for ranges).
The right-click context menu changes to expose bulk actions:

| Action | Endpoint | Behaviour |
|---|---|---|
| Close | `POST /api/sessions/bulk` `op=close` | Atomic batch with per-ID savepoints; partial failures surface inline. Pushes an undo toast (*"N sessions archived"*) backed by per-session `/reopen` calls. |
| Delete | `POST /api/sessions/bulk` `op=delete` | Atomic batch; partial failures inline. |
| Export | `POST /api/sessions/bulk` `op=export` | Streams a single bundle named `bearings-export-YYYY-MM-DD.json`. |
| Add tag | `POST /api/sessions/bulk` `op=tag` | `MultiSelectTagPicker`; partial failures inline. |
| Remove tag | `POST /api/sessions/bulk` `op=untag` | Same picker, inverse op. |

`session_ids` is capped at `BULK_SESSION_IDS_MAX` (500). HTTP
status is always `200`; callers inspect each `results[*].ok` for
partial failures.

### Save a session as a template

Right-click any session → **Save as template**. The session's
metadata (working directory, executor model, advisor model,
permission mode, attached tags by class) is persisted as a template
row. The new-session dialog's template picker (the **t** keyboard
shortcut, or the dropdown in the dialog) renders the saved
templates.

Selecting a template populates the dialog with the saved values;
the user can still override any field before pressing **Start
Session**. Templates carry no message history — they are scaffolds,
not session clones.

For the templates API see [../api.md §templates](../api.md#templates).

---

## Reference

### Action surface

| Action | Trigger | Endpoint |
|---|---|---|
| Create | **+** button / new-session dialog | `POST /api/sessions` |
| Navigate / select | sidebar click, `j` / `k`, `Alt+1..9` | (UI only) |
| Mark viewed | row select / tab focus | `POST /api/sessions/{id}/viewed` |
| Rename | dblclick title / **Rename** menu | `PATCH /api/sessions/{id}` |
| Pin | right-click → **Pin session** | `PATCH /api/sessions/{id}` `pinned=true` |
| Archive (close) | right-click → **Close** | `POST /api/sessions/{id}/close` |
| Reopen | right-click → **Reopen** | `POST /api/sessions/{id}/reopen` |
| Delete | right-click → **Delete** (confirm) | `DELETE /api/sessions/{id}` |
| Export JSON | right-click → **Export session JSON** | `GET /api/sessions/{id}/export` |
| Import JSON | sidebar **Import session…** | `POST /api/sessions/import[?force=true]` |
| Fork | message right-click → **Fork from here** | `POST /api/sessions/{id}/fork_at/{message_id}` |
| Spawn from reply | assistant-message hover **＋ SPAWN** | `POST /api/sessions/{id}/spawn_from_reply/{message_id}` |
| Bulk close / delete / export / tag | multi-select context menu | `POST /api/sessions/bulk` |
| Save template | right-click → **Save as template** | `POST /api/templates` |
| Activity pip | (live, no action) | `/ws/sessions` broadcast |

### Activity pip colours

Single coloured pip per sidebar row; resolved in priority order
(first match wins):

| Priority | Colour | Animation | Condition |
|---|---|---|---|
| 1 | **Red** | Flashing | Agent parked waiting on user (tool approval / `AskUserQuestion`) **OR** `error_pending` latched |
| 2 | **Orange** | Flashing | Agent turn actively running |
| 3 | **Green** | Solid | New output the user has not opened (`last_completed_at > last_viewed_at`). Suppressed on the currently-selected row. |
| 4 | (none) | — | Idle and caught up |

Driven by the `runner_state` WebSocket events
(`is_running` / `is_awaiting_user` fields) for red/orange and the
`last_completed_at` / `last_viewed_at` timestamps on the
`SessionOut` row for green.

### Header band components (per-chat)

| Component | What it does |
|---|---|
| Title | Inline-renamable (dblclick). |
| Severity shield | Coloured chip from the `severity`-class tag (or empty when none attached). |
| Tag chips | All attached tags; clicking a chip filters the sidebar. |
| Paired-checklist breadcrumb | Present when `checklist_item_id != null` — `<checklist title> › <item label>`. See [paired-chats](paired-chats.md). |
| Executor-model dropdown | Mid-session swap (calls `runner.set_model()` via `PATCH /api/sessions/{id}/model`). |
| Permission-mode selector | `Default` / `Accept edits` / `Plan` / `Bypass permissions`. See [../behavior/chat.md §Permission-mode selector](../behavior/chat.md#permission-mode-selector). |
| Total-cost / context-window indicator | Live tally; updates per turn. |
| Quota bar pair | Overall + Sonnet headroom; yellow at 80%, red at 95%. |
| Megaphone (feedback) | Opens GitHub issue form pre-filled with version, UA, platform, repro scaffold. No data is POSTed by Bearings — user submits manually. |

---

## See also

* [getting-started.md](getting-started.md) — install / first-run /
  first-session walkthrough.
* [paired-chats.md](paired-chats.md) — how paired chats relate
  to checklists.
* [routing.md](routing.md) — how the routing badge and quota guard
  surfaces work.
* [inspector.md](inspector.md) — five-tab inspector across the
  conversation pane.
* [../behavior/sessions.md](../behavior/sessions.md) — session-level
  observable behavior reference.
* [../behavior/chat.md](../behavior/chat.md) — full conversation
  pane behavior reference.
* [../api.md §sessions](../api.md#sessions),
  [../api.md §sessions-bulk](../api.md#sessions-bulk),
  [../api.md §spawn-from-reply](../api.md#spawn-from-reply).
* `src/bearings/web/routes/sessions.py`,
  `src/bearings/web/routes/sessions_bulk.py`,
  `src/bearings/web/routes/spawn_from_reply.py`,
  `src/bearings/web/routes/messages.py`,
  `frontend/src/lib/components/sidebar/`.
