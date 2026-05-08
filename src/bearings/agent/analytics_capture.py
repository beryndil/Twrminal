"""Analytics Phase 2 — agent-side capture module.

Writes to the Phase 1 analytics tables (``turns``, ``plug_blocks``,
``session_plug_blocks``) on every SDK turn boundary and session
creation event.  This module is the sole writer for those tables from
the agent layer; read-path queries stay in :mod:`bearings.db.analytics`.

Wire-in points
--------------
* :func:`capture_turn` — called from ``agent/sdk_loop.py``
  ``_finish_turn()`` after every completed SDK turn.
* :func:`capture_session_plug` — called from
  ``agent/session_bootstrap.py`` ``setup()`` once per session
  materialisation (first worker spawn and every subsequent supervisor
  respawn; :func:`bearings.db.analytics.record_session_plug_blocks`
  uses ``INSERT OR IGNORE`` so respawns are no-ops).

Idempotency
-----------
Both public coroutines are safe to call multiple times for the same
logical event:

* :func:`capture_turn` derives ``turn_index`` from
  ``COUNT(*) FROM turns WHERE session_id = ?`` then delegates to
  :func:`bearings.db.analytics.insert_turn` which uses
  ``INSERT OR IGNORE`` on ``UNIQUE(session_id, turn_index)`` — a
  re-delivered turn is a no-op.
* :func:`capture_session_plug` delegates to :func:`upsert_plug_block`
  (``INSERT … ON CONFLICT DO UPDATE SET last_seen``) and
  :func:`record_session_plug_blocks` (``INSERT OR IGNORE``) — a
  re-run of session setup creates no duplicate rows.

Token counting
--------------
Token counts use ``max(0, len(normalized_content) // 4)`` — the same
approximation as :mod:`bearings.agent.prompt_assembler`.  This avoids a
tokenizer dependency while staying consistent across all layers that
estimate plug sizes.  The ``token_count_model`` column records which
model the estimate is attributed to.

Failure isolation
-----------------
Both public coroutines catch and log every exception from the DB layer
rather than propagating.  An analytics write failure must never crash
the agent loop or the session bootstrap.

References
----------
* ``BEARINGS_ANALYTICS_v1.md`` §4.1 (schema), §5 (plug capture),
  §6 (bucket attribution context).
* ``docs/architecture-v1.md`` §1.1.4 (module home: ``agent/``).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import os.path
from collections.abc import Sequence
from dataclasses import dataclass

import aiosqlite

from bearings.config.constants import (
    ANALYTICS_BLOCK_TYPE_CLAUDE_MD,
    ANALYTICS_BLOCK_TYPE_TAG_MEMORY,
)
from bearings.db.analytics import (
    insert_turn,
    record_session_plug_blocks,
    upsert_plug_block,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaptureBlock:
    """One plug block descriptor for :func:`capture_session_plug`.

    Attributes:
        block_type: One of the ``ANALYTICS_BLOCK_TYPE_*`` constants from
            :mod:`bearings.config.constants` (e.g. ``"claude_md"``,
            ``"tag_memory"``).
        content: Raw block text — normalisation happens inside
            :func:`capture_session_plug` before hashing.
        source_path: Filesystem path for file-sourced blocks (e.g.
            ``/home/dave/.claude/CLAUDE.md``).  ``None`` for in-DB
            content (tag memories) or blocks whose source file is not
            directly accessible.
    """

    block_type: str
    content: str
    source_path: str | None = None


# ---------------------------------------------------------------------------
# Content normalisation, hashing, and token estimation
# ---------------------------------------------------------------------------


def normalize_block_content(content: str) -> str:
    """Normalise *content* for hash-based deduplication per spec §5.1.

    Steps applied in order:

    1. Normalise line endings to ``\\n`` (``\\r\\n`` → ``\\n``,
       bare ``\\r`` → ``\\n``).
    2. Strip trailing whitespace from every line.
    3. Trim leading and trailing blank lines.

    The content is NOT lowercased or otherwise reformatted — diff
    fidelity requires verbatim content.

    Args:
        content: Raw block text.

    Returns:
        Normalised string.  May be empty if *content* consisted
        entirely of whitespace or was already empty.
    """
    unified = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = unified.split("\n")
    stripped = [line.rstrip() for line in lines]
    return "\n".join(stripped).strip("\n")


def hash_block(normalized_content: str) -> str:
    """Return the sha256 hex digest of *normalized_content* (spec §5.1).

    Args:
        normalized_content: Output of :func:`normalize_block_content`.

    Returns:
        64-character lowercase hex string.
    """
    return hashlib.sha256(normalized_content.encode()).hexdigest()


def estimate_tokens(content: str) -> int:
    """Approximate token count as ``max(0, len(content) // 4)``.

    Consistent with :mod:`bearings.agent.prompt_assembler`.  The
    ``token_count_model`` column on ``plug_blocks`` records which model
    the estimate is attributed to (spec §5.3).

    Args:
        content: Normalised block text.

    Returns:
        Non-negative integer.
    """
    return max(0, len(content) // 4)


# ---------------------------------------------------------------------------
# Project CLAUDE.md walk-up helper (sync — no async I/O inside async fn)
# ---------------------------------------------------------------------------


def collect_project_claude_md_blocks(working_dir: str) -> list[CaptureBlock]:
    """Walk from *working_dir* toward the filesystem root collecting CLAUDE.md files.

    Returns one :class:`CaptureBlock` per readable ``CLAUDE.md`` found,
    with ``block_type='claude_md'`` and an absolute ``source_path``.
    Walk order is innermost directory first (matches
    :func:`bearings.agent.prompt_assembler._walk_up_claude_md`).

    Missing files, unreadable files, and path errors are silently
    skipped.  Returns an empty list when *working_dir* is empty.

    This is a pure sync function so the ASYNC240 lint rule (no blocking
    I/O inside ``async def``) is not triggered when called from an async
    bootstrap — the same pattern used in
    :mod:`bearings.agent.prompt_assembler`.

    Args:
        working_dir: Absolute or ``~``-prefixed directory path.

    Returns:
        Ordered list of :class:`CaptureBlock` instances.
    """
    if not working_dir:
        return []
    blocks: list[CaptureBlock] = []
    try:
        current = os.path.abspath(os.path.expanduser(working_dir))
    except (ValueError, OSError):
        return blocks
    visited: set[str] = set()
    while True:
        if current in visited:
            break
        visited.add(current)
        candidate = os.path.join(current, "CLAUDE.md")
        if os.path.isfile(candidate):
            with contextlib.suppress(OSError, UnicodeDecodeError):
                with open(candidate, encoding="utf-8") as fh:
                    body = fh.read()
                blocks.append(
                    CaptureBlock(
                        block_type=ANALYTICS_BLOCK_TYPE_CLAUDE_MD,
                        content=body,
                        source_path=os.path.abspath(candidate),
                    )
                )
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return blocks


def assemble_plug_blocks(
    working_dir: str,
    extra_claude_md_blocks: tuple[str, ...],
    extra_memory_blocks: tuple[str, ...],
    session_instructions: str | None,
) -> list[CaptureBlock]:
    """Assemble the full :class:`CaptureBlock` list for a session.

    Combines all plug sources in the same order the system-prompt
    assembler uses (project CLAUDE.md walk-up, then tag CLAUDE.mds,
    then tag memories, then session instructions).

    Called from ``agent/session_bootstrap.py`` ``setup()`` immediately
    before :func:`capture_session_plug` so the bootstrap has a single
    call site for "what blocks does this session inject?".

    Args:
        working_dir: Expanded absolute working directory for the session
            (used by :func:`collect_project_claude_md_blocks` to walk
            up the CLAUDE.md chain).
        extra_claude_md_blocks: Tag CLAUDE.md content strings returned
            by :func:`bearings.agent.tags.resolve_claude_md_blocks`.
            Source paths are not available from that function; blocks
            are captured with ``source_path=None``.
        extra_memory_blocks: Tag memory bodies returned by
            :func:`bearings.agent.tags.resolve_tag_memory_blocks`.
        session_instructions: The session row's ``session_instructions``
            column value, or ``None`` if absent.

    Returns:
        Ordered list of :class:`CaptureBlock` instances covering all
        plug sources.
    """
    from bearings.config.constants import ANALYTICS_BLOCK_TYPE_SYSTEM_ADDITION

    blocks: list[CaptureBlock] = []
    # Layer: project CLAUDE.md walk-up (with source paths).
    blocks.extend(collect_project_claude_md_blocks(working_dir))
    # Layer: tag CLAUDE.md files (content only; resolve_claude_md_blocks
    # does not return source paths, so captured with source_path=None).
    for content in extra_claude_md_blocks:
        blocks.append(
            CaptureBlock(
                block_type=ANALYTICS_BLOCK_TYPE_CLAUDE_MD,
                content=content,
                source_path=None,
            )
        )
    # Layer: tag memories.
    for content in extra_memory_blocks:
        blocks.append(
            CaptureBlock(
                block_type=ANALYTICS_BLOCK_TYPE_TAG_MEMORY,
                content=content,
                source_path=None,
            )
        )
    # Layer: session instructions.
    if session_instructions:
        stripped = session_instructions.strip()
        if stripped:
            blocks.append(
                CaptureBlock(
                    block_type=ANALYTICS_BLOCK_TYPE_SYSTEM_ADDITION,
                    content=stripped,
                    source_path=None,
                )
            )
    return blocks


# ---------------------------------------------------------------------------
# Public capture coroutines
# ---------------------------------------------------------------------------


async def capture_session_plug(
    db: aiosqlite.Connection,
    session_id: str,
    model: str,
    blocks: Sequence[CaptureBlock],
) -> None:
    """Upsert plug blocks and link them to *session_id* (spec §5.1).

    For each block in *blocks*:

    1. Normalise content → compute sha256 hash.
    2. ``INSERT … ON CONFLICT DO UPDATE SET last_seen`` into
       ``plug_blocks``.  First call stores ``token_count`` and
       ``token_count_model``; subsequent calls only touch ``last_seen``.
    3. Collect the hash.

    After iterating all blocks, ``INSERT OR IGNORE`` the collected
    hashes into ``session_plug_blocks`` (one row per
    ``(session_id, block_hash)`` pair).

    Empty blocks (after normalisation) are silently skipped.  Individual
    upsert failures are caught and logged; the remaining blocks continue
    normally.

    Args:
        db: Open aiosqlite connection.
        session_id: The session to link blocks to.
        model: Executor model for this session (stored as
            ``token_count_model`` on first insert of each block).
        blocks: Ordered sequence of :class:`CaptureBlock` instances.
    """
    hashes: list[str] = []
    for block in blocks:
        normalized = normalize_block_content(block.content)
        if not normalized:
            continue
        block_hash = hash_block(normalized)
        token_count = estimate_tokens(normalized)
        try:
            await upsert_plug_block(
                db,
                hash=block_hash,
                block_type=block.block_type,
                content=normalized,
                token_count=token_count,
                token_count_model=model,
                source_path=block.source_path,
            )
            hashes.append(block_hash)
        except Exception:
            _log.warning(
                "analytics_capture: upsert_plug_block failed hash=%.8s session=%s",
                block_hash,
                session_id,
                exc_info=True,
            )
    if not hashes:
        return
    try:
        await record_session_plug_blocks(db, session_id, hashes)
    except Exception:
        _log.warning(
            "analytics_capture: record_session_plug_blocks failed session=%s blocks=%d",
            session_id,
            len(hashes),
            exc_info=True,
        )


async def capture_turn(
    db: aiosqlite.Connection,
    session_id: str,
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> None:
    """Insert one ``turns`` row for the completed SDK turn (spec §4.1).

    ``turn_index`` is derived from ``COUNT(*) FROM turns WHERE
    session_id = ?`` at call time.  Because each session has at most one
    active SDK worker loop, this count is safe without a transaction
    lock.  :func:`bearings.db.analytics.insert_turn` uses
    ``INSERT OR IGNORE`` on ``UNIQUE(session_id, turn_index)`` so a
    re-delivered turn is a no-op.

    All exceptions from the DB layer are caught and logged so an
    analytics failure never crashes the agent loop.

    Args:
        db: Open aiosqlite connection.
        session_id: The session this turn belongs to.
        model: Executor model (e.g. ``"claude-opus-4-7"``).
        input_tokens: Total input tokens for this turn (executor +
            advisor combined, since the ``turns`` table has one row per
            turn — not one per model).
        output_tokens: Total output tokens for this turn.
        cache_read_tokens: Cache-read tokens for this turn.
        cache_creation_tokens: Cache-creation tokens for this turn.
    """
    try:
        async with db.execute(
            "SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)
        ) as cursor:
            count_row = await cursor.fetchone()
        turn_index = int(count_row[0]) if count_row is not None else 0
        await insert_turn(
            db,
            session_id=session_id,
            turn_index=turn_index,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )
    except Exception:
        _log.warning(
            "analytics_capture: capture_turn failed session=%s",
            session_id,
            exc_info=True,
        )


__all__ = [
    "CaptureBlock",
    "assemble_plug_blocks",
    "capture_session_plug",
    "capture_turn",
    "collect_project_claude_md_blocks",
    "estimate_tokens",
    "hash_block",
    "normalize_block_content",
]
