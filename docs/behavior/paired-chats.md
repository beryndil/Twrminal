# Paired chats — observable behavior

A paired chat is a regular [chat](chat.md) session that "belongs to" a specific item on a [checklist](checklists.md). The pairing is observable: the chat shows a breadcrumb back to the parent item, the item shows a link to the chat, and a few user actions cascade across the link. This document lists what the user observes; implementation choices are governed by `docs/architecture-v1.md`.

Sibling subsystems referenced here:
[chat](chat.md), [checklists](checklists.md), [keyboard-shortcuts](keyboard-shortcuts.md), [context-menus](context-menus.md).

## What "paired" means observably

A pair is a 1:1 link between exactly one checklist *leaf* item and exactly one chat session, in this direction:

* Each leaf item has at most one paired chat.
* Each chat session that was spawned from a checklist item carries a back-pointer to that item.
* Parent (non-leaf) items cannot be paired.

The user sees the pair in two places:

1. **From the checklist side.** The leaf item row shows a clickable chat title to the right of its label, plus a "Continue working" button when the pair already exists. See [checklists](checklists.md) for the full row anatomy.
2. **From the chat side.** The conversation header shows a breadcrumb chip: `<parent checklist title> › <item label>`. Hovering reveals the full label; clicking the parent-title segment selects the parent checklist; clicking the item-label segment scrolls the parent checklist pane to the corresponding item.

## Link / spawn UI

### Spawning a new pair

Pressing **💬 Work on this** on an unpaired leaf:

1. Creates a fresh chat session that inherits the checklist's working directory, model, and tags. The chat title defaults to the item's label.
2. Sets the pair pointer on both sides (item → chat, chat → item).
3. Selects the new chat (the conversation pane takes focus).
4. The originating checklist row shows the chat title link and the "Continue working" affordance the next time the user navigates back.

The spawn is **idempotent**. Pressing **💬 Work on this** on an already-paired item navigates to the existing chat rather than creating a second one. Two simultaneous clicks (e.g. double-tap) collapse to a single pairing — the second click selects the same session the first one created.

### Linking to an existing chat

Right-clicking a leaf item exposes a **Link to existing chat…** action (see [context-menus](context-menus.md)) that opens a session-picker modal listing the user's open chat sessions. Selecting one establishes the pairing. The picker rejects:

* sessions that are not chat-kind (checklists cannot be paired);
* sessions that are closed (the autonomous driver's visit-existing mode requires open sessions; the gate is consistent).

The originating chat session keeps its title, tags, and history; pairing only adds the back-pointer.

### Detaching

Right-clicking a paired leaf exposes **Unlink chat** (the inverse of Link). Detach is unconditional: the pair pointer is cleared on both sides, the chat keeps its history, the item reverts to "no chat" state, and the next **💬 Work on this** click spawns a fresh chat.

The chat itself can also be detached *from the chat side* via its breadcrumb's right-click menu — the user observes the same outcome.

## Indicator placement on the chat row

In the sidebar, a paired chat row carries a small breadcrumb-style annotation under the title: `↳ <parent checklist title>`. The annotation is dim and truncates with an ellipsis when the parent title is long. Hovering shows the full parent title plus the item label.

Paired chats sort and filter inside the sidebar exactly like any other chat session — they are not segregated into a "paired" group. The annotation is the only visual difference.

## Behavior under one-side-closed

The user can close either side of the pair independently. The pairing's reaction:

| Side closed | What the user observes |
|---|---|
| Chat closed | The chat row moves to the sidebar's collapsed "Closed" group. The leaf item still shows the (now-greyed) chat title and a "Reopen chat" affordance instead of "Continue working". The pair pointer is preserved. Posting to the closed chat via the [prompt-endpoint](prompt-endpoint.md) returns 409 — the same gate the UI enforces. |
| Item checked (closes the chat as a side-effect) | Per [checklists](checklists.md), checking a paired leaf closes the paired chat. The user observes the chat row move to "Closed" and the item's checkbox fill green. This cascades to the parent if every sibling is also complete, and to the parent checklist session if every root item is complete. |
| Chat deleted | The pair pointer is cleared from the item side; the leaf reverts to unpaired and shows the "💬 Work on this" button as if no chat had ever existed. The chat history is gone; nothing in the leaf preserves it. |
| Item deleted | The leaf disappears. The chat keeps its history but loses the breadcrumb; the breadcrumb chip on the chat header changes to "(checklist deleted)" — clicking it does nothing because there is no parent to navigate to. The chat is otherwise a normal chat session and can be used as such. |
| Parent checklist deleted | The checklist row disappears from the sidebar. Each child leaf's paired chat also loses its parent pointer; chats render the "(checklist deleted)" breadcrumb. |
| Both sides closed | Both rows render in their sidebar's collapsed Closed group. Reopening either does not reopen the other; the user must reopen each side independently. |

## Reopen semantics

* Reopening a closed paired chat from the sidebar re-attaches its sidebar row to the open group; the breadcrumb back to the item works again; the composer is enabled.
* If the parent checklist auto-closed (every root item complete) and the user re-opens a child item by unchecking it, the parent checklist's session does **not** auto-reopen — auto-close is one-directional. The user must reopen the parent checklist explicitly. Reopening the parent does not reopen its previously-closed paired chats either; each is reopened on its own.

## Cross-cuts with the autonomous driver

When the autonomous driver (see [checklists](checklists.md)) is running, every leg it spawns is a paired chat. The user observes:

* successive chat rows for the same item appear and close as the driver hands off legs;
* the breadcrumb on each leg's chat points to the same item;
* the driver's *visit-existing-sessions* mode reuses an item's already-paired chat for the first leg instead of spawning a new one — the user sees the existing chat selected and a fresh prompt arrive in its conversation.

The driver does not modify the breadcrumb or the pairing affordances — the chat-side and item-side surfaces look the same whether a human or the driver is the one prompting.

## Spawn from reply (gap-cycle-03-007)

Every completed assistant message in a non-paired chat session displays a **＋ SPAWN** action pill in its reply-action row (visible on hover, alongside the "Ask for more detail" button). Clicking it:

1. Calls `POST /api/sessions/{parent_id}/spawn_from_reply/{message_id}`.
2. The server creates a fresh `kind='chat'` session whose first user message is a Markdown blockquote of the clicked assistant message body (each line prefixed with `> `).
3. The new session records `pivot_message_id` (the clicked message) and `parent_session_id` (the originating session) so the idempotency check and future back-link rendering can locate the relationship.
4. The UI navigates to the new chat; it appears in the sidebar under the same tag scope as any other session.

The spawn is **idempotent**: clicking **＋ SPAWN** again on the same assistant message while the spawned chat is still open returns the existing session rather than creating a second one.

The **＋ SPAWN** pill is suppressed in sessions that are already paired to a checklist item (`checklist_item_id != null`) — paired chats are dedicated "work chat" surfaces and do not expose the reply-thread affordance.

### Spawn-from-reply endpoint contract

| Parameter | Description |
|---|---|
| `parent_id` | The session containing the pivot message. Must exist — 404 otherwise. |
| `message_id` | The assistant-role message to quote. Must belong to `parent_id` — 404 if absent or mismatched. 422 if the message role is not `assistant`. |

HTTP 201 on first spawn; HTTP 200 (with `created: false`) on idempotent re-spawn of an open session. Response body: `SpawnFromReplyOut` (`chat_session_id`, `parent_session_id`, `pivot_message_id`, `title`, `working_dir`, `model`, `created`).
