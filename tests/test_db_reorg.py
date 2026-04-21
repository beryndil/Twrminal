"""Tests for `bearings.db._reorg.move_messages_tx` — Slice 1 of the
Session Reorg plan (`~/.claude/plans/sparkling-triaging-otter.md`).

Covers the primitive's contract: happy path, tool_call follow, orphan
tool_call stays, idempotency, partial input, ValueError branches, and
the updated_at bump on both sides."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from bearings.db.store import (
    attach_tool_calls_to_message,
    create_session,
    delete_reorg_audit,
    delete_session,
    get_session,
    init_db,
    insert_message,
    insert_tool_call_start,
    list_reorg_audits,
    list_sessions,
    list_tool_calls,
    move_messages_tx,
    record_reorg_audit,
)


@pytest_asyncio.fixture
async def conn(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    connection = await init_db(tmp_path / "db.sqlite")
    try:
        yield connection
    finally:
        await connection.close()


async def _mk_session(conn: aiosqlite.Connection, title: str) -> str:
    row = await create_session(
        conn,
        working_dir="/tmp",
        model="claude-sonnet-4-5",
        title=title,
    )
    return str(row["id"])


@pytest.mark.asyncio
async def test_move_happy_path_updates_counts(conn: aiosqlite.Connection) -> None:
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")
    m1 = await insert_message(conn, session_id=src, role="user", content="one")
    m2 = await insert_message(conn, session_id=src, role="user", content="two")
    m3 = await insert_message(conn, session_id=src, role="user", content="three")

    result = await move_messages_tx(
        conn,
        source_id=src,
        target_id=dst,
        message_ids=[m1["id"], m2["id"]],
    )

    assert result.moved == 2
    assert result.tool_calls_followed == 0

    # Derived message_count reflects the move on next read.
    sessions_by_id = {s["id"]: s for s in await list_sessions(conn)}
    assert sessions_by_id[src]["message_count"] == 1
    assert sessions_by_id[dst]["message_count"] == 2

    # Leftover stayed put.
    async with conn.execute(
        "SELECT id FROM messages WHERE session_id = ? ORDER BY created_at",
        (src,),
    ) as cur:
        leftover = [row["id"] async for row in cur]
    assert leftover == [m3["id"]]


@pytest.mark.asyncio
async def test_move_tool_calls_follow_anchored_message(conn: aiosqlite.Connection) -> None:
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")
    msg = await insert_message(conn, session_id=src, role="assistant", content="calls")
    await insert_tool_call_start(
        conn,
        session_id=src,
        tool_call_id="tc-1",
        name="Read",
        input_json="{}",
    )
    await attach_tool_calls_to_message(conn, message_id=msg["id"], tool_call_ids=["tc-1"])

    result = await move_messages_tx(
        conn,
        source_id=src,
        target_id=dst,
        message_ids=[msg["id"]],
    )

    assert result.moved == 1
    assert result.tool_calls_followed == 1
    dst_calls = await list_tool_calls(conn, dst)
    assert [c["id"] for c in dst_calls] == ["tc-1"]
    assert await list_tool_calls(conn, src) == []


@pytest.mark.asyncio
async def test_move_orphan_tool_call_stays_with_source(conn: aiosqlite.Connection) -> None:
    """A tool_call whose message_id is NULL (in-flight or result-
    less) is not anchored to any message, so it stays with the source
    even when unrelated messages move out."""
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")
    msg = await insert_message(conn, session_id=src, role="assistant", content="msg")
    # Orphan tool_call — never attached to a message.
    await insert_tool_call_start(
        conn,
        session_id=src,
        tool_call_id="orphan",
        name="Bash",
        input_json="{}",
    )

    result = await move_messages_tx(
        conn,
        source_id=src,
        target_id=dst,
        message_ids=[msg["id"]],
    )

    assert result.moved == 1
    assert result.tool_calls_followed == 0
    src_calls = await list_tool_calls(conn, src)
    assert [c["id"] for c in src_calls] == ["orphan"]


@pytest.mark.asyncio
async def test_move_is_idempotent(conn: aiosqlite.Connection) -> None:
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")
    msg = await insert_message(conn, session_id=src, role="user", content="x")

    first = await move_messages_tx(conn, source_id=src, target_id=dst, message_ids=[msg["id"]])
    second = await move_messages_tx(conn, source_id=src, target_id=dst, message_ids=[msg["id"]])

    assert first.moved == 1
    assert second.moved == 0
    assert second.tool_calls_followed == 0


@pytest.mark.asyncio
async def test_move_skips_unknown_ids(conn: aiosqlite.Connection) -> None:
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")
    msg = await insert_message(conn, session_id=src, role="user", content="real")

    result = await move_messages_tx(
        conn,
        source_id=src,
        target_id=dst,
        message_ids=[msg["id"], "does-not-exist"],
    )

    assert result.moved == 1


@pytest.mark.asyncio
async def test_move_empty_input_is_noop(conn: aiosqlite.Connection) -> None:
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")

    result = await move_messages_tx(conn, source_id=src, target_id=dst, message_ids=[])

    assert result.moved == 0
    assert result.tool_calls_followed == 0


@pytest.mark.asyncio
async def test_move_rejects_same_session(conn: aiosqlite.Connection) -> None:
    src = await _mk_session(conn, "source")
    with pytest.raises(ValueError, match="must differ"):
        await move_messages_tx(conn, source_id=src, target_id=src, message_ids=["any"])


@pytest.mark.asyncio
async def test_move_rejects_missing_target(conn: aiosqlite.Connection) -> None:
    src = await _mk_session(conn, "source")
    msg = await insert_message(conn, session_id=src, role="user", content="x")
    with pytest.raises(ValueError, match="does not exist"):
        await move_messages_tx(
            conn,
            source_id=src,
            target_id="no-such-session",
            message_ids=[msg["id"]],
        )


@pytest.mark.asyncio
async def test_move_bumps_updated_at_on_both_sides(
    conn: aiosqlite.Connection,
) -> None:
    """Both source and target re-sort to the top of the sidebar after a
    move. Checked by comparing `updated_at` before and after."""
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")
    msg = await insert_message(conn, session_id=src, role="user", content="x")

    src_before = (await get_session(conn, src))["updated_at"]  # type: ignore[index]
    dst_before = (await get_session(conn, dst))["updated_at"]  # type: ignore[index]

    await move_messages_tx(conn, source_id=src, target_id=dst, message_ids=[msg["id"]])

    src_after = (await get_session(conn, src))["updated_at"]  # type: ignore[index]
    dst_after = (await get_session(conn, dst))["updated_at"]  # type: ignore[index]
    assert src_after > src_before
    assert dst_after > dst_before


@pytest.mark.asyncio
async def test_move_noop_does_not_bump_updated_at(
    conn: aiosqlite.Connection,
) -> None:
    """Idempotent re-run with zero actual moves must not touch
    updated_at — otherwise a buggy client looping forever would keep
    re-sorting sessions with no real change."""
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")

    src_before = (await get_session(conn, src))["updated_at"]  # type: ignore[index]
    dst_before = (await get_session(conn, dst))["updated_at"]  # type: ignore[index]

    await move_messages_tx(conn, source_id=src, target_id=dst, message_ids=["ghost"])

    src_after = (await get_session(conn, src))["updated_at"]  # type: ignore[index]
    dst_after = (await get_session(conn, dst))["updated_at"]  # type: ignore[index]
    assert src_after == src_before
    assert dst_after == dst_before


# --- Slice 5: reorg_audits -------------------------------------------------


@pytest.mark.asyncio
async def test_record_and_list_reorg_audits_round_trip(
    conn: aiosqlite.Connection,
) -> None:
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")
    first = await record_reorg_audit(
        conn,
        source_session_id=src,
        target_session_id=dst,
        target_title_snapshot="target",
        message_count=3,
        op="move",
    )
    second = await record_reorg_audit(
        conn,
        source_session_id=src,
        target_session_id=dst,
        target_title_snapshot="target",
        message_count=1,
        op="split",
    )
    await conn.commit()
    assert first > 0 and second > first

    audits = await list_reorg_audits(conn, src)
    assert [a["id"] for a in audits] == [first, second]
    assert [a["op"] for a in audits] == ["move", "split"]
    assert audits[0]["message_count"] == 3
    assert audits[1]["target_title_snapshot"] == "target"


@pytest.mark.asyncio
async def test_reorg_audit_target_nulled_on_target_delete(
    conn: aiosqlite.Connection,
) -> None:
    """`ON DELETE SET NULL` keeps the audit row legible even after the
    target is deleted — the frontend shows the snapshotted title +
    "(deleted session)" instead of losing the audit entry."""
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "gone")
    audit_id = await record_reorg_audit(
        conn,
        source_session_id=src,
        target_session_id=dst,
        target_title_snapshot="gone",
        message_count=2,
        op="merge",
    )
    await conn.commit()
    assert audit_id > 0

    await delete_session(conn, dst)

    audits = await list_reorg_audits(conn, src)
    assert len(audits) == 1
    assert audits[0]["target_session_id"] is None
    assert audits[0]["target_title_snapshot"] == "gone"


@pytest.mark.asyncio
async def test_reorg_audit_cascades_on_source_delete(
    conn: aiosqlite.Connection,
) -> None:
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")
    await record_reorg_audit(
        conn,
        source_session_id=src,
        target_session_id=dst,
        target_title_snapshot="target",
        message_count=1,
        op="move",
    )
    await conn.commit()

    await delete_session(conn, src)

    # Source gone → audit cascades out. Query for the raw row count
    # directly since `list_reorg_audits` filters by source id.
    async with conn.execute("SELECT COUNT(*) FROM reorg_audits") as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row[0] == 0


@pytest.mark.asyncio
async def test_delete_reorg_audit_returns_false_for_missing(
    conn: aiosqlite.Connection,
) -> None:
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")
    audit_id = await record_reorg_audit(
        conn,
        source_session_id=src,
        target_session_id=dst,
        target_title_snapshot="target",
        message_count=1,
        op="move",
    )
    await conn.commit()

    assert await delete_reorg_audit(conn, audit_id) is True
    assert await list_reorg_audits(conn, src) == []
    # Second delete is a no-op, not an error (racing undo clicks).
    assert await delete_reorg_audit(conn, audit_id) is False


@pytest.mark.asyncio
async def test_reorg_audit_rejects_unknown_op(
    conn: aiosqlite.Connection,
) -> None:
    """The CHECK constraint forbids anything outside move/split/merge."""
    src = await _mk_session(conn, "source")
    dst = await _mk_session(conn, "target")
    with pytest.raises(aiosqlite.IntegrityError):
        await record_reorg_audit(
            conn,
            source_session_id=src,
            target_session_id=dst,
            target_title_snapshot="target",
            message_count=1,
            op="archive",  # type: ignore[arg-type]
        )
    await conn.rollback()
