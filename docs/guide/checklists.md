# Checklists

A checklist is a structured-list session that walks work items in
order — manually, or under the autonomous driver. Each leaf item
can pair with a chat session that "does" the item; the driver
spawns those pairings, consumes sentinels from the agent's output,
and advances the list.

For the conceptual picture see
[../concepts.md §5](../concepts.md#5-paired-chats-and-checklists).
For the full observable behavior see
[../behavior/checklists.md](../behavior/checklists.md). Paired-
chat behavior lives in [paired-chats.md](paired-chats.md).

## What you can do here

* [Create a checklist session](#create-a-checklist-session)
* [Add and edit items](#add-and-edit-items)
* [Nest items (drag and keyboard)](#nest-items-drag-and-keyboard)
* [Check / uncheck items](#check--uncheck-items)
* [Spawn a paired chat from a leaf](#spawn-a-paired-chat-from-a-leaf)
* [Send whole-list instructions through ChecklistChat](#send-whole-list-instructions)
* [Start the autonomous driver](#start-the-autonomous-driver)
* [Skip the current item / change failure policy](#skip--change-failure-policy)
* [Read the run-status line](#read-the-run-status-line)
* [Recover after a server restart mid-run](#recover-after-a-server-restart)
* [Read item-status colours](#read-item-status-colours)

---

## Walkthrough

### Create a checklist session

In the new-session dialog pick **Checklist** as the session kind
(or use a slash-command / tag-rule that creates one). Tags follow
the same rules as chats: at most one project class, at most one
severity class, any number of general labels.

Severity-class tags carry no `default_model` / `working_dir`, so a
paired chat spawned from a leaf inherits inheritance fields from
project / general tags only.

After create, the pane opens with the **Add-item** input focused.

### Add and edit items

* **Add** — type a label, press Enter. Item lands at the bottom of
  the current parent; the input refocuses for rapid entry. Empty
  labels are rejected at the boundary.
* **Edit label** — click the item label to enter inline-edit mode.
  Enter commits, Esc cancels, blur commits.
* **Edit notes** — each item has an expandable notes block. Edits
  commit on blur or Enter; Esc reverts.
* **Delete** — right-click → **Delete**. A confirm dialog appears
  because the action is destructive. Delete cascades to children
  (a parent's deletion removes its subtree) and to any paired chat
  that exists for the item.

### Nest items (drag and keyboard)

**Drag.** Each item has a drag handle on the left. While dragging:

* a 2-pixel horizontal accent line shows the legal insertion point;
* illegal targets (inside the dragged item's own subtree, on the
  dragged item itself) show no indicator and the cursor takes the
  not-allowed shape;
* releasing inside a parent's children area inserts at the end of
  that parent;
* releasing between siblings inserts at that exact slot;
* releasing on a sibling's left edge inserts before that sibling;
  on its right edge nests as a child (when nesting is legal);
* cancelling (Esc, or releasing outside the pane) restores the
  original position with no animation.

**Keyboard.** While focused on an item label:

* **Tab** — nests the item under its previous sibling at the same
  indent level. No-op when there is no previous sibling.
* **Shift+Tab** — pops out one nesting level. No-op at root.

Indent transitions are animated so the relationship change is
visible.

### Check / uncheck items

* **Leaf items** render a clickable checkbox. Checking a leaf
  closes its paired chat (if any) — see
  [paired-chats](paired-chats.md) §"Checking a paired item".
* **Parent items** render a **disabled** checkbox whose state is
  the AND of their children. You cannot check a parent directly.
* **Auto-cascade.** When the last unchecked **child** of a parent
  is checked, the parent's checkbox visually fills (rendered as
  derived-from-children). When the last unchecked **root** item
  is checked, the parent checklist session auto-closes.
* **Auto-close is one-directional.** Unchecking does not re-open
  the closed checklist; you must reopen it explicitly via the
  sidebar context menu.

### Spawn a paired chat from a leaf

A leaf with no pairing shows a **💬 Work on this** button. Pressing
it:

1. Creates a fresh chat session that inherits the checklist's
   working directory, model, and project + general tags. Title
   defaults to the item's label.
2. Sets the pair pointer on both sides (item → chat,
   chat → item).
3. Selects the new chat (the conversation pane takes focus).

The spawn is **idempotent** — pressing **💬 Work on this** twice
on the same item navigates to the existing chat rather than
creating a second one. Two simultaneous clicks (e.g. double-tap)
collapse to a single pairing.

A leaf with a pairing shows a clickable chat title (right of the
label) and a **Continue working** affordance instead of the spawn
button. Right-click a leaf for **Link to existing chat…** /
**Unlink chat** — see [paired-chats](paired-chats.md).

### Send whole-list instructions

The checklist pane carries a compact **ChecklistChat** panel
between the auto-driver header and the items tree. Use it for
whole-list operations:

* *"Add five items about CI setup."*
* *"Reorder these by estimated effort."*
* *"Mark every item under the 'pre-flight' parent as done."*

The panel renders a streaming conversation surface with a multi-
line composer (Enter sends, Shift+Enter inserts a newline). The
composer disables on submit and re-enables when the 202 ack
arrives; the streaming reply arrives independently via WebSocket.

ChecklistChat sends prompts to the **checklist session's own
agent**, not to any per-item paired chat. Item-level work happens
in the item's paired chat.

### Start the autonomous driver

The checklist header carries a small Auto-driver widget with:

* **Start / Stop** button — `POST /api/checklists/{id}/run/start`.
* **Pause** — soft stop (reuses the Stop wiring; no separate pause
  UI in v1).
* **Skip current item** submenu.
* **Failure policy** dropdown — `halt` (default) or `skip`.
* **Visit-existing-sessions** toggle.

Pressing **Start** begins driving unchecked items in sort order.
The control changes to **Stop**; a status line appears beside it:
*"Running — item 3 of 12, leg 1, 0 failures"*.

When started, the driver:

1. Picks the first unchecked item in sort order.
2. Spawns (or reuses, with visit-existing) a paired chat for that
   item.
3. Consumes the sentinels the agent emits in its assistant text:
   `done` / `handoff` / `followup` (blocking + non-blocking) /
   `blocked` / `failed`.
4. Acts on each sentinel (see below).
5. Advances to the next unchecked item until terminal outcome.

#### Sentinel reactions

| Sentinel | Driver reaction |
|---|---|
| `done` | Check the item, advance to next unchecked, tick `items_completed`. |
| `handoff` | Kill current paired chat's runner, spawn a successor leg with the agent's plug as first prompt, tick `legs_spawned`. |
| `followup` (blocking) | Append a new child item under the current item, recurse into it before completing the parent. |
| `followup` (non-blocking) | Append a new item at the end of the checklist; current item completes; new item picked up later by the outer loop. |
| `blocked` | Leave item unchecked, leave paired chat open, tick `items_blocked`, advance regardless of failure policy. |
| `failed` | Honour the failure policy (`halt` / `skip`). |

Malformed or incomplete sentinels are ignored — the driver does
not act on a half-emitted block.

#### Pressure-watchdog handoff

When the agent's last assistant turn produced no handoff sentinel
AND the agent's reported context-window pressure has crossed the
configured threshold (60% by default), the driver **injects one
nudge turn** ("please emit a handoff plug now") before treating a
quiet turn as a silent-exit failure. You'll see one extra turn in
the chat with the nudge text; the agent typically responds with a
handoff sentinel and the cutover proceeds.

### Skip / change failure policy

The Auto-driver widget exposes both:

* **Skip current item** — sets the current item's outcome to
  skipped (sentinel-color grey) and advances. The skipped item
  contributes to the skipped count; the run continues.
* **Failure policy** — `halt` halts the run on any `failed`
  sentinel or runtime error; `skip` advances past the failed
  item and ticks `items_failed`.

The choice applies to the next Start; in-flight runs honour the
policy they were started with.

### Read the run-status line

While running, the status line shows live counters:

* items_completed
* items_failed
* items_blocked
* items_skipped
* legs_spawned

On terminal outcome the line freezes:

* `Completed` — every unchecked item finished.
* `Halted: failure on item N — <reason>` — `halt` policy hit a
  `failed` sentinel.
* `Halted: max items` — the per-run safety cap (50 by default)
  exceeded.
* `Halted: stopped by user` — user pressed Stop.
* `Halted: empty` — Start pressed with no unchecked items.

The Start control re-enables once the line freezes.

### Recover after a server restart

The driver state is persisted. If the server restarts mid-run:

* drivers in `running` state at shutdown re-attach to a fresh leg
  on next boot; you see the status line resume against the same
  item rather than the run vanishing;
* drivers in `finished` / `errored` state are kept for the audit
  trail and do not re-start.

### Read item-status colours

The leftmost column of every item carries a coloured pip:

| Colour | State |
|---|---|
| (none / hollow) | Not yet attempted by a driver, no paired chat. |
| Slate | Has a paired chat, no run currently driving the item. |
| Blue, animated | Driver currently has this item active (current leg in flight). |
| Green | Item is checked. |
| Amber | Item is blocked (sentinel `blocked` — outside-agent-reach). Paired chat stays open. |
| Red | Item failed (sentinel `failed`, leg-cap exceeded, or runtime error). |
| Grey | Item was skipped (skip-failure policy or visit-existing skip). |

Hovering shows a tooltip explaining the state.

---

## Reference

### Safety caps the driver enforces

| Cap | Default | Override | Effect when exceeded |
|---|---|---|---|
| Max legs per item | 5 | `RUN_MAX_LEGS_PER_ITEM` | Halt that item with `failure_reason="max_legs_per_item exceeded"`; honour failure policy. |
| Max items per run | 50 | `RUN_MAX_ITEMS` | Halt the run with outcome `Halted: max items`. Counts both completed items and items the driver attempted but did not complete. |
| Max blocking-followup depth | 3 | `RUN_MAX_FOLLOWUP_DEPTH` | Treat the offending sentinel as malformed; ignore it. |

### Action surface

| Action | Trigger | Endpoint |
|---|---|---|
| Create checklist | New-session dialog → kind=Checklist | `POST /api/sessions` |
| Add item | Add-item input + Enter | `POST /api/checklists/{id}/items` |
| Edit label / notes | Click → inline edit | `PATCH /api/checklist-items/{id}` |
| Delete item | Right-click → Delete (confirm) | `DELETE /api/checklist-items/{id}` |
| Drag-reorder | Drag handle → drop | `POST /api/checklist-items/{id}/move` |
| Indent / outdent | Tab / Shift+Tab | `POST /api/checklist-items/{id}/indent` / `/outdent` |
| Check / uncheck | Click leaf checkbox | `POST /api/checklist-items/{id}/check` / `/uncheck` |
| Block / unblock | Right-click → Block / Unblock | `POST /api/checklist-items/{id}/block` / `/unblock` |
| Spawn paired chat | **💬 Work on this** | `POST /api/checklist-items/{id}/spawn-chat` |
| Link existing chat | Right-click → **Link to existing chat…** | `POST /api/checklist-items/{id}/link` |
| Unlink chat | Right-click → **Unlink chat** | `POST /api/checklist-items/{id}/unlink` |
| Start run | Auto-driver **Start** | `POST /api/checklists/{id}/run/start` |
| Stop run | Auto-driver **Stop** | `POST /api/checklists/{id}/run/stop` |
| Pause run | Auto-driver **Pause** | `POST /api/checklists/{id}/run/pause` |
| Resume run | (After Pause) | `POST /api/checklists/{id}/run/resume` |
| Skip current | Submenu | `POST /api/checklists/{id}/run/skip-current` |
| Read status | Status line | `GET /api/checklists/{id}/run/status` |
| ChecklistChat send | Compact panel composer | `POST /api/sessions/{checklist_id}/prompt` |

### Sidebar visibility

A paired chat's sidebar row carries the same "needs attention" /
"unviewed" indicators as a normal chat. The driver's leg cutovers
are observable in the sidebar as a fast-cycling sequence of new
chat rows for the same item. The originating checklist session
keeps a single row.

---

## See also

* [../concepts.md §5](../concepts.md#5-paired-chats-and-checklists)
  — conceptual picture.
* [../behavior/checklists.md](../behavior/checklists.md) — full
  observable behavior reference.
* [paired-chats.md](paired-chats.md) — pair relationship,
  detach / re-link, breadcrumb anatomy.
* [sessions.md](sessions.md) — session lifecycle (close cascades
  hit the parent checklist when every root item is complete).
* [../api.md §checklists](../api.md#checklists),
  [../api.md §checklist-items](../api.md#checklist-items).
* `src/bearings/agent/auto_driver.py` — driver class.
* `src/bearings/agent/sentinel.py` — sentinel parser.
* `src/bearings/web/routes/checklists.py`,
  `src/bearings/web/routes/checklist_items` (in
  `frontend/src/lib/components/checklist/`).
