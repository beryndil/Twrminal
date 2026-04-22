"""Layered system-prompt assembler.

Order: base → session description (if non-null) → tag memories (one
per attached tag with a `tag_memories` row, in the canonical
pinned-first / sort_order / id order) → checklist context (if this
session is paired to a checklist item) → checklist overview (if this
session IS a checklist — v0.5.2) → session instructions (if non-null).

The session description is the human-authored "why this window
exists" blurb rendered under the title/tags in the Conversation
header. Injecting it into the system prompt gives empty-context
agents a first-person orientation hint without having to query the
DB or UI out-of-band.

The checklist-context layer (v0.5.0, Slice 4 of nimble-checking-heron)
is the "memory plug" for paired chats: when
`sessions.checklist_item_id` is set, this assembler reads the live
parent checklist on every turn and injects the current item's label
/ notes / state plus a compact sibling summary. Edits to the
checklist from another tab land on the next turn without a runner
respawn — same re-read-per-turn pattern as tag memories.

Pure SQL reads — no writes, safe to call per-turn. `AgentSession`
calls this before every SDK turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import aiosqlite

from bearings.agent.base_prompt import BASE_PROMPT

LayerKind = Literal[
    "base",
    "session_description",
    "tag_memory",
    "checklist_context",
    "checklist_overview",
    "session",
]


@dataclass(frozen=True)
class Layer:
    name: str
    kind: LayerKind
    content: str


@dataclass(frozen=True)
class AssembledPrompt:
    layers: list[Layer]
    text: str


def estimate_tokens(text: str) -> int:
    """Rough token count for UI display. Uses ~4-chars-per-token as a
    proxy — the real figure comes from the tokenizer on the Claude
    side, but this is good enough for the Context-tab badge and
    avoids pulling a heavyweight tokenizer dep.

    Empty strings count as zero; anything else is at least 1 so the
    UI never shows an all-zero row for non-empty content.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def _finalize(layers: list[Layer]) -> AssembledPrompt:
    parts = [f"<!-- layer: {layer.kind}[{layer.name}] -->\n{layer.content}" for layer in layers]
    return AssembledPrompt(layers=layers, text="\n\n".join(parts))


def _format_checklist_context(
    checklist: dict[str, Any],
    focus_item: dict[str, Any],
    parent_title: str | None,
) -> str:
    """Render the checklist-context layer body. Focused-item details
    come first (label + notes + checked state); a compact sibling
    summary follows so the agent sees the full list shape without
    drowning in item-specific detail. Long notes are not truncated
    here — the user already accepted them into the checklist and the
    per-turn cost of a verbose checklist is bounded by the list
    itself, not by Bearings."""
    lines: list[str] = []
    title = (parent_title or "").strip() or "(untitled checklist)"
    lines.append(f"You are working on one item of the checklist: {title!r}.")
    notes = (checklist.get("notes") or "").strip()
    if notes:
        lines.append("")
        lines.append("Checklist notes:")
        lines.append(notes)
    lines.append("")
    item_state = "CHECKED" if focus_item.get("checked_at") else "UNCHECKED"
    lines.append(f"Current item ({item_state}): {focus_item['label']}")
    item_notes = (focus_item.get("notes") or "").strip()
    if item_notes:
        lines.append("")
        lines.append("Item notes:")
        lines.append(item_notes)
    siblings = [it for it in checklist.get("items", []) if int(it["id"]) != int(focus_item["id"])]
    if siblings:
        lines.append("")
        lines.append("Other items in this checklist:")
        for sib in siblings:
            glyph = "[x]" if sib.get("checked_at") else "[ ]"
            lines.append(f"  {glyph} {sib['label']}")
    lines.append("")
    lines.append(
        "Stay focused on the current item. Reference siblings by label only "
        "when the user brings them up or when they're directly relevant."
    )
    lines.append(
        "Do not propose working on sibling items, do not offer to continue to "
        "the next item, and do not modify sibling items' state. When the user "
        "considers this item resolved the session is finished — Dave will open "
        "a new session for the next item. Closing this chat marks the item "
        "done automatically; you do not need to offer to do that yourself."
    )
    return "\n".join(lines)


def _render_overview_items(
    children_by_parent: dict[int | None, list[dict[str, Any]]],
    parent_id: int | None,
    depth: int,
    lines: list[str],
) -> None:
    """Walk the parent→children map depth-first, emitting one line per
    item with indentation that reflects nesting. Item notes wrap under
    their owning item one extra indent level. Split from
    `_format_checklist_overview` so the formatter stays under the
    40-line ceiling."""
    for item in children_by_parent.get(parent_id, []):
        glyph = "[x]" if item.get("checked_at") else "[ ]"
        indent = "  " * depth
        lines.append(f"{indent}{glyph} {item['label']} (id={item['id']})")
        item_notes = (item.get("notes") or "").strip()
        if item_notes:
            note_indent = "  " * (depth + 1)
            for note_line in item_notes.splitlines():
                lines.append(f"{note_indent}  {note_line}")
        _render_overview_items(children_by_parent, int(item["id"]), depth + 1, lines)


