"""Tests for :func:`bearings.agent.tags.resolve_tag_memory_blocks`.

Covers the per-turn DB-memory loader added for feature-7-002: the
agent loop now reads enabled ``tag_memories`` rows on every worker
spawn so edits take effect on the next prompt without a runner
respawn.

References:

* ``docs/behavior/memories.md`` — memory body is documented as
  "the prompt-fragment text the assembler injects".
* ``docs/architecture-v1.md`` §6.3 — "Layered system-prompt assembler
  with per-turn re-read".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.tags import resolve_tag_memory_blocks
from bearings.config.constants import SESSION_KIND_CHAT
from bearings.db import memories as memories_db
from bearings.db import sessions as sessions_db
from bearings.db import tags as tags_db
from bearings.db.connection import load_schema


@pytest.fixture
async def conn(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        await load_schema(connection)
        yield connection


# ---------------------------------------------------------------------------
# resolve_tag_memory_blocks
# ---------------------------------------------------------------------------


async def test_no_tags_returns_empty_tuple(conn: aiosqlite.Connection) -> None:
    """Session with no tags → empty tuple."""
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp", model="sonnet"
    )
    result = await resolve_tag_memory_blocks(conn, session.id)
    assert result == ()


async def test_tag_with_no_memories_returns_empty_tuple(conn: aiosqlite.Connection) -> None:
    """Tag attached to session but with no memories → empty tuple."""
    tag = await tags_db.create(conn, name="empty-tag", color=None, working_dir=None)
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp", model="sonnet"
    )
    await tags_db.attach(conn, session_id=session.id, tag_id=tag.id)
    result = await resolve_tag_memory_blocks(conn, session.id)
    assert result == ()


async def test_enabled_memories_returned(conn: aiosqlite.Connection) -> None:
    """Enabled memories for an attached tag are included in the tuple."""
    tag = await tags_db.create(conn, name="my-tag", color=None, working_dir=None)
    await memories_db.create(conn, tag_id=tag.id, title="A", body="Body A.", enabled=True)
    await memories_db.create(conn, tag_id=tag.id, title="B", body="Body B.", enabled=True)

    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp", model="sonnet"
    )
    await tags_db.attach(conn, session_id=session.id, tag_id=tag.id)

    result = await resolve_tag_memory_blocks(conn, session.id)
    assert "Body A." in result
    assert "Body B." in result
    assert len(result) == 2


async def test_disabled_memories_excluded(conn: aiosqlite.Connection) -> None:
    """Memories with ``enabled=False`` are excluded from the tuple."""
    tag = await tags_db.create(conn, name="mix-tag", color=None, working_dir=None)
    await memories_db.create(conn, tag_id=tag.id, title="On", body="Enabled.", enabled=True)
    await memories_db.create(conn, tag_id=tag.id, title="Off", body="Disabled.", enabled=False)

    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp", model="sonnet"
    )
    await tags_db.attach(conn, session_id=session.id, tag_id=tag.id)

    result = await resolve_tag_memory_blocks(conn, session.id)
    assert result == ("Enabled.",)


async def test_multiple_tags_bodies_ordered_by_precedence(conn: aiosqlite.Connection) -> None:
    """Memories from multiple tags appear in reversed-precedence order.

    ``list_for_session_ordered`` returns project > general > severity;
    ``resolve_tag_memory_blocks`` reverses so the highest-precedence
    tag's memories land last (matching the extras-tuple convention).
    Two general tags are used here so ordering is deterministic via
    sort_order.
    """
    # tag_lo has lower sort_order → higher precedence in list_for_session_ordered
    # → lower precedence in the extras tuple (lands first after reversal)
    tag_lo = await tags_db.create(conn, name="lo-tag", color=None, working_dir=None)
    tag_hi = await tags_db.create(conn, name="hi-tag", color=None, working_dir=None)

    # Set sort_orders so tag_lo is "first" (higher precedence in the DB list)
    # and tag_hi is "second" (lower precedence in the DB list).
    # After reversal: tag_hi bodies appear first, tag_lo bodies appear last.
    await conn.execute("UPDATE tags SET sort_order = 0 WHERE id = ?", (tag_lo.id,))
    await conn.execute("UPDATE tags SET sort_order = 1 WHERE id = ?", (tag_hi.id,))
    await conn.commit()

    await memories_db.create(conn, tag_id=tag_lo.id, title="LO", body="Lo body.")
    await memories_db.create(conn, tag_id=tag_hi.id, title="HI", body="Hi body.")

    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp", model="sonnet"
    )
    await tags_db.attach(conn, session_id=session.id, tag_id=tag_lo.id)
    await tags_db.attach(conn, session_id=session.id, tag_id=tag_hi.id)

    result = await resolve_tag_memory_blocks(conn, session.id)
    assert "Lo body." in result
    assert "Hi body." in result
    # tag_lo has sort_order=0 → comes first in list_for_session_ordered
    # → reversed → tag_hi bodies come first in the tuple (lower-precedence
    # tag first means tag_hi lands before tag_lo when reversed).
    hi_idx = result.index("Hi body.")
    lo_idx = result.index("Lo body.")
    assert hi_idx < lo_idx


async def test_per_turn_reread_reflects_update(conn: aiosqlite.Connection) -> None:
    """Editing a memory body and calling resolve again returns the new body
    without any runner respawn (per-turn re-read contract)."""
    tag = await tags_db.create(conn, name="edit-tag", color=None, working_dir=None)
    memory = await memories_db.create(conn, tag_id=tag.id, title="Rule", body="Original body.")

    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp", model="sonnet"
    )
    await tags_db.attach(conn, session_id=session.id, tag_id=tag.id)

    first = await resolve_tag_memory_blocks(conn, session.id)
    assert first == ("Original body.",)

    await memories_db.update(conn, memory.id, title="Rule", body="Updated body.", enabled=True)

    second = await resolve_tag_memory_blocks(conn, session.id)
    assert second == ("Updated body.",)


async def test_session_not_attached_to_tag_sees_no_memories(
    conn: aiosqlite.Connection,
) -> None:
    """A session with no tags attached sees no memories even if tags with
    memories exist in the DB."""
    tag = await tags_db.create(conn, name="other-tag", color=None, working_dir=None)
    await memories_db.create(conn, tag_id=tag.id, title="X", body="Invisible body.")

    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp", model="sonnet"
    )
    # Deliberately NOT attaching the tag.
    result = await resolve_tag_memory_blocks(conn, session.id)
    assert result == ()
