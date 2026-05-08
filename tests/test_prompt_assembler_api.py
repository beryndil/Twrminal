"""Tests for ``GET /api/sessions/{id}/system_prompt`` and the
:func:`bearings.agent.prompt_assembler.assemble_system_prompt_layers`
domain function (gap-cycle-13-004).

Covers acceptance criteria:
- Layers populated for a session with a working_dir under a CLAUDE.md
  walk-up chain.
- tag_memory rows for each enabled tag-attached memory.
- total_tokens sums correctly.
- 404 on unknown session_id.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.agent.bearings_mcp import CLOSE_SESSION_INSTRUCTION
from bearings.agent.prompt_assembler import (
    LAYER_KIND_BASELINE,
    LAYER_KIND_PROJECT_CLAUDE_MD,
    LAYER_KIND_SESSION_INSTRUCTIONS,
    LAYER_KIND_TAG_CLAUDE_MD,
    LAYER_KIND_TAG_MEMORY,
    assemble_system_prompt_layers,
)
from bearings.config.constants import SESSION_KIND_CHAT
from bearings.db import memories as memories_db
from bearings.db import sessions as sessions_db
from bearings.db import tags as tags_db
from bearings.db.connection import load_schema
from bearings.web.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    conn = await aiosqlite.connect(tmp_path / "test.db")
    try:
        await load_schema(conn)
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def app_and_db(
    tmp_path: Path,
) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection]]:
    conn = await aiosqlite.connect(tmp_path / "sapi.db")
    try:
        await load_schema(conn)
        app = create_app(db_connection=conn)
        yield app, conn
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# assemble_system_prompt_layers unit tests
# ---------------------------------------------------------------------------


async def test_baseline_always_present(db: aiosqlite.Connection) -> None:
    """The ``baseline`` layer is always present regardless of other fields."""
    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/nonexistent/path",
        model="sonnet",
    )
    result = await assemble_system_prompt_layers(db, session.id)
    assert result is not None
    kinds = [layer.kind for layer in result.layers]
    assert LAYER_KIND_BASELINE in kinds
    baseline = next(layer for layer in result.layers if layer.kind == LAYER_KIND_BASELINE)
    assert baseline.body == CLOSE_SESSION_INSTRUCTION
    assert baseline.token_count == len(CLOSE_SESSION_INSTRUCTION) // 4
    assert baseline.source_path is None


async def test_none_for_unknown_session(db: aiosqlite.Connection) -> None:
    """Returns ``None`` when the session does not exist."""
    result = await assemble_system_prompt_layers(db, "no-such-session")
    assert result is None


async def test_session_instructions_layer_when_set(db: aiosqlite.Connection) -> None:
    """``session_instructions`` layer appears when the field is non-empty."""
    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/nonexistent/path",
        model="sonnet",
        session_instructions="You are an executor.",
    )
    result = await assemble_system_prompt_layers(db, session.id)
    assert result is not None
    si_layers = [layer for layer in result.layers if layer.kind == LAYER_KIND_SESSION_INSTRUCTIONS]
    assert len(si_layers) == 1
    assert si_layers[0].body == "You are an executor."
    assert si_layers[0].source_path is None


async def test_session_instructions_omitted_when_empty(db: aiosqlite.Connection) -> None:
    """``session_instructions`` layer is omitted when None or whitespace-only."""
    session_none = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t1",
        working_dir="/nope",
        model="sonnet",
        session_instructions=None,
    )
    session_ws = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t2",
        working_dir="/nope",
        model="sonnet",
        session_instructions="   \n\n  ",
    )
    for sid in (session_none.id, session_ws.id):
        result = await assemble_system_prompt_layers(db, sid)
        assert result is not None
        si_kind = LAYER_KIND_SESSION_INSTRUCTIONS
        si_layers = [layer for layer in result.layers if layer.kind == si_kind]
        assert si_layers == [], f"expected no SI layer for session {sid}"


async def test_project_claude_md_walk_up(
    db: aiosqlite.Connection,
    tmp_path: Path,
) -> None:
    """``project_claude_md`` layers appear for CLAUDE.md files found in
    the working_dir and its parents."""
    # Create CLAUDE.md at two levels.
    child_dir = tmp_path / "project" / "sub"
    child_dir.mkdir(parents=True)
    parent_claude = tmp_path / "project" / "CLAUDE.md"
    child_claude = child_dir / "CLAUDE.md"
    parent_claude.write_text("parent context", encoding="utf-8")
    child_claude.write_text("child context", encoding="utf-8")

    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir=str(child_dir),
        model="sonnet",
    )
    result = await assemble_system_prompt_layers(db, session.id)
    assert result is not None

    md_layers = [layer for layer in result.layers if layer.kind == LAYER_KIND_PROJECT_CLAUDE_MD]
    source_paths = [layer.source_path for layer in md_layers]
    bodies = [layer.body for layer in md_layers]

    assert str(child_claude) in source_paths
    assert str(parent_claude) in source_paths
    assert "child context" in bodies
    assert "parent context" in bodies
    # Child directory appears before its parent (walk-up order).
    child_idx = source_paths.index(str(child_claude))
    parent_idx = source_paths.index(str(parent_claude))
    assert child_idx < parent_idx


async def test_no_project_claude_md_when_none_found(
    db: aiosqlite.Connection,
    tmp_path: Path,
) -> None:
    """No ``project_claude_md`` layers when the working_dir chain has no
    CLAUDE.md files."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir=str(empty_dir),
        model="sonnet",
    )
    result = await assemble_system_prompt_layers(db, session.id)
    assert result is not None
    md_layers = [layer for layer in result.layers if layer.kind == LAYER_KIND_PROJECT_CLAUDE_MD]
    assert md_layers == []


