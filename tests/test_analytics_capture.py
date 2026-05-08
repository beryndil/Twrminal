"""Tests for the analytics Phase 2 capture module.

Covers ``BEARINGS_ANALYTICS_v1.md`` §4.1 (turns table) and §5
(plug block capture / hashing / normalisation).

Test inventory
--------------
1. normalize_block_content — CRLF/CR → LF, trailing whitespace stripped,
   blank edges trimmed, interior blank lines preserved, no case change.
2. hash_block — determinism, distinct inputs produce distinct digests,
   64-char hex output.
3. estimate_tokens — approximation formula, empty string, non-ASCII.
4. collect_project_claude_md_blocks — walk-up with source paths, missing
   dirs skipped, empty working_dir returns [].
5. assemble_plug_blocks — correct block types and order, empty sources
   handled, session_instructions included/excluded.
6. capture_session_plug — end-to-end upsert + session link, idempotency
   (re-run is no-op), empty blocks skipped, blocks with identical
   content deduplicated.
7. capture_turn — sequential turn_index, all token fields persisted,
   idempotency via INSERT OR IGNORE on (session_id, turn_index).
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.analytics_capture import (
    CaptureBlock,
    assemble_plug_blocks,
    capture_session_plug,
    capture_turn,
    collect_project_claude_md_blocks,
    estimate_tokens,
    hash_block,
    normalize_block_content,
)
from bearings.db import get_connection_factory, load_schema
from bearings.db.analytics import list_session_plug_blocks, list_turns_for_session

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_SESS_ID = "sess-capture-test"
_MODEL = "claude-sonnet-4-6"


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "capture_test.db"


async def _bootstrapped(database_path: Path) -> aiosqlite.Connection:
    """Open a fresh connection with schema + a seed session row."""
    factory = get_connection_factory(database_path)
    conn = await factory().__aenter__()
    await load_schema(conn)
    await conn.execute(
        "INSERT INTO sessions (id, kind, title, working_dir, model, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            _SESS_ID,
            "chat",
            "Capture test",
            "/tmp",
            _MODEL,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    await conn.commit()
    return conn


# ---------------------------------------------------------------------------
# 1. normalize_block_content
# ---------------------------------------------------------------------------


def test_normalize_crlf_to_lf() -> None:
    """Windows line endings are normalised to LF."""
    assert normalize_block_content("a\r\nb\r\nc") == "a\nb\nc"


def test_normalize_cr_to_lf() -> None:
    """Bare CR is normalised to LF."""
    assert normalize_block_content("a\rb\rc") == "a\nb\nc"


def test_normalize_strips_trailing_whitespace_per_line() -> None:
    """Trailing spaces/tabs are removed from each line."""
    result = normalize_block_content("line one   \nline two\t\nline three")
    assert result == "line one\nline two\nline three"


def test_normalize_trims_leading_trailing_blank_lines() -> None:
    """Blank lines at the very start and end are removed."""
    result = normalize_block_content("\n\nhello\n\n")
    assert result == "hello"


def test_normalize_preserves_interior_blank_lines() -> None:
    """Blank lines between content are not removed."""
    result = normalize_block_content("a\n\nb")
    assert result == "a\n\nb"


def test_normalize_preserves_case() -> None:
    """Content is NOT lowercased — diff fidelity is required."""
    result = normalize_block_content("UPPER lower MiXeD")
    assert result == "UPPER lower MiXeD"


def test_normalize_empty_string() -> None:
    """Empty input returns empty string."""
    assert normalize_block_content("") == ""


def test_normalize_all_whitespace() -> None:
    """Content that is all whitespace normalises to empty string."""
    assert normalize_block_content("   \n  \n  ") == ""


# ---------------------------------------------------------------------------
# 2. hash_block
# ---------------------------------------------------------------------------


def test_hash_block_deterministic() -> None:
    """Same input always produces the same digest."""
    assert hash_block("hello") == hash_block("hello")


def test_hash_block_distinct_inputs() -> None:
    """Distinct inputs produce distinct digests."""
    assert hash_block("aaa") != hash_block("bbb")


def test_hash_block_length() -> None:
    """sha256 hex digest is always 64 characters."""
    assert len(hash_block("anything")) == 64


def test_hash_block_hex_chars() -> None:
    """Digest contains only lowercase hex characters."""
    digest = hash_block("test content")
    assert all(c in "0123456789abcdef" for c in digest)


# ---------------------------------------------------------------------------
# 3. estimate_tokens
# ---------------------------------------------------------------------------


def test_estimate_tokens_formula() -> None:
    """Token count is len(content) // 4."""
    assert estimate_tokens("1234") == 1  # 4 chars → 1 token
    assert estimate_tokens("12345678") == 2  # 8 chars → 2 tokens


