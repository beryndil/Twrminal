"""Sessions service — orchestrates queries and owns business logic.

Single source of truth for:

- ID generation (UUID4, hex form for URL friendliness).
- The set of fields a PATCH may touch (mirrors :class:`SessionUpdate`).
- Translating ``SessionUpdate`` (with ``model_fields_set`` semantics)
  into the dict the queries layer expects.

Returns plain dicts to the router. The router converts to
:class:`SessionResponse` on the way out — keeps the service layer
HTTP-agnostic so future CLI / WS callers can use it directly.
"""

import uuid
from typing import Any

import aiosqlite

from bearings.db.queries import sessions as sessions_queries
from bearings.models.sessions import SessionCreate, SessionUpdate

# Maximum page size accepted by ``list_sessions``. Caps unbounded
# query cost for a careless client. Above this, paginate.
LIST_LIMIT_MAX = 200
LIST_LIMIT_DEFAULT = 50


async def create_session(
    connection: aiosqlite.Connection,
    payload: SessionCreate,
) -> dict[str, Any]:
    """Mint a new session row and return the inserted record."""
    return await sessions_queries.insert(
        connection,
        session_id=uuid.uuid4().hex,
        working_dir=payload.working_dir,
        model=payload.model,
        title=payload.title,
        description=payload.description,
        max_budget=payload.max_budget,
        kind=payload.kind,
    )


async def get_session(
    connection: aiosqlite.Connection,
    session_id: str,
) -> dict[str, Any] | None:
    """Return the row for *session_id*, or ``None`` if not found."""
    return await sessions_queries.get_by_id(connection, session_id)


async def list_sessions(
    connection: aiosqlite.Connection,
    *,
    limit: int = LIST_LIMIT_DEFAULT,
    offset: int = 0,
    kind: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List sessions with optional kind filter; return ``(items, total)``."""
    return await sessions_queries.list_paginated(
        connection,
        limit=limit,
        offset=offset,
        kind=kind,
    )


async def update_session(
    connection: aiosqlite.Connection,
    session_id: str,
    payload: SessionUpdate,
) -> dict[str, Any] | None:
    """Apply a partial update; return new row, or ``None`` if missing.

    Uses Pydantic's ``model_fields_set`` to distinguish "client didn't
    send this field" from "client sent null". Only fields explicitly
    present in the request are written to the DB.
    """
    fields_to_update: dict[str, Any] = {
        name: getattr(payload, name)
        for name in payload.model_fields_set
        if name in _UPDATABLE_FIELDS
    }
    return await sessions_queries.update(
        connection,
        session_id,
        fields=fields_to_update,
    )


async def delete_session(connection: aiosqlite.Connection, session_id: str) -> bool:
    """Delete *session_id*; return True if a row was removed."""
    return await sessions_queries.delete(connection, session_id)


# Whitelist of column names the service is willing to write on a PATCH.
# Mirrors :class:`SessionUpdate`. Defined as a module constant so a new
# field has to be added here intentionally — defense against an
# accidental "update everything Pydantic accepted" path.
_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {
        "working_dir",
        "model",
        "title",
        "description",
        "max_budget",
        "kind",
    }
)
