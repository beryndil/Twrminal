from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.base_prompt import BASE_PROMPT
from bearings.agent.prompt import assemble_prompt
from bearings.db.store import (
    attach_tag,
    create_checklist,
    create_item,
    create_session,
    create_tag,
    init_db,
    toggle_item,
)


async def _set_session_instructions(
    conn: aiosqlite.Connection, session_id: str, instructions: str
) -> None:
    await conn.execute(
        "UPDATE sessions SET session_instructions = ? WHERE id = ?",
        (instructions, session_id),
    )
    await conn.commit()


async def _set_session_description(
    conn: aiosqlite.Connection, session_id: str, description: str
) -> None:
    await conn.execute(
        "UPDATE sessions SET description = ? WHERE id = ?",
        (description, session_id),
    )
    await conn.commit()


async def _set_tag_memory(conn: aiosqlite.Connection, tag_id: int, content: str) -> None:
    await conn.execute(
        "INSERT INTO tag_memories (tag_id, content, updated_at) VALUES (?, ?, datetime('now'))",
        (tag_id, content),
    )
    await conn.commit()


def test_estimate_tokens_empty_is_zero() -> None:
    from bearings.agent.prompt import estimate_tokens

    assert estimate_tokens("") == 0


def test_estimate_tokens_short_string_is_at_least_one() -> None:
    from bearings.agent.prompt import estimate_tokens

    # 1 char / 4 = 0 under plain division, but non-empty must return ≥1.
    assert estimate_tokens("a") == 1


def test_estimate_tokens_scales_with_length() -> None:
    from bearings.agent.prompt import estimate_tokens

    # 80 chars → 20 tokens (4 chars per token approximation).
    assert estimate_tokens("x" * 80) == 20