async def test_tag_claude_md_rows_for_each_tag_with_working_dir(
    db: aiosqlite.Connection,
    tmp_path: Path,
) -> None:
    """One ``tag_claude_md`` layer per tag whose working_dir has a readable CLAUDE.md."""
    dir_a = tmp_path / "tag_a"
    dir_a.mkdir()
    dir_b = tmp_path / "tag_b"
    dir_b.mkdir()
    (dir_a / "CLAUDE.md").write_text("Tag A context", encoding="utf-8")
    (dir_b / "CLAUDE.md").write_text("Tag B context", encoding="utf-8")

    tag_a = await tags_db.create(db, name="tag-a", color=None, working_dir=str(dir_a))
    tag_b = await tags_db.create(db, name="tag-b", color=None, working_dir=str(dir_b))

    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/nonexistent",
        model="sonnet",
    )
    await tags_db.attach(db, session_id=session.id, tag_id=tag_a.id)
    await tags_db.attach(db, session_id=session.id, tag_id=tag_b.id)

    result = await assemble_system_prompt_layers(db, session.id)
    assert result is not None

    claude_md_layers = [layer for layer in result.layers if layer.kind == LAYER_KIND_TAG_CLAUDE_MD]
    assert len(claude_md_layers) == 2
    bodies = {layer.body for layer in claude_md_layers}
    assert "Tag A context" in bodies
    assert "Tag B context" in bodies
    # source_path is set for filesystem-sourced layers
    for layer in claude_md_layers:
        assert layer.source_path is not None
        assert layer.source_path.endswith("CLAUDE.md")


async def test_tag_with_no_working_dir_skipped(db: aiosqlite.Connection) -> None:
    """Tags without a working_dir contribute no tag_claude_md layer."""
    tag = await tags_db.create(db, name="bare-tag", color=None, working_dir=None)
    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/nope",
        model="sonnet",
    )
    await tags_db.attach(db, session_id=session.id, tag_id=tag.id)
    result = await assemble_system_prompt_layers(db, session.id)
    assert result is not None
    claude_md_layers = [layer for layer in result.layers if layer.kind == LAYER_KIND_TAG_CLAUDE_MD]
    assert claude_md_layers == []


