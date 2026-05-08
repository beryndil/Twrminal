"""Preferences singleton row — DB access layer (item 3.2).

The preferences table holds exactly one row (id = 1, enforced by a
CHECK constraint in schema.sql). All callers go through
:func:`get_preferences` to read and :func:`patch_preferences` to
write; neither function creates the row — the seed INSERT OR IGNORE in
schema.sql guarantees the row exists after :func:`load_schema` runs.

Foreign-key enforcement must be active on the connection before calling
these functions (``PRAGMA foreign_keys = ON``); the bootstrap in
:func:`bearings.db.connection.load_schema` handles this for the
long-lived production connection.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

# The singleton's fixed primary key.
_PREFS_ID = 1


@dataclass(frozen=True)
class Preferences:
    """In-memory mirror of the preferences row."""

    theme: str
    default_model: str | None
    default_permission_mode: str | None
    default_working_dir: str | None
    # gap-cycle-03-011 profile / identity fields.
    display_name: str | None
    avatar_path: str | None
    avatar_mime_type: str | None
    # gap-cycle-07-001: desktop-notification opt-in.
    notify_on_complete: bool
    updated_at: str


def _row_to_prefs(row: aiosqlite.Row) -> Preferences:
    return Preferences(
        theme=row["theme"],
        default_model=row["default_model"],
        default_permission_mode=row["default_permission_mode"],
        default_working_dir=row["default_working_dir"],
        display_name=row["display_name"],
        avatar_path=row["avatar_path"],
        avatar_mime_type=row["avatar_mime_type"],
        notify_on_complete=bool(row["notify_on_complete"]),
        updated_at=row["updated_at"],
    )


async def get_preferences(conn: aiosqlite.Connection) -> Preferences:
    """Return the singleton preferences row.

    Raises :class:`RuntimeError` if the seed row is absent (should
    never happen after :func:`load_schema`).
    """
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        """
        SELECT theme, default_model, default_permission_mode,
               default_working_dir, display_name, avatar_path,
               avatar_mime_type, notify_on_complete, updated_at
          FROM preferences
         WHERE id = ?
        """,
        (_PREFS_ID,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:  # pragma: no cover — schema seed guarantees this
        raise RuntimeError("preferences singleton row missing; was load_schema called?")
    return _row_to_prefs(row)


def _add_prefs_update(
    updates: list[str],
    params: list[object],
    condition: bool,
    column: str,
    value: object,
) -> None:
    """Append a SET clause and its value when ``condition`` is true."""
    if condition:
        updates.append(f"{column} = ?")
        params.append(value)


async def patch_preferences(
    conn: aiosqlite.Connection,
    *,
    theme: str | None = None,
    default_model: str | None = None,
    default_permission_mode: str | None = None,
    default_working_dir: str | None = None,
    display_name: str | None = None,
    avatar_path: str | None = None,
    avatar_mime_type: str | None = None,
    notify_on_complete: bool = False,
    fields: frozenset[str] = frozenset(),
) -> Preferences:
    """Update the singleton row with only the fields named in ``fields``.

    ``fields`` is the set of column names to write; the corresponding
    keyword argument supplies the value (``None`` clears a nullable
    column; omitting a field from ``fields`` leaves it unchanged).

    ``theme`` is excluded from the ``fields`` guard when non-None
    because the theme column is NOT NULL — callers pass a valid theme
    string directly and it is always written.

    The avatar/display-name fields (``display_name``, ``avatar_path``,
    ``avatar_mime_type``) follow the same ``fields``-gated semantics as
    the other nullable columns.

    Typical call from the route layer (mirrors Pydantic
    ``model_fields_set``):

    .. code-block:: python

        await patch_preferences(
            conn,
            theme="evergreen",
            default_model="haiku",
            default_working_dir=None,
            fields=frozenset({"default_model", "default_working_dir"}),
        )

    Returns the updated row.
    """
    updates: list[str] = []
    params: list[object] = []

    _add_prefs_update(updates, params, theme is not None, "theme", theme)
    _add_prefs_update(updates, params, "default_model" in fields, "default_model", default_model)
    _add_prefs_update(
        updates,
        params,
        "default_permission_mode" in fields,
        "default_permission_mode",
        default_permission_mode,
    )
    _add_prefs_update(
        updates,
        params,
        "default_working_dir" in fields,
        "default_working_dir",
        default_working_dir,
    )
    _add_prefs_update(updates, params, "display_name" in fields, "display_name", display_name)
    _add_prefs_update(updates, params, "avatar_path" in fields, "avatar_path", avatar_path)
    _add_prefs_update(
        updates, params, "avatar_mime_type" in fields, "avatar_mime_type", avatar_mime_type
    )
    if "notify_on_complete" in fields:
        updates.append("notify_on_complete = ?")
        params.append(1 if notify_on_complete else 0)

    if updates:
        updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
        params.append(_PREFS_ID)
        await conn.execute(
            f"UPDATE preferences SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await conn.commit()

    return await get_preferences(conn)


__all__ = ["Preferences", "get_preferences", "patch_preferences"]
