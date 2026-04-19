from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from twrminal.agent.base_prompt import BASE_PROMPT
from twrminal.agent.prompt import assemble_prompt
from twrminal.db.store import attach_tag, create_session, create_tag, init_db


async def _set_session_instructions(
    conn: aiosqlite.Connection, session_id: str, instructions: str
) -> None:
    await conn.execute(
        "UPDATE sessions SET session_instructions = ? WHERE id = ?",
        (instructions, session_id),
    )
    await conn.commit()


async def _set_tag_memory(conn: aiosqlite.Connection, tag_id: int, content: str) -> None:
    await conn.execute(
        "INSERT INTO tag_memories (tag_id, content, updated_at) VALUES (?, ?, datetime('now'))",
        (tag_id, content),
    )
    await conn.commit()


def test_estimate_tokens_empty_is_zero() -> None:
    from twrminal.agent.prompt import estimate_tokens

    assert estimate_tokens("") == 0


def test_estimate_tokens_short_string_is_at_least_one() -> None:
    from twrminal.agent.prompt import estimate_tokens

    # 1 char / 4 = 0 under plain division, but non-empty must return ≥1.
    assert estimate_tokens("a") == 1


def test_estimate_tokens_scales_with_length() -> None:
    from twrminal.agent.prompt import estimate_tokens

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