async def test_total_tokens_sums_correctly(
    db: aiosqlite.Connection,
    tmp_path: Path,
) -> None:
    """``total_tokens`` equals the sum of all individual layer
    ``token_count`` values."""
    wd = tmp_path / "proj"
    wd.mkdir()
    (wd / "CLAUDE.md").write_text("A" * 40, encoding="utf-8")

    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir=str(wd),
        model="sonnet",
        session_instructions="instructions body",
    )
    result = await assemble_system_prompt_layers(db, session.id)
    assert result is not None
    expected = sum(layer.token_count for layer in result.layers)
    assert result.total_tokens == expected


async def test_layer_order_matches_spec(db: aiosqlite.Connection) -> None:
    """Layer kinds appear in the documented splice order:
    session_instructions → baseline → project_claude_md → tag_memory."""
    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/nope",
        model="sonnet",
        session_instructions="steer",
    )
    result = await assemble_system_prompt_layers(db, session.id)
    assert result is not None
    kinds = [layer.kind for layer in result.layers]
    assert kinds.index(LAYER_KIND_SESSION_INSTRUCTIONS) < kinds.index(LAYER_KIND_BASELINE)


# ---------------------------------------------------------------------------
# HTTP endpoint integration tests
# ---------------------------------------------------------------------------


async def test_get_system_prompt_404_unknown_session(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        resp = client.get("/api/sessions/no-such/system_prompt")
    assert resp.status_code == 404


async def test_get_system_prompt_200_baseline_always_present(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/nonexistent",
        model="sonnet",
    )
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{session.id}/system_prompt")
    assert resp.status_code == 200
    body = resp.json()
    assert "layers" in body
    assert "total_tokens" in body
    assert body["token_count_approximate"] is True
    kinds = [layer["kind"] for layer in body["layers"]]
    assert LAYER_KIND_BASELINE in kinds


async def test_get_system_prompt_wire_shape(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
    tmp_path: Path,
) -> None:
    """Each layer in the response has the required wire fields."""
    wd = tmp_path / "p"
    wd.mkdir()
    (wd / "CLAUDE.md").write_text("project content", encoding="utf-8")

    app, conn = app_and_db
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir=str(wd),
        model="sonnet",
        session_instructions="steer",
    )
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{session.id}/system_prompt")
    assert resp.status_code == 200
    for layer in resp.json()["layers"]:
        assert "kind" in layer
        assert "body" in layer
        assert "token_count" in layer
        assert "source_path" in layer  # may be null


async def test_get_system_prompt_total_tokens_matches_sum(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/nonexistent",
        model="sonnet",
        session_instructions="hello",
    )
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{session.id}/system_prompt")
    assert resp.status_code == 200
    data = resp.json()
    expected = sum(layer["token_count"] for layer in data["layers"])
    assert data["total_tokens"] == expected


# ---------------------------------------------------------------------------
# DB memory (tag_memory kind) tests — feature-7-002
# ---------------------------------------------------------------------------


async def test_db_memories_appear_as_tag_memory_layers(
    db: aiosqlite.Connection,
) -> None:
    """Enabled tag_memories rows produce ``tag_memory`` layers with source_path=None."""
    tag = await tags_db.create(db, name="mem-tag", color=None, working_dir=None)
    await memories_db.create(db, tag_id=tag.id, title="Rule A", body="Always cite arch §1.1.3.")
    await memories_db.create(db, tag_id=tag.id, title="Rule B", body="No inline literals.")

    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/nope",
        model="sonnet",
    )
    await tags_db.attach(db, session_id=session.id, tag_id=tag.id)

    result = await assemble_system_prompt_layers(db, session.id)
    assert result is not None

    mem_layers = [layer for layer in result.layers if layer.kind == LAYER_KIND_TAG_MEMORY]
    assert len(mem_layers) == 2
    bodies = {layer.body for layer in mem_layers}
    assert "Always cite arch §1.1.3." in bodies
    assert "No inline literals." in bodies
    # DB-resident: source_path must be None
    for layer in mem_layers:
        assert layer.source_path is None


