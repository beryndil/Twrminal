"""Analytics DB layer — query module for the Phase 1 analytics tables.

Per ``BEARINGS_ANALYTICS_v1.md`` §4, the analytics schema consists of
five tables:

* :class:`Turn` — per-turn token accounting (``turns`` table).
* :class:`PlugBlock` — unique injected context blocks (``plug_blocks``
  table), content-addressed by sha256.
* :class:`SessionPlugBlock` — join between sessions and plug blocks
  (``session_plug_blocks`` table).
* :class:`BucketSnapshot` — snapshots of ``/usage`` poll results
  (``bucket_snapshots`` table).
* :class:`SuppressedWarning` — user-dismissed plug-length warnings
  (``suppressed_warnings`` table).

This module is the authoritative query surface for those five tables.
No other module in the codebase should issue raw SQL against them.

Timestamp convention: all analytics timestamps are INTEGER unix
milliseconds (spec §4.1 "unix ms"), matching the routing/quota tables.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import aiosqlite

from bearings.config.constants import (
    KNOWN_ANALYTICS_BLOCK_TYPES,
    KNOWN_ANALYTICS_WARNING_TYPES,
)

# ---------------------------------------------------------------------------
# Dataclass row mirrors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Turn:
    """Row mirror for the ``turns`` table.

    Per spec §4.1: one row per Claude API turn, carrying per-model token
    counts.  ``model`` is stored on every row so aggregation queries
    group by model before summing (spec §3.2 tokenizer constraint).
    """

    id: int
    session_id: str
    turn_index: int
    timestamp: int
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("Turn.session_id must be non-empty")
        if not self.model:
            raise ValueError("Turn.model must be non-empty")
        if self.turn_index < 0:
            raise ValueError("Turn.turn_index must be >= 0")
        for field in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
        ):
            val = getattr(self, field)
            if val < 0:
                raise ValueError(f"Turn.{field} must be >= 0")


@dataclass(frozen=True)
class PlugBlock:
    """Row mirror for the ``plug_blocks`` table.

    ``hash`` is the sha256 of the normalised block content and serves as
    the natural deduplication key.  ``id`` is the INTEGER autoincrement
    PK required by the schema convention; FK references from
    ``session_plug_blocks`` and ``suppressed_warnings`` point to
    ``plug_blocks(hash)`` via the UNIQUE constraint.
    """

    id: int
    hash: str
    block_type: str
    content: str
    token_count: int
    token_count_model: str
    first_seen: int
    last_seen: int
    source_path: str | None

    def __post_init__(self) -> None:
        if not self.hash:
            raise ValueError("PlugBlock.hash must be non-empty")
        if self.block_type not in KNOWN_ANALYTICS_BLOCK_TYPES:
            raise ValueError(
                f"PlugBlock.block_type {self.block_type!r} not in KNOWN_ANALYTICS_BLOCK_TYPES"
            )
        if not self.token_count_model:
            raise ValueError("PlugBlock.token_count_model must be non-empty")
        if self.token_count < 0:
            raise ValueError("PlugBlock.token_count must be >= 0")


@dataclass(frozen=True)
class SessionPlugBlock:
    """Row mirror for the ``session_plug_blocks`` join table.

    Records that a specific plug block was injected into a session.
    ``injected_at`` is unix ms at the time of session creation.
    """

    session_id: str
    block_hash: str
    injected_at: int

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("SessionPlugBlock.session_id must be non-empty")
        if not self.block_hash:
            raise ValueError("SessionPlugBlock.block_hash must be non-empty")


@dataclass(frozen=True)
class BucketSnapshot:
    """Row mirror for the ``bucket_snapshots`` table.

    One row per ``/usage`` poll.  All integer fields are nullable because
    the ``/usage`` response shape may omit windows that haven't started yet.
    ``raw_response`` is the full JSON dump for debugging.
    """

    id: int
    timestamp: int
    five_hour_used: int | None
    five_hour_limit: int | None
    weekly_used: int | None
    weekly_limit: int | None
    raw_response: str | None


@dataclass(frozen=True)
class SuppressedWarning:
    """Row mirror for the ``suppressed_warnings`` table.

    When the user dismisses a yellow or red plug-length warning for a
    given block hash, this row prevents re-notification.
    """

    block_hash: str
    warning_type: str
    suppressed_at: int

    def __post_init__(self) -> None:
        if not self.block_hash:
            raise ValueError("SuppressedWarning.block_hash must be non-empty")
        if self.warning_type not in KNOWN_ANALYTICS_WARNING_TYPES:
            raise ValueError(
                f"SuppressedWarning.warning_type {self.warning_type!r} "
                "not in KNOWN_ANALYTICS_WARNING_TYPES"
            )


# ---------------------------------------------------------------------------
# Turn queries
# ---------------------------------------------------------------------------


def _now_ms() -> int:
    """Current unix time in milliseconds."""
    return int(time.time() * 1000)


async def insert_turn(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    turn_index: int,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    timestamp: int | None = None,
) -> Turn:
    """Insert one turn row and return the persisted :class:`Turn`.

    Uses ``INSERT OR IGNORE`` so re-delivery of the same
    ``(session_id, turn_index)`` pair is a no-op (idempotent).  Returns
    the existing row if the IGNORE path fires, matching the
    ``OR IGNORE`` semantics callers depend on.
    """
    ts = timestamp if timestamp is not None else _now_ms()
    await connection.execute(
        "INSERT OR IGNORE INTO turns "
        "(session_id, turn_index, timestamp, model, "
        " input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            turn_index,
            ts,
            model,
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
        ),
    )
    await connection.commit()
    async with connection.execute(
        "SELECT id, session_id, turn_index, timestamp, model, "
        "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens "
        "FROM turns WHERE session_id = ? AND turn_index = ?",
        (session_id, turn_index),
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return Turn(
        id=int(row[0]),
        session_id=str(row[1]),
        turn_index=int(row[2]),
        timestamp=int(row[3]),
        model=str(row[4]),
        input_tokens=int(row[5]),
        output_tokens=int(row[6]),
        cache_read_tokens=int(row[7]),
        cache_creation_tokens=int(row[8]),
    )


async def list_turns_for_session(
    connection: aiosqlite.Connection,
    session_id: str,
) -> list[Turn]:
    """Return all turns for ``session_id``, ordered by turn_index ascending."""
    rows = await connection.execute_fetchall(
        "SELECT id, session_id, turn_index, timestamp, model, "
        "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens "
        "FROM turns WHERE session_id = ? ORDER BY turn_index ASC",
        (session_id,),
    )
    return [
        Turn(
            id=int(r[0]),
            session_id=str(r[1]),
            turn_index=int(r[2]),
            timestamp=int(r[3]),
            model=str(r[4]),
            input_tokens=int(r[5]),
            output_tokens=int(r[6]),
            cache_read_tokens=int(r[7]),
            cache_creation_tokens=int(r[8]),
        )
        for r in rows
    ]


async def list_turns(
    connection: aiosqlite.Connection,
    *,
    cutoff_ms: int,
    session_id: str | None = None,
) -> list[Turn]:
    """Return turns at or after ``cutoff_ms`` (unix ms), optionally for one session.

    Ordered by timestamp ascending then turn_index ascending so
    time-series consumers receive rows in chronological order.

    Per spec §3.2: never aggregate token counts across models without
    grouping by model first — callers are responsible for that
    constraint.  This query returns raw rows so the caller can slice
    by model as needed.

    Args:
        connection: open aiosqlite connection.
        cutoff_ms: earliest timestamp to include (unix milliseconds).
        session_id: when set, only rows for this session are returned.
    """
    if session_id is not None:
        rows = await connection.execute_fetchall(
            "SELECT id, session_id, turn_index, timestamp, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens "
            "FROM turns "
            "WHERE session_id = ? AND timestamp >= ? "
            "ORDER BY timestamp ASC, turn_index ASC",
            (session_id, cutoff_ms),
        )
    else:
        rows = await connection.execute_fetchall(
            "SELECT id, session_id, turn_index, timestamp, model, "
            "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens "
            "FROM turns "
            "WHERE timestamp >= ? "
            "ORDER BY timestamp ASC, turn_index ASC",
            (cutoff_ms,),
        )
    return [
        Turn(
            id=int(r[0]),
            session_id=str(r[1]),
            turn_index=int(r[2]),
            timestamp=int(r[3]),
            model=str(r[4]),
            input_tokens=int(r[5]),
            output_tokens=int(r[6]),
            cache_read_tokens=int(r[7]),
            cache_creation_tokens=int(r[8]),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# PlugBlock queries
# ---------------------------------------------------------------------------


async def upsert_plug_block(
    connection: aiosqlite.Connection,
    *,
    hash: str,
    block_type: str,
    content: str,
    token_count: int,
    token_count_model: str,
    source_path: str | None = None,
    now: int | None = None,
) -> PlugBlock:
    """Insert a plug block row or update ``last_seen`` if it already exists.

    Per spec §5.1: "Insert into plug_blocks with INSERT OR IGNORE. If
    the row exists, update last_seen."  Token count is only stored on
    first insert (the cost is in the API hit, not local accounting).
    """
    ts = now if now is not None else _now_ms()
    await connection.execute(
        "INSERT INTO plug_blocks "
        "(hash, block_type, content, token_count, token_count_model, "
        " first_seen, last_seen, source_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(hash) DO UPDATE SET last_seen = excluded.last_seen",
        (hash, block_type, content, token_count, token_count_model, ts, ts, source_path),
    )
    await connection.commit()
    async with connection.execute(
        "SELECT id, hash, block_type, content, token_count, token_count_model, "
        "first_seen, last_seen, source_path FROM plug_blocks WHERE hash = ?",
        (hash,),
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return PlugBlock(
        id=int(row[0]),
        hash=str(row[1]),
        block_type=str(row[2]),
        content=str(row[3]),
        token_count=int(row[4]),
        token_count_model=str(row[5]),
        first_seen=int(row[6]),
        last_seen=int(row[7]),
        source_path=str(row[8]) if row[8] is not None else None,
    )


async def get_plug_block(
    connection: aiosqlite.Connection,
    hash: str,
) -> PlugBlock | None:
    """Return the :class:`PlugBlock` for ``hash``, or ``None`` if absent."""
    async with connection.execute(
        "SELECT id, hash, block_type, content, token_count, token_count_model, "
        "first_seen, last_seen, source_path FROM plug_blocks WHERE hash = ?",
        (hash,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return PlugBlock(
        id=int(row[0]),
        hash=str(row[1]),
        block_type=str(row[2]),
        content=str(row[3]),
        token_count=int(row[4]),
        token_count_model=str(row[5]),
        first_seen=int(row[6]),
        last_seen=int(row[7]),
        source_path=str(row[8]) if row[8] is not None else None,
    )


async def search_plug_blocks_fts(
    connection: aiosqlite.Connection,
    query: str,
    limit: int = 20,
) -> list[PlugBlock]:
    """Return plug blocks whose content matches the FTS5 ``query`` string.

    Uses the ``plug_blocks_fts`` virtual table (spec §4.2).  Results are
    ranked by FTS5's default BM25 relevance.
    """
    rows = await connection.execute_fetchall(
        "SELECT pb.id, pb.hash, pb.block_type, pb.content, pb.token_count, "
        "pb.token_count_model, pb.first_seen, pb.last_seen, pb.source_path "
        "FROM plug_blocks_fts fts "
        "JOIN plug_blocks pb ON pb.rowid = fts.rowid "
        "WHERE plug_blocks_fts MATCH ? "
        "ORDER BY rank "
        "LIMIT ?",
        (query, limit),
    )
    return [
        PlugBlock(
            id=int(r[0]),
            hash=str(r[1]),
            block_type=str(r[2]),
            content=str(r[3]),
            token_count=int(r[4]),
            token_count_model=str(r[5]),
            first_seen=int(r[6]),
            last_seen=int(r[7]),
            source_path=str(r[8]) if r[8] is not None else None,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# SessionPlugBlock queries
# ---------------------------------------------------------------------------


async def record_session_plug_blocks(
    connection: aiosqlite.Connection,
    session_id: str,
    block_hashes: list[str],
    injected_at: int | None = None,
) -> list[SessionPlugBlock]:
    """Record that ``block_hashes`` were injected into ``session_id``.

    Uses ``INSERT OR IGNORE`` so a re-run of session setup (e.g. after a
    compact) does not duplicate rows.
    """
    ts = injected_at if injected_at is not None else _now_ms()
    result: list[SessionPlugBlock] = []
    for bh in block_hashes:
        await connection.execute(
            "INSERT OR IGNORE INTO session_plug_blocks "
            "(session_id, block_hash, injected_at) VALUES (?, ?, ?)",
            (session_id, bh, ts),
        )
        result.append(SessionPlugBlock(session_id=session_id, block_hash=bh, injected_at=ts))
    await connection.commit()
    return result


async def list_session_plug_blocks(
    connection: aiosqlite.Connection,
    session_id: str,
) -> list[SessionPlugBlock]:
    """Return all plug block links for ``session_id``."""
    rows = await connection.execute_fetchall(
        "SELECT session_id, block_hash, injected_at FROM session_plug_blocks WHERE session_id = ?",
        (session_id,),
    )
    return [
        SessionPlugBlock(
            session_id=str(r[0]),
            block_hash=str(r[1]),
            injected_at=int(r[2]),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# BucketSnapshot queries
# ---------------------------------------------------------------------------


async def insert_bucket_snapshot(
    connection: aiosqlite.Connection,
    *,
    five_hour_used: int | None = None,
    five_hour_limit: int | None = None,
    weekly_used: int | None = None,
    weekly_limit: int | None = None,
    raw_response: str | None = None,
    timestamp: int | None = None,
) -> BucketSnapshot:
    """Insert one bucket snapshot row and return the persisted object."""
    ts = timestamp if timestamp is not None else _now_ms()
    cursor = await connection.execute(
        "INSERT INTO bucket_snapshots "
        "(timestamp, five_hour_used, five_hour_limit, weekly_used, weekly_limit, raw_response) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ts, five_hour_used, five_hour_limit, weekly_used, weekly_limit, raw_response),
    )
    await connection.commit()
    row_id = cursor.lastrowid
    return BucketSnapshot(
        id=int(row_id),  # type: ignore[arg-type]
        timestamp=ts,
        five_hour_used=five_hour_used,
        five_hour_limit=five_hour_limit,
        weekly_used=weekly_used,
        weekly_limit=weekly_limit,
        raw_response=raw_response,
    )


async def get_latest_bucket_snapshot(
    connection: aiosqlite.Connection,
) -> BucketSnapshot | None:
    """Return the most recent bucket snapshot, or ``None`` if the table is empty."""
    async with connection.execute(
        "SELECT id, timestamp, five_hour_used, five_hour_limit, "
        "weekly_used, weekly_limit, raw_response "
        "FROM bucket_snapshots ORDER BY timestamp DESC LIMIT 1",
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    return BucketSnapshot(
        id=int(row[0]),
        timestamp=int(row[1]),
        five_hour_used=int(row[2]) if row[2] is not None else None,
        five_hour_limit=int(row[3]) if row[3] is not None else None,
        weekly_used=int(row[4]) if row[4] is not None else None,
        weekly_limit=int(row[5]) if row[5] is not None else None,
        raw_response=str(row[6]) if row[6] is not None else None,
    )


# ---------------------------------------------------------------------------
# SuppressedWarning queries
# ---------------------------------------------------------------------------


async def suppress_warning(
    connection: aiosqlite.Connection,
    *,
    block_hash: str,
    warning_type: str,
    suppressed_at: int | None = None,
) -> SuppressedWarning:
    """Record that the user dismissed ``warning_type`` for ``block_hash``.

    Uses ``INSERT OR IGNORE`` so a double-click on "don't show again" is
    idempotent.
    """
    ts = suppressed_at if suppressed_at is not None else _now_ms()
    await connection.execute(
        "INSERT OR IGNORE INTO suppressed_warnings "
        "(block_hash, warning_type, suppressed_at) VALUES (?, ?, ?)",
        (block_hash, warning_type, ts),
    )
    await connection.commit()
    async with connection.execute(
        "SELECT block_hash, warning_type, suppressed_at "
        "FROM suppressed_warnings WHERE block_hash = ? AND warning_type = ?",
        (block_hash, warning_type),
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return SuppressedWarning(
        block_hash=str(row[0]),
        warning_type=str(row[1]),
        suppressed_at=int(row[2]),
    )


async def is_warning_suppressed(
    connection: aiosqlite.Connection,
    block_hash: str,
    warning_type: str,
) -> bool:
    """Return ``True`` if the warning has been suppressed for this block."""
    async with connection.execute(
        "SELECT 1 FROM suppressed_warnings WHERE block_hash = ? AND warning_type = ?",
        (block_hash, warning_type),
    ) as cursor:
        row = await cursor.fetchone()
    return row is not None


__all__ = [
    "BucketSnapshot",
    "PlugBlock",
    "SessionPlugBlock",
    "SuppressedWarning",
    "Turn",
    "get_latest_bucket_snapshot",
    "get_plug_block",
    "insert_bucket_snapshot",
    "insert_turn",
    "is_warning_suppressed",
    "list_session_plug_blocks",
    "list_turns",
    "list_turns_for_session",
    "record_session_plug_blocks",
    "search_plug_blocks_fts",
    "suppress_warning",
    "upsert_plug_block",
]
