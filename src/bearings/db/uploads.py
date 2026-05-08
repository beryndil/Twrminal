"""``uploads`` table queries — content-addressed file metadata.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches the ``uploads`` table. The table itself is the
*metadata* surface for the misc-API uploads endpoint (item 1.10; arch
§1.1.5 ``web/routes/uploads.py``); the on-disk body lives under
:data:`bearings.config.constants.DEFAULT_UPLOADS_STORAGE_ROOT` keyed
by sha256, written by :mod:`bearings.agent.uploads`.

Behavior docs are silent on the upload contract (chat.md mentions
"attachment chips" only) — see ``docs/architecture-v1.md`` §1.1.5
plus ``src/bearings/config/constants.py`` §"Uploads" for the
decided-and-documented endpoint shape.

Public surface:

* :class:`UploadRow` — frozen dataclass row mirror with
  ``__post_init__`` validation.
* :func:`insert_or_get` — content-addressed insert; returns the
  existing row on sha256 collision (dedup at zero cost).
* :func:`get`, :func:`get_by_sha256`, :func:`list_all` — cache reads.
* :func:`delete` — row removal (caller is responsible for the
  on-disk body — agent layer owns that side per arch §3 layer rules).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import aiosqlite

from bearings.config.constants import (
    UPLOAD_FILENAME_MAX_LENGTH,
    UPLOAD_MIME_TYPE_MAX_LENGTH,
    UPLOADS_LIST_DEFAULT_LIMIT,
    UPLOADS_LIST_MAX_LIMIT,
)

# sha256 hex digest length: 32 bytes = 64 hex chars. Pinned as a
# named constant so a downstream length check reads as the concern
# rather than a magic number.
_SHA256_HEX_LENGTH: int = 64


@dataclass(frozen=True)
class UploadRow:
    """Row mirror for the ``uploads`` table.

    Field semantics follow ``schema.sql``:

    * ``id`` — INTEGER PRIMARY KEY AUTOINCREMENT.
    * ``sha256`` — hex-encoded sha256 of the body (64 chars). UNIQUE
      across the table; a re-upload of the same body returns the
      existing row via :func:`insert_or_get`.
    * ``filename`` — user-supplied multipart filename (capped at
      :data:`bearings.config.constants.UPLOAD_FILENAME_MAX_LENGTH`).
    * ``mime_type`` — content-type from the multipart part, or
      :data:`bearings.config.constants.UPLOAD_DEFAULT_MIME_TYPE` if
      absent.
    * ``size`` — on-disk body size in bytes (≥ 0).
    * ``created_at`` — INTEGER unix seconds; matches the
      routing/quota-table convention (the user-facing TEXT-timestamp
      tables use ISO-8601, but the misc-API uploads table is closer
      to the routing-spec surface than to the chat surface).
    """

    id: int
    sha256: str
    filename: str
    mime_type: str
    size: int
    created_at: int

    def __post_init__(self) -> None:
        if self.id < 0:
            raise ValueError(f"UploadRow.id must be ≥ 0 (got {self.id})")
        if len(self.sha256) != _SHA256_HEX_LENGTH:
            raise ValueError(
                f"UploadRow.sha256 must be {_SHA256_HEX_LENGTH} hex chars (got {len(self.sha256)})"
            )
        if not self.filename:
            raise ValueError("UploadRow.filename must be non-empty")
        if len(self.filename) > UPLOAD_FILENAME_MAX_LENGTH:
            raise ValueError(f"UploadRow.filename exceeds {UPLOAD_FILENAME_MAX_LENGTH} chars")
        if len(self.mime_type) > UPLOAD_MIME_TYPE_MAX_LENGTH:
            raise ValueError(f"UploadRow.mime_type exceeds {UPLOAD_MIME_TYPE_MAX_LENGTH} chars")
        if self.size < 0:
            raise ValueError(f"UploadRow.size must be ≥ 0 (got {self.size})")
        if self.created_at < 0:
            raise ValueError(f"UploadRow.created_at must be ≥ 0 (got {self.created_at})")


def _now_unix() -> int:
    """Current wall-clock as unix seconds (UTC)."""
    return int(datetime.now(tz=UTC).timestamp())


def _row_to_upload(row: aiosqlite.Row) -> UploadRow:
    """Materialise an ``aiosqlite.Row`` into an :class:`UploadRow`."""
    return UploadRow(
        id=int(row["id"]),
        sha256=str(row["sha256"]),
        filename=str(row["filename"]),
        mime_type=str(row["mime_type"]),
        size=int(row["size"]),
        created_at=int(row["created_at"]),
    )


async def insert_or_get(
    conn: aiosqlite.Connection,
    *,
    sha256: str,
    filename: str,
    mime_type: str,
    size: int,
) -> UploadRow:
    """Content-addressed insert.

    Returns the existing row when the sha256 already exists in the
    table (the upload was already stored — the on-disk body is
    identical by definition). Otherwise inserts a new row and returns
    it. Idempotent under concurrent re-upload of the same body.
    """
    if len(sha256) != _SHA256_HEX_LENGTH:
        raise ValueError(f"sha256 must be {_SHA256_HEX_LENGTH} hex chars (got {len(sha256)})")
    existing = await get_by_sha256(conn, sha256)
    if existing is not None:
        return existing
    now = _now_unix()
    cursor = await conn.execute(
        "INSERT INTO uploads (sha256, filename, mime_type, size, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (sha256, filename, mime_type, size, now),
    )
    await conn.commit()
    new_row_id = cursor.lastrowid
    if new_row_id is None:  # pragma: no cover — sqlite always sets lastrowid on INSERT
        raise RuntimeError("INSERT returned no lastrowid")
    return UploadRow(
        id=int(new_row_id),
        sha256=sha256,
        filename=filename,
        mime_type=mime_type,
        size=size,
        created_at=now,
    )


async def get(conn: aiosqlite.Connection, upload_id: int) -> UploadRow | None:
    """Fetch one row by id; ``None`` if absent."""
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        "SELECT id, sha256, filename, mime_type, size, created_at FROM uploads WHERE id = ?",
        (upload_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return _row_to_upload(row)


async def get_by_sha256(conn: aiosqlite.Connection, sha256: str) -> UploadRow | None:
    """Fetch one row by sha256; ``None`` if absent."""
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        "SELECT id, sha256, filename, mime_type, size, created_at FROM uploads WHERE sha256 = ?",
        (sha256,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return _row_to_upload(row)


async def list_all(
    conn: aiosqlite.Connection,
    *,
    limit: int = UPLOADS_LIST_DEFAULT_LIMIT,
) -> list[UploadRow]:
    """List uploads newest-first, capped at ``limit``.

    Per arch §1.1.5 the route layer caps user-supplied ``limit`` at
    :data:`bearings.config.constants.UPLOADS_LIST_MAX_LIMIT`; this
    helper enforces the same ceiling defensively so a direct caller
    cannot bypass the wire-shape budget.
    """
    if limit <= 0:
        raise ValueError(f"limit must be > 0 (got {limit})")
    bounded = min(limit, UPLOADS_LIST_MAX_LIMIT)
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        "SELECT id, sha256, filename, mime_type, size, created_at "
        "FROM uploads ORDER BY created_at DESC, id DESC LIMIT ?",
        (bounded,),
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_upload(row) for row in rows]


async def list_all_sha256s(conn: aiosqlite.Connection) -> frozenset[str]:
    """Return the set of every sha256 digest recorded in the uploads table.

    Unlike :func:`list_all` there is no row-count cap — the GC sweep
    must see the complete set to distinguish orphaned on-disk bodies
    (digests not present here) from valid ones.
    """
    async with conn.execute("SELECT sha256 FROM uploads") as cur:
        rows = await cur.fetchall()
    return frozenset(str(row[0]) for row in rows)


async def list_all_rows_for_gc(conn: aiosqlite.Connection) -> list[UploadRow]:
    """Return every upload row ordered oldest-first for the GC reverse sweep.

    The GC reverse pass checks each row's on-disk body; it needs the
    full table (no limit) so a long-running instance with many uploads
    does not silently skip older rows.
    """
    conn.row_factory = aiosqlite.Row
    async with conn.execute(
        "SELECT id, sha256, filename, mime_type, size, created_at "
        "FROM uploads ORDER BY created_at ASC, id ASC"
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_upload(row) for row in rows]


async def delete(conn: aiosqlite.Connection, upload_id: int) -> bool:
    """Remove the row by id; returns ``True`` if a row was removed.

    The on-disk body is the agent layer's concern (see
    :func:`bearings.agent.uploads.delete_bytes`) — the route handler
    sequences the two calls. This separation keeps the DB module free
    of filesystem syscalls per arch §3 layer rules.
    """
    cursor = await conn.execute(
        "DELETE FROM uploads WHERE id = ?",
        (upload_id,),
    )
    await conn.commit()
    return (cursor.rowcount or 0) > 0


__all__ = [
    "UploadRow",
    "delete",
    "get",
    "get_by_sha256",
    "insert_or_get",
    "list_all",
    "list_all_rows_for_gc",
    "list_all_sha256s",
]