def _format_checklist_overview(checklist: dict[str, Any], list_title: str | None) -> str:
    """Render the whole-checklist body injected into every turn of an
    embedded checklist chat (v0.5.2). The agent sees the list's title
    and notes once, then a flat item tree with `[x]`/`[ ]` glyphs and
    per-item notes. Unlike the per-item `checklist_context` layer this
    does NOT narrow focus to a single item: the whole point of the
    embedded chat is list-wide conversation, so the agent should be
    free to answer questions that span items, suggest reordering,
    flag duplicates, etc."""
    lines: list[str] = []
    title = (list_title or "").strip() or "(untitled checklist)"
    lines.append(f"You are chatting with the user inside a checklist session titled {title!r}.")
    lines.append(
        "The structured list and its items are the subject of this conversation. "
        "The user may toggle, add, remove, or reorder items out-of-band; you will "
        "see the latest state on every turn below."
    )
    notes = (checklist.get("notes") or "").strip()
    if notes:
        lines.append("")
        lines.append("Checklist notes:")
        lines.append(notes)
    children_by_parent: dict[int | None, list[dict[str, Any]]] = {}
    for item in checklist.get("items", []):
        children_by_parent.setdefault(item.get("parent_item_id"), []).append(item)
    lines.append("")
    if any(children_by_parent.values()):
        lines.append("Items:")
    else:
        lines.append("Items: (none yet — the list is empty)")
    _render_overview_items(children_by_parent, None, 0, lines)
    lines.append("")
    lines.append(
        "Reference items by their label (and id when disambiguation helps) "
        "when discussing them. You do not modify the checklist yourself — the "
        "user toggles items in the UI. Suggestions are welcome; edits are the "
        "user's call."
    )
    return "\n".join(lines)


async def _load_checklist_overview_layer(
    conn: aiosqlite.Connection,
    session_id: str,
) -> Layer | None:
    """Build the whole-checklist overview layer for a kind='checklist'
    session. Returns `None` when the companion `checklists` row is
    missing (transient race during session creation, or a manual DB
    edit). A `None` result means the assembler skips the layer on this
    turn; the chat still works as a plain session."""
    from bearings.db import _checklists  # local import: avoid circular

    checklist = await _checklists.get_checklist(conn, session_id)
    if checklist is None:
        return None
    async with conn.execute("SELECT title FROM sessions WHERE id = ?", (session_id,)) as cursor:
        title_row = await cursor.fetchone()
    list_title = title_row["title"] if title_row is not None else None
    body = _format_checklist_overview(checklist, list_title)
    return Layer(name=f"list-{session_id}", kind="checklist_overview", content=body)


async def _load_checklist_context_layer(
    conn: aiosqlite.Connection,
    session_id: str,
    checklist_item_id: int,
) -> Layer | None:
    """Build the checklist-context layer for a paired chat. Returns
    `None` when the pairing has gone stale (item deleted out from
    under the session — the session's FK auto-nulls, but an in-flight
    row may still point at a missing item). `None` result means the
    assembler skips the layer on this turn; the chat keeps working as
    a plain session.

    Reads three rows: the target item, its parent checklist + items,
    and the parent session title. All local to the checklists module
    except the title lookup."""
    from bearings.db import _checklists  # local import: avoid circular

    item = await _checklists.get_item(conn, checklist_item_id)
    if item is None:
        return None
    checklist_id = str(item["checklist_id"])
    checklist = await _checklists.get_checklist(conn, checklist_id)
    if checklist is None:
        return None
    async with conn.execute("SELECT title FROM sessions WHERE id = ?", (checklist_id,)) as cursor:
        title_row = await cursor.fetchone()
    parent_title = title_row["title"] if title_row is not None else None
    body = _format_checklist_context(checklist, item, parent_title)
    return Layer(name=f"item-{checklist_item_id}", kind="checklist_context", content=body)


async def assemble_prompt(conn: aiosqlite.Connection, session_id: str) -> AssembledPrompt:
    layers: list[Layer] = [Layer(name="base", kind="base", content=BASE_PROMPT)]

    async with conn.execute(
        "SELECT description, session_instructions, checklist_item_id, kind "
        "FROM sessions WHERE id = ?",
        (session_id,),
    ) as cursor:
        session_row = await cursor.fetchone()
    if session_row is None:
        return _finalize(layers)

    description = session_row["description"]
    session_instructions = session_row["session_instructions"]
    checklist_item_id = session_row["checklist_item_id"]
    kind = session_row["kind"] if "kind" in session_row.keys() else "chat"

    if description:
        layers.append(Layer(name="description", kind="session_description", content=description))

    async with conn.execute(
        "SELECT t.name AS name, tm.content AS content "
        "FROM session_tags st "
        "JOIN tags t ON t.id = st.tag_id "
        "JOIN tag_memories tm ON tm.tag_id = t.id "
        "WHERE st.session_id = ? "
        "ORDER BY t.pinned DESC, t.sort_order ASC, t.id ASC",
        (session_id,),
    ) as cursor:
        async for row in cursor:
            layers.append(Layer(name=row["name"], kind="tag_memory", content=row["content"]))

    if checklist_item_id is not None:
        context_layer = await _load_checklist_context_layer(
            conn, session_id, int(checklist_item_id)
        )
        if context_layer is not None:
            layers.append(context_layer)

    # v0.5.2: when this session IS a checklist (not merely paired to
    # an item), inject the whole-list overview so the embedded chat
    # panel in ChecklistView can talk about the list with context. The
    # two layers are mutually exclusive in practice — a checklist
    # session has no `checklist_item_id` and an item-paired chat is
    # kind='chat' — but we don't enforce that here; both layers are
    # idempotent reads so a weird row just pays for two lookups.
    if kind == "checklist":
        overview_layer = await _load_checklist_overview_layer(conn, session_id)
        if overview_layer is not None:
            layers.append(overview_layer)

    if session_instructions:
        layers.append(Layer(name="session", kind="session", content=session_instructions))

    return _finalize(layers)
