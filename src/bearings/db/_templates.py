"""Session-template table operations (Phase 9b of docs/context-menu-plan.md).

A template is a stand-alone snapshot captured from one session so the
user can later spawn a new session pre-populated with the same
working_dir / model / tag set / first prompt. Three consumer surfaces
drive the shape here:

  * The template-picker wants every row newest-first — hence
    `list_templates` ORDER BY created_at DESC, backed by the
    (created_at) index from migration 0025.
  * The `POST /sessions/from_template/{id}` route wants a single row
    it can pass into `create_session` + `attach_tag` — hence
    `get_template` returning a full row (with `tag_ids` already
    JSON-decoded) or None.
  * The CRUD endpoints want minimal surface: create + delete. No
    in-place update — templates are intentionally write-once so the
    UI flow is "delete + save again" rather than juggling partial
    edits. We can grow an `update_template` helper once a real
    rename / tweak flow lands.

Returns dict rows with the `tag_ids` key already decoded into a
`list[int]` (the JSON encoding is a persistence detail, not a caller
contract). The connection-commit-then-read pattern mirrors
`_checkpoints.create_checkpoint`: commit the write, then re-fetch so
callers always see the persisted shape.
"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from bearings.db._common import _new_id, _now

TEMPLATE_COLS = "id, name, body, working_dir, model, session_instructions, tag_ids_json, created_at"


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    """Decode a raw `session_templates` row into the caller-facing dict
    shape — `tag_ids_json` becomes a `tag_ids: list[int]` field. A bad
    JSON payload is treated as an empty list; we log through the store
    layer rather than crash because a hand-edited DB should degrade to
    "no tags" instead of a 500."""
    data = dict(row)
    raw = data.pop("tag_ids_json")
    try:
        decoded = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        decoded = []
    data["tag_ids"] = [int(x) for x in decoded if isinstance(x, int)]
    return data


async def create_template(
    conn: aiosqlite.Connection,
    *,
    name: str,
    body: str | None = None,
    working_dir: str | None = None,
    model: str | None = None,
    session_instructions: str | None = None,
    tag_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Insert a new template row and return it.

    `name` is the only required field. Everything else is nullable so
    the picker can render a "blank scratchpad" template that carries no
    model / working_dir / prompt and lets the downstream create path
    fall through to the app-wide defaults.

    Tag ids are stored as a JSON array; no FK so stale ids from a
    since-deleted tag don't block the insert. The instantiation path
    filters those out at attach time."""
    template_id = _new_id()
    now = _now()
    tag_ids_json = json.dumps(list(tag_ids or []))
    await conn.execute(
        f"INSERT INTO session_templates ({TEMPLATE_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            template_id,
            name,
            body,
            working_dir,
            model,
            session_instructions,
            tag_ids_json,
            now,
        ),
    )
    await conn.commit()
    row = await get_template(conn, template_id)
    assert row is not None  # just inserted
    return row


async def get_template(conn: aiosqlite.Connection, template_id: str) -> dict[str, Any] | None:
    """Fetch a single template by id, or None if not found. Returns
    the caller-facing shape (`tag_ids` as list[int])."""
    async with conn.execute(
        f"SELECT {TEMPLATE_COLS} FROM session_templates WHERE id = ?",
        (template_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return _row_to_dict(row) if row is not None else None


async def list_templates(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Every template, newest first. The (created_at) index from
    migration 0025 serves this query — SQLite walks the index backward
    and streams rows without a sort step."""
    async with conn.execute(
        f"SELECT {TEMPLATE_COLS} FROM session_templates ORDER BY created_at DESC, id DESC",
    ) as cursor:
        return [_row_to_dict(row) async for row in cursor]


async def delete_template(conn: aiosqlite.Connection, template_id: str) -> bool:
    """Delete a template by id. Returns True if a row was removed."""
    cursor = await conn.execute("DELETE FROM session_templates WHERE id = ?", (template_id,))
    await conn.commit()
    return cursor.rowcount > 0
