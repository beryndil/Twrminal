# Checklists — observable behavior

A checklist is a structured list of work items the user (or an autonomous driver) walks in order. Each item can be checked off, edited, nested under a parent, and paired with a chat session that exists to "do" the item. This document lists what the user observes; implementation choices are governed by `docs/architecture-v1.md`.

Sibling subsystems referenced here:
[chat](chat.md), [paired-chats](paired-chats.md), [keyboard-shortcuts](keyboard-shortcuts.md), [context-menus](context-menus.md).

## What a checklist is, observably

A checklist session is a sidebar row that opens a structured-list pane (not a conversation pane) when selected. The user sees:

* a header band identical to a chat session's (title, tag chips, severity shield, attached-tag column);
* a free-form **notes** field directly under the header;
* a tree of **items** below that, oldest-first within each parent;
* an **Add item** input at the bottom that auto-focuses on first open;
* an **Auto-run** control next to the header (start / pause / stop the autonomous driver — see "Autonomous driver" below).

A checklist session has no composer and no conversation history — those live on the per-item *paired chats*.

## When the user creates a checklist

The user picks "Checklist" as the session kind in the new-session dialog (or via a slash-command / tag-rule the rebuild may add). Tags follow the same rules as chats — any number of tags, with at most one project class, at most one severity class, and any number of general labels (see [chat](chat.md) §"When the user creates a chat" for the cardinality rule). Severity-class tags carry no `default_model` / `working_dir`, so a paired chat spawned from a leaf inherits inheritance fields only from project / general tags. After create, the pane opens with the Add-item input focused.

## Item edit / add / delete / reorder

