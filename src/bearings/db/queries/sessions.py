"""Sessions resource — raw SQL CRUD.

Mechanical layer: parameterized SQL in, ``aiosqlite.Row`` out (or
``None`` for not-found, or row counts for mutations). No business
logic — that lives in :mod:`bearings.services.sessions`.

Why dicts at the boundary: Pydantic models belong to the HTTP layer
(request/response shapes); ORM-style row objects would couple the DB
layer to a particular model class. Returning plain row dicts lets the
service layer convert to Pydantic at one well-known seam.

Every function here takes the connection as its first argument. The
caller (service layer, tests) owns the connection's lifetime — see
:func:`bearings.web.db.build_db_dependency` for the per-request wiring.
"""

from typing import Any

import aiosqlite

# Column list mirrored across SELECT/INSERT/UPDATE so the row-to-dict
# conversion stays predictable and a column rename surfaces as one
# diff instead of seven.
_COLUMNS: tuple[str, ...] = (
    "id",
    "working_dir",
    "model",
    "title",
    "description",
    "max_budget",
    "kind",
    "created_at",
    "updated_at",
)
_SELECT_COLUMNS = ", ".join(_COLUMNS)


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert an :class:`aiosqlite.Row` to a plain dict."""
    return {column: row[column] for column in _COLUMNS}


async def insert(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    working_dir: str,
    model: str,
    title: str,
    description: str,
    max_budget: float | None,
    kind: str,
) -> dict[str, Any]:
    """Insert a row and return the inserted record (with timestamps).

    Uses SQLite's ``RETURNING`` (3.35+) so we don't need a follow-up
    SELECT to read the server-defaulted ``created_at`` / ``updated_at``.
    ``aiosqlite`` ships with the modern bundled SQLite, so this is safe.
    """
    # ``_SELECT_COLUMNS`` is a module-private constant composed from
    # :data:`_COLUMNS`; no user input flows into the f-string. The
    # values bind through ``?`` parameters, which SQLite escapes.
    sql = f"""
        INSERT INTO sessions (id, working_dir, model, title, description, max_budget, kind)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING {_SELECT_COLUMNS}
    """  # noqa: S608 — column list is a private constant, not caller input.
    async with connection.execute(
        sql,
        (session_id, working_dir, model, title, description, max_budget, kind),
    ) as cursor:
        row = await cursor.fetchone()
    await connection.commit()
    if row is None:  # pragma: no cover - RETURNING always yields one row
        msg = "INSERT ... RETURNING produced no row"
        raise RuntimeError(msg)
    return _row_to_dict(row)


async def get_by_id(
    connection: aiosqlite.Connection,
    session_id: str,
) -> dict[str, Any] | None:
    """Return the row for *session_id*, or ``None`` if not found."""
    sql = f"SELECT {_SELECT_COLUMNS} FROM sessions WHERE id = ?"  # noqa: S608 — see insert().
    async with connection.execute(sql, (session_id,)) as cursor:
        row = await cursor.fetchone()
    return _row_to_dict(row) if row else None


async def list_paginated(
    connection: aiosqlite.Connection,
    *,
    limit: int,
    offset: int,
    kind: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return ``(items, total)`` for the current page.

    ``total`` is the unfiltered (or kind-filtered) row count, not the
    page size — the response model uses it to compute "has next page"
    on the client.
    """
    where_clauses: list[str] = []
    params: list[object] = []
    if kind is not None:
        where_clauses.append("kind = ?")
        params.append(kind)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # ``where_sql`` is composed from a private literal "kind = ?"; the
    # value binds via ``?``. ``_SELECT_COLUMNS`` is a private constant.
    count_sql = f"SELECT COUNT(*) AS total FROM sessions {where_sql}"  # noqa: S608 — see insert().
    async with connection.execute(count_sql, tuple(params)) as cursor:
        count_row = await cursor.fetchone()
    total = int(count_row["total"]) if count_row else 0

    list_sql = f"""
        SELECT {_SELECT_COLUMNS} FROM sessions
        {where_sql}
        ORDER BY created_at DESC, id ASC
        LIMIT ? OFFSET ?
    """  # noqa: S608 — see insert().
    async with connection.execute(list_sql, (*params, limit, offset)) as cursor:
        rows = await cursor.fetchall()
    return [_row_to_dict(row) for row in rows], total


async def update(
    connection: aiosqlite.Connection,
    session_id: str,
    *,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply a partial update; return the new row, or ``None`` if missing.

    *fields* is the pre-validated set of columns to write. The caller
    (service layer) is responsible for filtering it to known columns
    before passing it in — this function trusts its caller and uses
    parameterized SQL.

    ``updated_at`` is touched here so the service layer doesn't have to
    remember to pass it on every call.
    """
    if not fields:
        # Nothing to write — just refresh updated_at and return the row.
        sql = f"""
            UPDATE sessions
            SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            RETURNING {_SELECT_COLUMNS}
        """  # noqa: S608 — see insert().
        async with connection.execute(sql, (session_id,)) as cursor:
            row = await cursor.fetchone()
        await connection.commit()
        return _row_to_dict(row) if row else None

    # The service layer filters ``fields`` to a whitelist of column
    # names (see ``_UPDATABLE_FIELDS`` in services/sessions.py); the
    # values bind via ``?``. The interpolation is structurally safe.
    set_clause = ", ".join(f"{column} = ?" for column in fields)
    sql = f"""
        UPDATE sessions
        SET {set_clause}, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        RETURNING {_SELECT_COLUMNS}
    """  # noqa: S608 — see insert().
    params = (*fields.values(), session_id)
    async with connection.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    await connection.commit()
    return _row_to_dict(row) if row else None


async def delete(connection: aiosqlite.Connection, session_id: str) -> bool:
    """Delete *session_id*; return True if a row was removed."""
    async with connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,)) as cursor:
        deleted = cursor.rowcount
    await connection.commit()
    return deleted > 0
