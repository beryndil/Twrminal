from __future__ import annotations

from pathlib import Path

import pytest

from twrminal.db.store import create_session, create_tag, init_db


@pytest.mark.asyncio
async def test_0007_creates_projects_and_memories_tables(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            tables = {row[0] async for row in cursor}
        assert {"projects", "tag_memories"}.issubset(tables)
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sessions_project'"
        ) as cursor:
            assert await cursor.fetchone() is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_0007_adds_project_id_and_session_instructions_columns(
    tmp_path: Path,
) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        async with conn.execute("PRAGMA table_info(sessions)") as cursor:
            cols = {row[1] async for row in cursor}
        assert "project_id" in cols
        assert "session_instructions" in cols
    finally:
        await conn.close()


async def _insert_project(conn, name: str) -> int:
    cursor = await conn.execute(
        "INSERT INTO projects (name, created_at, updated_at) "
        "VALUES (?, datetime('now'), datetime('now'))",
        (name,),
    )
    await conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


@pytest.mark.asyncio
async def test_project_delete_nulls_session_project_id(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        pid = await _insert_project(conn, "Twrminal")
        await conn.execute("UPDATE sessions SET project_id = ? WHERE id = ?", (pid, sess["id"]))
        await conn.commit()
        await conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
        await conn.commit()
        async with conn.execute(
            "SELECT project_id FROM sessions WHERE id = ?", (sess["id"],)
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_tag_delete_cascades_tag_memories(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        tag = await create_tag(conn, name="infra")
        await conn.execute(
            "INSERT INTO tag_memories (tag_id, content, updated_at) VALUES (?, ?, datetime('now'))",
            (tag["id"], "Prefer nftables over iptables."),
        )
        await conn.commit()
        await conn.execute("DELETE FROM tags WHERE id = ?", (tag["id"],))
        await conn.commit()
        async with conn.execute(
            "SELECT 1 FROM tag_memories WHERE tag_id = ?", (tag["id"],)
        ) as cursor:
            assert await cursor.fetchone() is None
    finally:
        await conn.close()