* **Add.** Typing a label in the Add-item input and pressing Enter creates a new item at the bottom of the current parent and refocuses the input so the user can keep typing. An empty label is rejected at the boundary.
* **Edit label.** Clicking an item's label puts it into inline-edit mode. Enter commits, Esc cancels. Blur is treated as Enter.
* **Edit notes.** Each item has an expandable notes block. Edits commit on blur or Enter; Esc reverts.
* **Delete.** Right-clicking an item opens a context menu (see [context-menus](context-menus.md)) with a destructive Delete entry. Delete cascades to children (a parent's deletion removes its subtree) and to any paired chat session that exists for the item — the chat row is removed from the sidebar. The user is shown a confirm dialog because the action is destructive.
* **Reorder (drag).** Items have a drag handle on the left. Dragging an item shows a drop indicator (a horizontal rule between items) at the legal drop targets. Releasing on a target inserts the item there. Drag is constrained to legal positions only — an item cannot be dropped inside its own subtree, and the indicator does not appear at illegal positions. The new sort order is persisted on drop.
* **Reorder (keyboard).** While focused on an item label, **Tab** nests the item under its previous sibling at the same indent level (effective parent shift). **Shift+Tab** pops it back out one nesting level (parent → grandparent). Both are no-ops at boundaries (Tab on the first child has no previous sibling to nest under; Shift+Tab on a root item has no parent to escape). Indent transitions are animated so the user sees the relationship change.

## Item nesting semantics

* A child's check-state is independent of its parent except through the auto-cascade: when the **last unchecked** root-level item gets checked, the parent checklist session auto-closes (one-directional — unchecking does not reopen). When the last unchecked **child** of a parent item gets checked, the parent's checkbox visually fills (rendered as derived-from-children, not directly toggleable).
* A parent with at least one child renders a **disabled** checkbox whose state is the AND of its children. The user cannot check a parent directly; they check its children.
* A leaf item (no children) renders a **clickable** checkbox.
* Paired-chat affordances (the title link and the **💬 Work on this** button) only render on leaves, since parents are not work units.

## Item ↔ chat-session linking (paired chats)

Each leaf item can be paired with at most one chat session. The user observes:

* A leaf with no pairing shows a **💬 Work on this** button. Pressing it spawns a fresh chat session that inherits the checklist's working directory, model, and tags, with the chat title defaulting to the item's label. The new chat is selected; the item gains a paired-chat link.
* A leaf with a pairing shows a clickable chat title (right of the label) and a "Continue working" affordance. Clicking the title selects the paired chat. The chat's header shows a paired-checklist breadcrumb back to the parent item — see [paired-chats](paired-chats.md).
* **Idempotent spawn.** Pressing **💬 Work on this** twice on the same item does not create two chats; the second click selects the existing pairing.
* **Checking a paired item closes the chat.** Clicking the leaf's checkbox closes the paired chat session (no prompt). Closing cascades up: each parent whose children are all complete auto-closes, and the parent checklist session auto-closes when every root item is complete.
* **Detach.** Removing the link (a context-menu action on the item) reverts the leaf to "no chat" without deleting the chat. The chat stays in the sidebar as a normal chat session.
* **Re-link.** The link action also accepts an existing chat (used by the autonomous driver's visit-existing mode). The target chat must be open (closed sessions are rejected at the boundary).

## Run-control surface (autonomous driver)

A checklist's header carries a small run-control widget:

* **Start.** Begins driving the checklist autonomously, walking unchecked items in sort order. The control changes to **Stop**; a small status line appears beside it ("Running — item 3 of 12, leg 1, 0 failures").
* **Stop.** Halts after the current leg's turn finishes. The user can re-Start later; the next run resumes from the first unchecked item.
* **Pause.** Conceptually a soft stop — the control reuses the Stop wiring; the run is "paused" in the sense that nothing is in flight. There is no separate pause-vs-stop UI in v1.
* **Skip current item.** A submenu of the run-control sets the current item's outcome to skipped and advances. The skipped item shows a sentinel-color status (see "Item-status colors" below) and the run continues.
* **Failure-policy toggle.** A dropdown next to Start lets the user pick `halt` (default) or `skip` for what happens when an item fails. The choice applies to the next Start; in-flight runs honor the policy they were started with.
* **Visit-existing-sessions toggle.** When enabled before Start, the driver reuses each item's already-paired chat (if any) instead of spawning a fresh one. Items with no paired chat (or a closed paired chat) are skipped and contribute to the skipped count.

The status line shows the live counters: items completed, items failed, items blocked, items skipped, legs spawned. On terminal outcome ("Completed", "Halted: failure on item N", "Halted: max items", "Halted: stopped by user", "Halted: empty"), the line freezes and the Start control is enabled again.

## Sentinels (auto-pause / failure / completion)

The autonomous driver consumes structured sentinels emitted by the working agent inside its assistant text. From the user's perspective:

* **Item done.** The driver checks the item, advances to the next unchecked item in sort order, and the status line ticks `items_completed`.
* **Handoff.** The driver kills the current paired chat's runner, spawns a *successor leg* for the same item with the agent's plug as its first prompt, and the status line ticks `legs_spawned`. The user sees the chat row "respawn" — the previous chat closes, a fresh one opens against the same item.
* **Followup, blocking.** A new child item is appended under the current item. The driver recurses into the child before completing the parent.
* **Followup, non-blocking.** A new item is appended at the end of the checklist. The current item completes; the new item is picked up later by the outer loop.
* **Item blocked.** The current item is left unchecked, the paired chat stays open for the user to deal with, the status line ticks `items_blocked`, and the run advances regardless of the failure policy. Blocked items are shown with an amber sentinel color (see "Item-status colors").
* **Pressure-watchdog handoff request.** When the agent's last assistant turn produced no handoff sentinel and the agent's reported context-window pressure has crossed the configured threshold (60 % by default), the driver injects one nudge turn ("please emit a handoff plug now") before treating a quiet turn as a silent-exit failure. The user observes one extra turn in the chat with the nudge text; the agent typically responds with a handoff sentinel and the cutover proceeds.

Malformed or incomplete sentinels are ignored. The driver does not act on a half-emitted block.

### Sentinel safety caps the user observes

* **Max legs per item.** When an item exceeds the leg cap (default 5), the driver halts that item with `failure_reason` "max_legs_per_item exceeded" and honors the failure policy.
* **Max items per run.** A driver that touches more than the per-run cap (default 50) halts with outcome `Halted: max items`. Counts both completed items and items the driver attempted but did not complete.
* **Max followup depth.** Blocking-followup nesting beyond the depth cap (default 3) is treated as a malformed sentinel and ignored.

## Item-status colors

The leftmost column of every item row carries a colored pip whose meaning the user learns by hover-tooltip:

| Color | State |
|---|---|
| (none / hollow) | Not yet attempted by a driver, no paired chat. |
| Slate | Has a paired chat, no run currently driving the item. |
| Blue, animated | The autonomous driver currently has this item active (current leg in flight). |
| Green | Item is checked. |
| Amber | Item is blocked (sentinel-flagged outside-agent-reach). Paired chat stays open. |
| Red | Item failed (sentinel `failed`, leg-cap exceeded, or runtime error during a leg). |
| Grey | Item was skipped (skip-failure policy or visit-existing skip). |

Pinned and severity tag colors come from the [chat](chat.md) / sidebar surface; the item-pip palette is checklist-local.

## Drag-reorder visual feedback

* The dragged row dims and follows the cursor.
* Legal drop targets show a 2-pixel horizontal accent line at the would-be insertion point. Illegal targets (inside the dragged item's own subtree, on the dragged item itself) show no indicator and the cursor takes the not-allowed shape.
* Releasing inside a parent's children area inserts at the end of that parent. Releasing between siblings inserts at that exact slot. Releasing on a sibling row's left edge inserts before that sibling; on its right edge nests as a child of that sibling (when nesting is legal).
* Cancelling the drag (Esc, or releasing outside the checklist pane) restores the original position with no animation.

## When the user starts / pauses / stops a run

| Action | What the user sees |
|---|---|
| **Start** with an empty unchecked set | Outcome `Halted: empty` flashes briefly and the Start control re-enables. |
| **Start** with items pending | Status line ticks live; the currently-active item's pip animates blue; the per-leg paired chat opens in the background (selectable from the sidebar but does not take focus). |
| **Stop** mid-leg | The current turn is interrupted at its next safe boundary; the driver writes a final status snapshot and the Start control re-enables. The paired chat for the interrupted leg remains in the sidebar. |
| **Skip current** | The current item's pip turns grey, the paired chat stays open, the driver advances. |
| **Item fails under `halt` policy** | The driver halts; status line shows `Halted: failure on item N — <reason>`. The failed item's pip turns red. |
| **Item fails under `skip` policy** | The failed item's pip turns red, the run advances, `items_failed` ticks. |

If the server restarts mid-run, the run is rehydrated on next boot — the user sees the status line resume against the same item rather than the run vanishing. Drivers in `running` state at shutdown re-attach to a fresh leg; drivers in `finished` / `errored` are kept for the audit trail and do not re-start.

## Sidebar visibility of paired-chat activity

A paired chat's sidebar row carries the same "needs attention" / "unviewed" indicators as a normal chat (see [chat](chat.md) error states). The driver's leg cutovers are observable in the sidebar as a fast-cycling sequence of new chat rows for the same item. The originating checklist session retains a single row.

## ChecklistChat

A checklist session pane carries a compact **ChecklistChat** panel positioned between the auto-driver header and the items tree. The panel provides a conversational surface for whole-list instructions — for example, "add five items about CI setup" or "reorder these by estimated effort".

**What the user observes:**

* The panel renders at a fixed compact height with an internal scroll area. A user turn and the matching assistant reply each occupy their own row; older turns scroll off the top.
* Each assistant reply renders as a streaming delta: as tokens arrive the text updates in-place, with a blinking cursor appended to the live text. Once the turn completes the cursor disappears and the full body is frozen.
* The composer at the bottom of the panel is a multi-line textarea (Enter sends, Shift+Enter inserts a newline to match the main chat composer convention). A **Send** button sits to the right.
* The textarea is disabled and the Send button is inert while a send is in flight (from submit until the 202 Accepted acknowledgement arrives). After the ack the textarea becomes active again; the streaming assistant reply arrives independently via the WebSocket channel.
* Typing in an empty textarea keeps the Send button disabled; the button enables once at least one non-whitespace character is present.
* If the 202 handshake fails the optimistic user bubble is removed and a brief inline error message appears. The composer re-enables so the user can retry.
* Conversation history for the checklist session is loaded on pane open (the most recent 50 messages). If history cannot be fetched the panel starts empty and remains usable for new messages.

**Relationship to paired chats:** ChecklistChat sends prompts to the checklist session's own agent, not to any per-item paired chat. Whole-list instructions (add, reorder, bulk-check) are appropriate here; item-level work happens in the item's paired chat (see [paired-chats](paired-chats.md)).
