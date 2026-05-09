# Paired chats

A paired chat is a regular chat session that "belongs to" a leaf
item on a checklist. The pair is observable from both sides — the
chat shows a breadcrumb back to the parent item; the item shows a
link to the chat — and a few user actions cascade across the link.

For the conceptual picture see
[../concepts.md §5.1](../concepts.md#51-the-pair-relationship).
For the full observable contract see
[../behavior/paired-chats.md](../behavior/paired-chats.md).

## What you can do here

* [Spawn a paired chat from a leaf](#spawn-a-paired-chat-from-a-leaf)
* [Link an existing chat to a leaf](#link-an-existing-chat-to-a-leaf)
* [Detach a paired chat](#detach-a-paired-chat)
* [Read the breadcrumb chip](#read-the-breadcrumb-chip)
* [Navigate via the breadcrumb](#navigate-via-the-breadcrumb)
* [Recognise driver leg cutovers in the sidebar](#recognise-driver-leg-cutovers)
* [Spawn a new chat from any assistant reply (non-paired chats)](#spawn-from-reply)

---

## Walkthrough

### Spawn a paired chat from a leaf

In the checklist pane, find the unpaired leaf and press the
**💬 Work on this** button beside its label.

What happens:

1. A fresh chat session is created. It inherits the checklist's
   working directory, model, and project + general tags. The chat
   title defaults to the item's label.
2. The pair pointer is set on both sides — `item.paired_chat_id`
   and `chat.checklist_item_id`.
3. The new chat is selected (the conversation pane takes focus).
4. The originating checklist row shows the chat title link and a
   **Continue working** affordance the next time you navigate
   back.

The spawn is **idempotent** — pressing **💬 Work on this** twice
on the same item navigates to the existing chat rather than
creating a second one. Two simultaneous clicks (e.g. double-tap)
collapse to a single pairing.

Backend: `POST /api/checklist-items/{id}/spawn-chat`.

### Link an existing chat to a leaf

Right-click a leaf → **Link to existing chat…**. A session-picker
modal opens listing your open chat sessions.

The picker rejects:

* sessions that are not chat-kind (checklists cannot be paired
  with checklists);
* sessions that are closed (open sessions only — keeps the gate
  consistent with the autonomous driver's visit-existing mode).

Selecting a chat establishes the pairing. The chat keeps its
title, tags, and history; pairing only adds the back-pointer.

Backend: `POST /api/checklist-items/{id}/link`.

### Detach a paired chat

Two paths:

* **From the item side** — right-click the leaf → **Unlink chat**.
* **From the chat side** — right-click the breadcrumb chip in the
  conversation header → **Unlink from item**.

Either action clears the pair pointer on both sides. The chat
keeps its history; it stays in the sidebar as a normal chat
session. The leaf reverts to **no chat** state and the next
**💬 Work on this** click spawns a fresh chat.

Detach is unconditional — there is no confirm dialog because the
data loss is zero (chat history is preserved).

Backend: `POST /api/checklist-items/{id}/unlink`.

### Read the breadcrumb chip

Every paired chat's conversation header carries a breadcrumb chip
above the title:

```
<parent checklist title> › <item label>
```

Hovering shows the full label even when truncated. The chip is a
visual signal that this chat is dedicated work for an item — it's
the canonical way to tell a paired chat from a free-standing one
when both are open in adjacent sidebar rows.

Sidebar paired-chat rows carry a small breadcrumb-style annotation
under the title: `↳ <parent checklist title>`. The annotation is
dim and uses an ellipsis when long. Paired chats sort and filter inside
the sidebar exactly like any other chat — they are not segregated
into a "paired" group.

### Navigate via the breadcrumb

* Clicking the **parent-title** segment selects the parent
  checklist (navigates to its pane).
* Clicking the **item-label** segment scrolls the parent checklist
  pane to the corresponding item (and selects it).

This makes the pair relationship navigable without round-tripping
through the sidebar.

### Recognise driver leg cutovers

When the [autonomous driver](checklists.md#start-the-autonomous-driver)
runs, every leg it spawns is a paired chat. You'll observe in the
sidebar:

* successive chat rows for the same item appearing and closing as
  the driver hands off legs;
* the breadcrumb on each leg's chat pointing to the same item;
* the driver's *visit-existing-sessions* mode reusing an item's
  already-paired chat for the first leg instead of spawning a new
  one — you see the existing chat selected and a fresh prompt
  arrive in its conversation.

The driver does not modify the breadcrumb or the pairing
affordances — the chat-side and item-side surfaces look the same
whether a human or the driver is the one prompting.

### Spawn from reply

Outside checklists, every completed assistant message in a
**non-paired** chat exposes a **＋ SPAWN** action pill on hover
(in the reply-action row, next to *"Ask for more detail"*).
Clicking it forks a new chat:

1. `POST /api/sessions/{parent_id}/spawn_from_reply/{message_id}`.
2. The new session's first user message is the clicked assistant
   body as a Markdown blockquote (each line prefixed with `> `).
3. The new session records `parent_session_id` and
   `pivot_message_id` for back-link rendering.
4. The UI navigates to the new chat. It appears in the sidebar
   under the same tag scope as any other session.

The spawn is **idempotent** on the same `(parent, pivot)` pair
while the spawned chat is open: clicking again returns the
existing session rather than creating a second.

The pill is **suppressed in paired chats** (`checklist_item_id !=
null`). Paired chats are dedicated work surfaces and do not
expose the reply-thread affordance.

---

## Reference

### One-side-closed cascade

| Side closed | What happens |
|---|---|
| **Chat closed** | Chat row moves to sidebar's collapsed Closed group. Leaf still shows the (greyed) chat title and a **Reopen chat** affordance instead of **Continue working**. Pair pointer is preserved. POSTing to the closed chat via the prompt endpoint returns 409. |
| **Item checked** | Per [checklists](checklists.md), checking a paired leaf closes its paired chat. Cascades up: parent's checkbox fills if every sibling complete; checklist auto-closes if every root item complete. |
| **Chat deleted** | Pair pointer cleared from item side. Leaf reverts to unpaired and shows **💬 Work on this** as if no chat had ever existed. Chat history is gone; nothing in the leaf preserves it. |
| **Item deleted** | Leaf disappears. Chat keeps its history but loses the breadcrumb (chip changes to *"(checklist deleted)"* and clicking it does nothing). The chat is otherwise a normal chat. |
| **Parent checklist deleted** | Checklist row gone. Each child leaf's paired chat shows the *"(checklist deleted)"* breadcrumb. |
| **Both sides closed** | Both rows render in their respective Closed groups. Reopening either does not reopen the other; reopen each side independently. |

### Reopen semantics

* Reopening a closed paired chat re-attaches its sidebar row to
  the open group; the breadcrumb works again; the composer is
  enabled.
* Auto-close is **one-directional**. If the parent checklist
  auto-closed (every root item complete) and you re-open a child
  item by unchecking it, the parent checklist's session does NOT
  auto-reopen — you must reopen the parent explicitly.
* Reopening the parent does not reopen its previously-closed
  paired chats either; each is reopened on its own.

### Action surface

| Action | Trigger | Endpoint |
|---|---|---|
| Spawn paired chat | **💬 Work on this** on a leaf | `POST /api/checklist-items/{id}/spawn-chat` |
| Link existing chat | Right-click leaf → **Link to existing chat…** | `POST /api/checklist-items/{id}/link` |
| Unlink (item side) | Right-click leaf → **Unlink chat** | `POST /api/checklist-items/{id}/unlink` |
| Unlink (chat side) | Right-click breadcrumb chip → **Unlink from item** | (same endpoint) |
| Spawn from reply | Hover assistant message → **＋ SPAWN** | `POST /api/sessions/{parent_id}/spawn_from_reply/{message_id}` |
| Continue working | Click chat title on leaf row | (UI nav) |
| Reopen chat (after item-check close) | Right-click in Closed group → **Reopen** | `POST /api/sessions/{id}/reopen` |

---

## See also

* [../concepts.md §5](../concepts.md#5-paired-chats-and-checklists)
  — conceptual picture.
* [../behavior/paired-chats.md](../behavior/paired-chats.md) —
  full observable behavior reference.
* [checklists.md](checklists.md) — checklist surface (drag-reorder,
  nesting, auto-driver, sentinels).
* [sessions.md](sessions.md) — session lifecycle, fork, spawn
  from reply.
* [../api.md §checklist-items](../api.md#checklist-items),
  [../api.md §spawn-from-reply](../api.md#spawn-from-reply).
* `src/bearings/web/routes/checklists.py`,
  `src/bearings/web/routes/spawn_from_reply.py`.