async def test_disabled_memory_excluded_from_layers(
    db: aiosqlite.Connection,
) -> None:
    """Memories with ``enabled=False`` do not appear as ``tag_memory`` layers."""
    tag = await tags_db.create(db, name="disable-tag", color=None, working_dir=None)
    await memories_db.create(db, tag_id=tag.id, title="Active", body="Enabled body.", enabled=True)
    await memories_db.create(
        db, tag_id=tag.id, title="Inactive", body="Disabled body.", enabled=False
    )

    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/nope",
        model="sonnet",
    )
    await tags_db.attach(db, session_id=session.id, tag_id=tag.id)

    result = await assemble_system_prompt_layers(db, session.id)
    assert result is not None

    mem_layers = [layer for layer in result.layers if layer.kind == LAYER_KIND_TAG_MEMORY]
    assert len(mem_layers) == 1
    assert mem_layers[0].body == "Enabled body."


async def test_tag_with_both_claude_md_and_db_memory_produces_both_layer_kinds(
    db: aiosqlite.Connection,
    tmp_path: Path,
) -> None:
    """A tag with a working-dir CLAUDE.md AND enabled DB memories produces
    both a ``tag_claude_md`` layer and a ``tag_memory`` layer, distinguishable
    by kind."""
    tag_dir = tmp_path / "dual-tag"
    tag_dir.mkdir()
    (tag_dir / "CLAUDE.md").write_text("File-system context.", encoding="utf-8")

    tag = await tags_db.create(db, name="dual-tag", color=None, working_dir=str(tag_dir))
    await memories_db.create(db, tag_id=tag.id, title="DB rule", body="DB memory body.")

    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/nope",
        model="sonnet",
    )
    await tags_db.attach(db, session_id=session.id, tag_id=tag.id)

    result = await assemble_system_prompt_layers(db, session.id)
    assert result is not None

    claude_md_layers = [layer for layer in result.layers if layer.kind == LAYER_KIND_TAG_CLAUDE_MD]
    db_mem_layers = [layer for layer in result.layers if layer.kind == LAYER_KIND_TAG_MEMORY]

    # CLAUDE.md layer present with filesystem source_path
    assert len(claude_md_layers) == 1
    assert claude_md_layers[0].body == "File-system context."
    assert claude_md_layers[0].source_path is not None

    # DB memory layer present with no source_path
    assert len(db_mem_layers) == 1
    assert db_mem_layers[0].body == "DB memory body."
    assert db_mem_layers[0].source_path is None


async def test_deleted_memory_absent_on_next_assemble_call(
    db: aiosqlite.Connection,
) -> None:
    """Deleting a memory removes it from the layer breakdown on the next call
    without requiring a runner respawn (per-turn re-read invariant)."""
    tag = await tags_db.create(db, name="reread-tag", color=None, working_dir=None)
    memory = await memories_db.create(db, tag_id=tag.id, title="Ephemeral", body="Will be deleted.")

    session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/nope",
        model="sonnet",
    )
    await tags_db.attach(db, session_id=session.id, tag_id=tag.id)

    # First call: memory is present.
    result_before = await assemble_system_prompt_layers(db, session.id)
    assert result_before is not None
    mem_layers_before = [
        layer for layer in result_before.layers if layer.kind == LAYER_KIND_TAG_MEMORY
    ]
    assert len(mem_layers_before) == 1

    # Delete the memory.
    deleted = await memories_db.delete(db, memory.id)
    assert deleted

    # Second call on the same connection: memory must be gone.
    result_after = await assemble_system_prompt_layers(db, session.id)
    assert result_after is not None
    mem_layers_after = [
        layer for layer in result_after.layers if layer.kind == LAYER_KIND_TAG_MEMORY
    ]
    assert mem_layers_after == []