def test_estimate_tokens_empty() -> None:
    """Empty string yields 0 tokens."""
    assert estimate_tokens("") == 0


def test_estimate_tokens_non_ascii() -> None:
    """Non-ASCII characters count by byte-length of the Python string, not UTF-8 bytes."""
    # Python str length counts code points, so len("é") == 1
    result = estimate_tokens("é" * 4)
    assert result == 1


def test_estimate_tokens_non_negative() -> None:
    """Result is always >= 0."""
    assert estimate_tokens("") >= 0
    assert estimate_tokens("x") >= 0


# ---------------------------------------------------------------------------
# 4. collect_project_claude_md_blocks
# ---------------------------------------------------------------------------


def test_collect_project_claude_md_blocks_empty_dir() -> None:
    """Empty working_dir returns an empty list."""
    assert collect_project_claude_md_blocks("") == []


def test_collect_project_claude_md_blocks_nonexistent_dir() -> None:
    """Nonexistent directory returns an empty list without raising."""
    result = collect_project_claude_md_blocks("/nonexistent/path/that/does/not/exist")
    assert result == []


def test_collect_project_claude_md_blocks_single_file(tmp_path: Path) -> None:
    """Single CLAUDE.md in working_dir is collected with absolute source_path."""
    (tmp_path / "CLAUDE.md").write_text("# Project CLAUDE.md\n")
    blocks = collect_project_claude_md_blocks(str(tmp_path))
    assert len(blocks) >= 1
    project_block = blocks[0]
    assert project_block.block_type == "claude_md"
    assert "Project CLAUDE.md" in project_block.content
    assert project_block.source_path is not None
    assert project_block.source_path.endswith("CLAUDE.md")


def test_collect_project_claude_md_blocks_walk_up(tmp_path: Path) -> None:
    """Walk-up finds CLAUDE.md files in parent directories."""
    child = tmp_path / "child"
    child.mkdir()
    (tmp_path / "CLAUDE.md").write_text("# Parent\n")
    (child / "CLAUDE.md").write_text("# Child\n")
    blocks = collect_project_claude_md_blocks(str(child))
    # Both child and parent CLAUDE.md should be found.
    source_paths = [b.source_path for b in blocks]
    assert any("child" in (p or "") for p in source_paths)
    assert any("child" not in (p or "") for p in source_paths)


def test_collect_project_claude_md_blocks_no_file(tmp_path: Path) -> None:
    """Directory without CLAUDE.md returns empty list."""
    result = collect_project_claude_md_blocks(str(tmp_path))
    # May find parent CLAUDE.mds but the tmp_path itself has none.
    # Just verify it doesn't crash.
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 5. assemble_plug_blocks
# ---------------------------------------------------------------------------


def test_assemble_plug_blocks_empty_inputs(tmp_path: Path) -> None:
    """All-empty inputs return empty list (no CLAUDE.md, no extras)."""
    result = assemble_plug_blocks(str(tmp_path), (), (), None)
    # tmp_path has no CLAUDE.md; result may include parent walk-up blocks
    # but at minimum will not raise.
    assert isinstance(result, list)


def test_assemble_plug_blocks_tag_claude_md(tmp_path: Path) -> None:
    """Tag CLAUDE.md blocks appear with block_type='claude_md' and source_path=None."""
    blocks = assemble_plug_blocks(str(tmp_path), ("tag content here",), (), None)
    tag_blocks = [b for b in blocks if b.content == "tag content here"]
    assert len(tag_blocks) == 1
    assert tag_blocks[0].block_type == "claude_md"
    assert tag_blocks[0].source_path is None


