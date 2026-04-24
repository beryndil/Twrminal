"""Artifact table operations — agent-authored files that Bearings
serves back to the browser for inline display.

This is the outbound mirror of `routes_uploads.py` + migration 0027:
uploads track files the user drops INTO the prompt (chip UI is the
deferred follow-up); artifacts track files the agent wrote and wants to
show back OUT. The HTTP layer owns path-allowlist validation on
register and on serve; this module owns only the CRUD, matching the
shape of `_checkpoints.py`.

Returned rows are `dict` so the HTTP layer can splat them into a
Pydantic model; see `_checkpoints.py` for the same pattern. `sha256`
is stored once at register time and never recomputed — a registered
row is an immutable reference to a snapshot of the bytes that existed
when the register call arrived.
"""

from __future__ import annotations

from typing import Any

import aiosqlite

from bearings.db._common import _new_id, _now

ARTIFACT_COLS = "id, session_id, path, filename, mime_type, size_bytes, sha256, created_at"


async def create_artifact(
    conn: aiosqlite.Connection,
    session_id: str,
    *,
    path: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    sha256: str,
) -> dict[str, Any]:
    """Insert an artifact row. Caller must have already validated the
    path against `settings.artifacts.serve_roots` and stat'd the file
    for size/hash — this layer just persists the row.

    Raises sqlite3.IntegrityError on FK miss; the route owns the 404
    translation, matching `_checkpoints.create_checkpoint`.
    """
    artifact_id = _new_id()
    now = _now()
    await conn.execute(
        f"INSERT INTO artifacts ({ARTIFACT_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, session_id, path, filename, mime_type, size_bytes, sha256, now),
    )
    await conn.commit()
    row = await get_artifact(conn, artifact_id)
    assert row is not None  # just inserted
    return row


async def get_artifact(conn: aiosqlite.Connection, artifact_id: str) -> dict[str, Any] | None:
    """Fetch one row by id, or None. Used by the GET /api/artifacts/{id}
    stream handler and by delete to look up the owning session."""
    async with conn.execute(
        f"SELECT {ARTIFACT_COLS} FROM artifacts WHERE id = ?",
        (artifact_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def list_artifacts(conn: aiosqlite.Connection, session_id: str) -> list[dict[str, Any]]:
    """Every artifact for a session, newest first. Matches the
    `list_checkpoints` ordering contract — the composite index on
    (session_id, created_at) from migration 0028 serves this directly."""
    async with conn.execute(
        f"SELECT {ARTIFACT_COLS} FROM artifacts "
        "WHERE session_id = ? ORDER BY created_at DESC, id DESC",
        (session_id,),
    ) as cursor:
        return [dict(row) async for row in cursor]


async def delete_artifact(conn: aiosqlite.Connection, artifact_id: str) -> bool:
    """Remove a row by id. Returns True if a row was removed. The
    on-disk file is NOT deleted — that's the GC sweep's job (shared
    with uploads; see TODO.md). Callers that need to delete the bytes
    should unlink the path before calling this."""
    cursor = await conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
    await conn.commit()
    return cursor.rowcount > 0
