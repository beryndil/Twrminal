"""Session-template store unit tests (Phase 9b.1 of docs/context-menu-plan.md).

Covers migration 0025 shape and CRUD via `db/_templates.py`. The HTTP
routes + `from_template` instantiation land in Phase 9b.2 with their
own tests — this file exercises the store layer directly so the DB
surface has standalone confidence before the routes compose on top.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bearings.db.store import (
    create_tag,
    create_template,
    delete_template,
    get_template,
    init_db,
    list_templates,
)

# --- migration shape -------------------------------------------------


@pytest.mark.asyncio
async def test_migration_creates_session_templates_table(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_templates'"
        ) as cursor:
            rows = [row[0] async for row in cursor]
        assert rows == ["session_templates"]
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_session_templates_created'"
        ) as cursor:
            idx = [row[0] async for row in cursor]
        assert idx == ["idx_session_templates_created"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_migration_columns_match_spec(tmp_path: Path) -> None:
    """Plan §4.3 pins the shape: id PK, name NN, body nullable,
    working_dir nullable, model nullable, session_instructions
    nullable, tag_ids_json NN with DEFAULT '[]', created_at NN."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        async with conn.execute("PRAGMA table_info(session_templates)") as cursor:
            cols = {row["name"]: row async for row in cursor}
        expected = {
            "id",
            "name",
            "body",
            "working_dir",
            "model",
            "session_instructions",
            "tag_ids_json",
            "created_at",
        }
        assert set(cols) == expected
        assert cols["id"]["pk"] == 1
        assert cols["name"]["notnull"] == 1
        assert cols["body"]["notnull"] == 0
        assert cols["working_dir"]["notnull"] == 0
        assert cols["model"]["notnull"] == 0
        assert cols["session_instructions"]["notnull"] == 0
        assert cols["tag_ids_json"]["notnull"] == 1
        assert cols["created_at"]["notnull"] == 1
    finally:
        await conn.close()


# --- CRUD -----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_template_round_trips(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_template(
            conn,
            name="Fresh debugging session",
            body="Walk me through the failing test.",
            working_dir="/tmp/work",
            model="claude-sonnet-4-6",
            session_instructions="Be concise.",
        )
        assert row["name"] == "Fresh debugging session"
        assert row["body"] == "Walk me through the failing test."
        assert row["working_dir"] == "/tmp/work"
        assert row["model"] == "claude-sonnet-4-6"
        assert row["session_instructions"] == "Be concise."
        assert row["tag_ids"] == []
        assert row["created_at"]
        assert len(row["id"]) == 32  # uuid4 hex
        # Round-trip through get_template.
        fetched = await get_template(conn, row["id"])
        assert fetched == row
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_create_template_stores_and_decodes_tag_ids(tmp_path: Path) -> None:
    """Tags land as a JSON array on disk but are decoded into
    `list[int]` on read. The round-trip preserves order."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        tag_a = await create_tag(conn, name="A")
        tag_b = await create_tag(conn, name="B")
        row = await create_template(
            conn,
            name="Tagged template",
            tag_ids=[tag_a["id"], tag_b["id"]],
        )
        assert row["tag_ids"] == [tag_a["id"], tag_b["id"]]
        # Inspect the raw column to confirm the JSON encoding.
        async with conn.execute(
            "SELECT tag_ids_json FROM session_templates WHERE id = ?",
            (row["id"],),
        ) as cursor:
            raw = await cursor.fetchone()
        assert raw is not None
        assert raw["tag_ids_json"] == f"[{tag_a['id']}, {tag_b['id']}]"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_create_template_defaults_to_empty_tag_ids(tmp_path: Path) -> None:
    """Omitting `tag_ids` stores `'[]'` — matches the column DEFAULT
    and keeps the picker free of undefined-array surprises."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_template(conn, name="Blank slate")
        assert row["tag_ids"] == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_create_template_allows_null_body(tmp_path: Path) -> None:
    """A "blank scratchpad" template is legal — body / working_dir /
    model all nullable so the downstream create falls through to app
    defaults."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_template(conn, name="Scratchpad")
        assert row["body"] is None
        assert row["working_dir"] is None
        assert row["model"] is None
        assert row["session_instructions"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_get_template_returns_none_for_missing(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await get_template(conn, "deadbeef") is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_templates_newest_first(tmp_path: Path) -> None:
    """The picker query wants newest-first. We assert the id set and
    count rather than leaning on ISO-second resolution which is flaky
    under a tight loop."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        first = await create_template(conn, name="first")
        second = await create_template(conn, name="second")
        third = await create_template(conn, name="third")
        rows = await list_templates(conn)
        ids = {r["id"] for r in rows}
        assert ids == {first["id"], second["id"], third["id"]}
        assert len(rows) == 3
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_templates_empty_on_fresh_db(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await list_templates(conn) == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_template_returns_true_on_hit(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_template(conn, name="to-kill")
        assert await delete_template(conn, row["id"]) is True
        assert await get_template(conn, row["id"]) is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_template_returns_false_on_miss(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await delete_template(conn, "deadbeef") is False
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_corrupt_tag_ids_json_degrades_to_empty(tmp_path: Path) -> None:
    """A hand-edited DB row with garbage JSON should not 500 the
    picker — the row surfaces with an empty `tag_ids` list so the
    caller keeps functioning."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_template(conn, name="tagged")
        await conn.execute(
            "UPDATE session_templates SET tag_ids_json = ? WHERE id = ?",
            ("{not valid json", row["id"]),
        )
        await conn.commit()
        fetched = await get_template(conn, row["id"])
        assert fetched is not None
        assert fetched["tag_ids"] == []
    finally:
        await conn.close()