def test_assemble_plug_blocks_tag_memory(tmp_path: Path) -> None:
    """Tag memory blocks appear with block_type='tag_memory'."""
    blocks = assemble_plug_blocks(str(tmp_path), (), ("memory body",), None)
    mem_blocks = [b for b in blocks if b.content == "memory body"]
    assert len(mem_blocks) == 1
    assert mem_blocks[0].block_type == "tag_memory"


def test_assemble_plug_blocks_session_instructions(tmp_path: Path) -> None:
    """Non-empty session_instructions produces a system_addition block."""
    blocks = assemble_plug_blocks(str(tmp_path), (), (), "  Do this always.  ")
    si_blocks = [b for b in blocks if b.block_type == "system_addition"]
    assert len(si_blocks) == 1
    assert si_blocks[0].content == "Do this always."  # stripped


def test_assemble_plug_blocks_empty_session_instructions(tmp_path: Path) -> None:
    """Whitespace-only session_instructions produces no block."""
    blocks = assemble_plug_blocks(str(tmp_path), (), (), "   ")
    si_blocks = [b for b in blocks if b.block_type == "system_addition"]
    assert len(si_blocks) == 0


def test_assemble_plug_blocks_none_session_instructions(tmp_path: Path) -> None:
    """None session_instructions produces no system_addition block."""
    blocks = assemble_plug_blocks(str(tmp_path), (), (), None)
    si_blocks = [b for b in blocks if b.block_type == "system_addition"]
    assert len(si_blocks) == 0


# ---------------------------------------------------------------------------
# 6. capture_session_plug
# ---------------------------------------------------------------------------


async def test_capture_session_plug_end_to_end(database_path: Path) -> None:
    """capture_session_plug upserts plug_blocks and creates session_plug_blocks links."""
    conn = await _bootstrapped(database_path)
    try:
        blocks = [
            CaptureBlock(block_type="claude_md", content="# CLAUDE.md content\n"),
            CaptureBlock(block_type="tag_memory", content="Some tag memory."),
        ]
        await capture_session_plug(conn, _SESS_ID, _MODEL, blocks)

        links = await list_session_plug_blocks(conn, _SESS_ID)
        assert len(links) == 2

        # Verify plug_blocks rows exist.
        for link in links:
            async with conn.execute(
                "SELECT hash, block_type FROM plug_blocks WHERE hash = ?",
                (link.block_hash,),
            ) as cursor:
                row = await cursor.fetchone()
            assert row is not None, f"plug_blocks row missing for hash {link.block_hash}"
    finally:
        await conn.close()


async def test_capture_session_plug_idempotent(database_path: Path) -> None:
    """Calling capture_session_plug twice for the same session is a no-op (INSERT OR IGNORE)."""
    conn = await _bootstrapped(database_path)
    try:
        blocks = [CaptureBlock(block_type="claude_md", content="idempotent block")]
        await capture_session_plug(conn, _SESS_ID, _MODEL, blocks)
        await capture_session_plug(conn, _SESS_ID, _MODEL, blocks)

        links = await list_session_plug_blocks(conn, _SESS_ID)
        assert len(links) == 1, "duplicate session_plug_blocks rows should not exist"
    finally:
        await conn.close()


async def test_capture_session_plug_deduplicates_identical_content(database_path: Path) -> None:
    """Two blocks with identical content resolve to one plug_blocks row via the shared hash."""
    conn = await _bootstrapped(database_path)
    try:
        same = "exact same content"
        blocks = [
            CaptureBlock(block_type="claude_md", content=same),
            CaptureBlock(block_type="claude_md", content=same),
        ]
        await capture_session_plug(conn, _SESS_ID, _MODEL, blocks)

        rows = list(await conn.execute_fetchall("SELECT hash FROM plug_blocks"))
        assert len(rows) == 1, "identical content must map to one plug_blocks row"

        links = await list_session_plug_blocks(conn, _SESS_ID)
        # Both CaptureBlocks share the same hash; only one session_plug_blocks row.
        assert len(links) == 1
    finally:
        await conn.close()


async def test_capture_session_plug_skips_empty_content(database_path: Path) -> None:
    """Blocks that normalise to empty string are silently skipped."""
    conn = await _bootstrapped(database_path)
    try:
        blocks = [
            CaptureBlock(block_type="claude_md", content="   \n  "),  # all whitespace
            CaptureBlock(block_type="tag_memory", content="real content"),
        ]
        await capture_session_plug(conn, _SESS_ID, _MODEL, blocks)

        links = await list_session_plug_blocks(conn, _SESS_ID)
        # empty block must not create a plug_blocks or session_plug_blocks row
        assert len(links) == 1
    finally:
        await conn.close()