@pytest.mark.asyncio
async def test_only_base_when_no_tags_or_instructions(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        result = await assemble_prompt(conn, sess["id"])
    finally:
        await conn.close()
    assert [layer.kind for layer in result.layers] == ["base"]
    assert result.layers[0].content == BASE_PROMPT
    assert "<!-- layer: base[base] -->" in result.text
    assert BASE_PROMPT in result.text


@pytest.mark.asyncio
async def test_missing_session_returns_base_only(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        result = await assemble_prompt(conn, "does-not-exist")
    finally:
        await conn.close()
    assert [layer.kind for layer in result.layers] == ["base"]


@pytest.mark.asyncio
async def test_tag_without_memory_is_skipped(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        tag_a = await create_tag(conn, name="with-memory")
        tag_b = await create_tag(conn, name="without-memory")
        await _set_tag_memory(conn, tag_a["id"], "Remember A.")
        await attach_tag(conn, sess["id"], tag_a["id"])
        await attach_tag(conn, sess["id"], tag_b["id"])
        result = await assemble_prompt(conn, sess["id"])
    finally:
        await conn.close()
    tag_layers = [layer for layer in result.layers if layer.kind == "tag_memory"]
    assert [layer.name for layer in tag_layers] == ["with-memory"]
    assert tag_layers[0].content == "Remember A."


@pytest.mark.asyncio
async def test_tag_memory_order_pinned_then_sort_order_then_id(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        # Four tags engineered to exercise every tiebreaker:
        # - c,b both pinned → c wins on sort_order (5 < 20).
        # - a,d both unpinned with sort_order=10 → a wins on id (created first).
        a = await create_tag(conn, name="a", pinned=False, sort_order=10)
        b = await create_tag(conn, name="b", pinned=True, sort_order=20)
        c = await create_tag(conn, name="c", pinned=True, sort_order=5)
        d = await create_tag(conn, name="d", pinned=False, sort_order=10)
        for tag in (a, b, c, d):
            await _set_tag_memory(conn, tag["id"], f"{tag['name']}-memory")
            await attach_tag(conn, sess["id"], tag["id"])
        result = await assemble_prompt(conn, sess["id"])
    finally:
        await conn.close()
    tag_layers = [layer for layer in result.layers if layer.kind == "tag_memory"]
    assert [layer.name for layer in tag_layers] == ["c", "b", "a", "d"]


@pytest.mark.asyncio
async def test_session_instructions_always_last(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        tag = await create_tag(conn, name="t")
        await _set_tag_memory(conn, tag["id"], "Tag memory.")
        await attach_tag(conn, sess["id"], tag["id"])
        await _set_session_instructions(conn, sess["id"], "Override everything above.")
        result = await assemble_prompt(conn, sess["id"])
    finally:
        await conn.close()
    assert [layer.kind for layer in result.layers] == ["base", "tag_memory", "session"]
    assert result.layers[-1].content == "Override everything above."


@pytest.mark.asyncio
async def test_description_injected_between_base_and_tag_memory(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        tag = await create_tag(conn, name="t")
        await _set_tag_memory(conn, tag["id"], "Tag memory.")
        await attach_tag(conn, sess["id"], tag["id"])
        await _set_session_description(conn, sess["id"], "Why this window exists.")
        await _set_session_instructions(conn, sess["id"], "Override everything above.")
        result = await assemble_prompt(conn, sess["id"])
    finally:
        await conn.close()
    assert [layer.kind for layer in result.layers] == [
        "base",
        "session_description",
        "tag_memory",
        "session",
    ]
    description_layer = result.layers[1]
    assert description_layer.name == "description"
    assert description_layer.content == "Why this window exists."
    assert "<!-- layer: session_description[description] -->" in result.text


@pytest.mark.asyncio
async def test_missing_description_omits_layer(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        result = await assemble_prompt(conn, sess["id"])
    finally:
        await conn.close()
    assert "session_description" not in [layer.kind for layer in result.layers]


@pytest.mark.asyncio
async def test_empty_description_omits_layer(tmp_path: Path) -> None:
    # Empty-string description is treated the same as NULL — no layer.
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await _set_session_description(conn, sess["id"], "")
        result = await assemble_prompt(conn, sess["id"])
    finally:
        await conn.close()
    assert "session_description" not in [layer.kind for layer in result.layers]


# ---------------------------------------------------------------------------
# v0.5.2: checklist_overview layer for kind='checklist' sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checklist_overview_layer_injected_for_checklist_kind(tmp_path: Path) -> None:
    """A kind='checklist' session gets a `checklist_overview` layer that
    carries the list title, notes, and every item's label + checked state."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        cl = await create_session(
            conn,
            working_dir="/tmp",
            model="claude-sonnet-4-6",
            kind="checklist",
            title="ship v0.5.2",
        )
        await create_checklist(conn, cl["id"], notes="paired-chat + embedded chat")
        done = await create_item(conn, cl["id"], label="wire runner")
        assert done is not None
        await toggle_item(conn, done["id"], checked=True)
        await create_item(conn, cl["id"], label="add overview layer")
        await create_item(conn, cl["id"], label="build chat panel")
        result = await assemble_prompt(conn, cl["id"])
    finally:
        await conn.close()
    kinds = [layer.kind for layer in result.layers]
    assert "checklist_overview" in kinds
    overview = next(layer for layer in result.layers if layer.kind == "checklist_overview")
    assert "ship v0.5.2" in overview.content
    assert "paired-chat + embedded chat" in overview.content
    assert "[x] wire runner" in overview.content
    assert "[ ] add overview layer" in overview.content
    assert "[ ] build chat panel" in overview.content


@pytest.mark.asyncio
async def test_checklist_overview_layer_omitted_for_chat_session(tmp_path: Path) -> None:
    """A plain chat session never gets the overview layer, even when a
    checklist exists in the DB for a different session."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        cl = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, cl["id"])
        chat = await create_session(conn, working_dir="/tmp", model="claude-sonnet-4-6")
        result = await assemble_prompt(conn, chat["id"])
    finally:
        await conn.close()
    assert "checklist_overview" not in [layer.kind for layer in result.layers]


@pytest.mark.asyncio
async def test_checklist_overview_layer_renders_nested_items(tmp_path: Path) -> None:
    """Nested items should indent under their parent so the agent sees
    the same hierarchy the UI renders."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        cl = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        await create_checklist(conn, cl["id"])
        parent = await create_item(conn, cl["id"], label="parent task")
        assert parent is not None
        await create_item(conn, cl["id"], label="child task", parent_item_id=parent["id"])
        result = await assemble_prompt(conn, cl["id"])
    finally:
        await conn.close()
    overview = next(layer for layer in result.layers if layer.kind == "checklist_overview")
    lines = overview.content.splitlines()
    parent_idx = next(i for i, ln in enumerate(lines) if "parent task" in ln)
    child_idx = next(i for i, ln in enumerate(lines) if "child task" in ln)
    assert child_idx > parent_idx
    # Child line is indented farther than parent line.
    assert lines[child_idx].startswith("  ") and not lines[parent_idx].startswith("  ")


@pytest.mark.asyncio
async def test_checklist_overview_layer_handles_empty_list(tmp_path: Path) -> None:
    """An empty checklist still injects the layer — the agent gets the
    title and a "(none yet)" marker instead of a silent skip."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        cl = await create_session(
            conn,
            working_dir="/tmp",
            model="claude-sonnet-4-6",
            kind="checklist",
            title="blank list",
        )
        await create_checklist(conn, cl["id"])
        result = await assemble_prompt(conn, cl["id"])
    finally:
        await conn.close()
    overview = next(layer for layer in result.layers if layer.kind == "checklist_overview")
    assert "blank list" in overview.content
    assert "(none yet" in overview.content


@pytest.mark.asyncio
async def test_checklist_overview_layer_skipped_on_missing_checklist_row(tmp_path: Path) -> None:
    """A kind='checklist' session whose companion `checklists` row never
    landed (transient creation race) should not crash the assembler."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        cl = await create_session(
            conn, working_dir="/tmp", model="claude-sonnet-4-6", kind="checklist"
        )
        # Deliberately skip create_checklist so the FK-joined row is
        # missing. The assembler should degrade gracefully.
        result = await assemble_prompt(conn, cl["id"])
    finally:
        await conn.close()
    assert "checklist_overview" not in [layer.kind for layer in result.layers]


@pytest.mark.asyncio
async def test_text_contains_every_layer_header_verbatim(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        tag = await create_tag(conn, name="infra")
        await _set_tag_memory(conn, tag["id"], "tm")
        await attach_tag(conn, sess["id"], tag["id"])
        await _set_session_instructions(conn, sess["id"], "si")
        result = await assemble_prompt(conn, sess["id"])
    finally:
        await conn.close()
    for layer in result.layers:
        assert f"<!-- layer: {layer.kind}[{layer.name}] -->" in result.text