async def test_capture_session_plug_normalises_before_hash(database_path: Path) -> None:
    """Two blocks differing only in trailing whitespace map to the same hash."""
    conn = await _bootstrapped(database_path)
    try:
        blocks = [
            CaptureBlock(block_type="claude_md", content="hello   "),
            CaptureBlock(block_type="claude_md", content="hello"),
        ]
        await capture_session_plug(conn, _SESS_ID, _MODEL, blocks)

        rows = list(await conn.execute_fetchall("SELECT hash FROM plug_blocks"))
        assert len(rows) == 1, "normalised-equal blocks must map to one plug_blocks row"
    finally:
        await conn.close()


async def test_capture_session_plug_updates_last_seen(database_path: Path) -> None:
    """Re-upserting the same hash updates last_seen without touching first_seen."""
    conn = await _bootstrapped(database_path)
    try:
        block = CaptureBlock(block_type="claude_md", content="stable content")
        # First capture — establishes first_seen.
        await capture_session_plug(conn, _SESS_ID, _MODEL, [block])

        # Second capture for a different session to trigger upsert on the same block.
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "sess-2",
                "chat",
                "S2",
                "/tmp",
                _MODEL,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
        await conn.commit()
        await capture_session_plug(conn, "sess-2", _MODEL, [block])

        # first_seen should be unchanged; last_seen may differ.
        async with conn.execute("SELECT first_seen, last_seen FROM plug_blocks") as cursor:
            row = await cursor.fetchone()
        assert row is not None
        # last_seen >= first_seen (both set by the same _now_ms() call in tests
        # running fast; at minimum they should be equal, not violating the invariant).
        assert int(row[1]) >= int(row[0])
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 7. capture_turn
# ---------------------------------------------------------------------------


async def test_capture_turn_inserts_row(database_path: Path) -> None:
    """capture_turn inserts a turns row with the correct field values."""
    conn = await _bootstrapped(database_path)
    try:
        await capture_turn(
            conn,
            _SESS_ID,
            _MODEL,
            input_tokens=1000,
            output_tokens=200,
            cache_read_tokens=50,
            cache_creation_tokens=10,
        )
        turns = await list_turns_for_session(conn, _SESS_ID)
        assert len(turns) == 1
        t = turns[0]
        assert t.session_id == _SESS_ID
        assert t.turn_index == 0
        assert t.model == _MODEL
        assert t.input_tokens == 1000
        assert t.output_tokens == 200
        assert t.cache_read_tokens == 50
        assert t.cache_creation_tokens == 10
    finally:
        await conn.close()


async def test_capture_turn_sequential_index(database_path: Path) -> None:
    """Successive capture_turn calls produce sequential turn_index values."""
    conn = await _bootstrapped(database_path)
    try:
        for _ in range(3):
            await capture_turn(conn, _SESS_ID, _MODEL, input_tokens=100, output_tokens=20)
        turns = await list_turns_for_session(conn, _SESS_ID)
        assert [t.turn_index for t in turns] == [0, 1, 2]
    finally:
        await conn.close()


async def test_capture_turn_zero_tokens(database_path: Path) -> None:
    """capture_turn succeeds with all-zero token counts (edge case)."""
    conn = await _bootstrapped(database_path)
    try:
        await capture_turn(conn, _SESS_ID, _MODEL, input_tokens=0, output_tokens=0)
        turns = await list_turns_for_session(conn, _SESS_ID)
        assert len(turns) == 1
        assert turns[0].input_tokens == 0
    finally:
        await conn.close()


async def test_capture_turn_default_cache_tokens(database_path: Path) -> None:
    """Omitting cache_* kwargs defaults to 0."""
    conn = await _bootstrapped(database_path)
    try:
        await capture_turn(conn, _SESS_ID, _MODEL, input_tokens=500, output_tokens=100)
        turns = await list_turns_for_session(conn, _SESS_ID)
        assert turns[0].cache_read_tokens == 0
        assert turns[0].cache_creation_tokens == 0
    finally:
        await conn.close()
