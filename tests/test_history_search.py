"""Regression tests for LIKE-metacharacter escaping in history search.

feature-5-002: ``%`` and ``_`` in search input were interpolated raw into
the LIKE pattern despite the ``ESCAPE '\\\\'`` clause.  ``_escape_like``
was added to ``routes/history.py`` to sanitise user input before building
the pattern.

Acceptance criteria:
- ``100%`` finds only sessions/messages whose text contains the literal
  substring ``100%``, not all strings starting with ``100``.
- ``foo_bar`` finds only the literal substring ``foo_bar``, not
  ``foo`` + any character + ``bar``.
- A literal backslash ``\\`` in the stored text is still findable when the
  user types it.  The escape character must not be consumed unintentionally.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from bearings.config.constants import SESSION_KIND_CHAT
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.web.app import create_app
from bearings.web.routes.history import _escape_like

# ---------------------------------------------------------------------------
# Unit tests for _escape_like
# ---------------------------------------------------------------------------


def test_escape_like_percent() -> None:
    assert _escape_like("100%") == r"100\%"


def test_escape_like_underscore() -> None:
    assert _escape_like("foo_bar") == r"foo\_bar"


def test_escape_like_backslash_first() -> None:
    # The backslash in the input must be escaped BEFORE % and _ are handled,
    # so that a literal backslash does not accidentally escape the substituted
    # metachar markers.
    assert _escape_like("a\\b") == "a\\\\b"


def test_escape_like_combined() -> None:
    assert _escape_like("a\\%_b") == "a\\\\\\%\\_b"


def test_escape_like_plain_string_unchanged() -> None:
    assert _escape_like("hello world") == "hello world"


# ---------------------------------------------------------------------------
# Integration fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def search_client(tmp_path: Path) -> AsyncIterator[tuple[TestClient, aiosqlite.Connection]]:
    """Spin up an in-process app with a temporary DB seeded for search tests."""
    db_path = tmp_path / "hist.db"
    conn = await aiosqlite.connect(db_path)
    try:
        await load_schema(conn)
        app = create_app(db_connection=conn)
        with TestClient(app) as client:
            yield client, conn
    finally:
        await conn.close()


async def _session(conn: aiosqlite.Connection, title: str, description: str = "") -> str:
    s = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title=title,
        working_dir="/wd",
        model="sonnet",
        description=description or None,
    )
    return s.id


async def _message(conn: aiosqlite.Connection, session_id: str, content: str) -> None:
    await messages_db.insert_user(conn, session_id=session_id, content=content)


def _session_ids(payload: list[dict[str, object]]) -> set[str]:
    return {str(r["session_id"]) for r in payload}


# ---------------------------------------------------------------------------
# Integration: percent wildcard is treated literally
# ---------------------------------------------------------------------------


async def test_percent_literal_session_hit(
    search_client: tuple[TestClient, aiosqlite.Connection],
) -> None:
    """Searching ``100%`` returns only sessions whose title contains ``100%``."""
    client, conn = search_client
    target = await _session(conn, "Hit: 100% complete")
    _decoy = await _session(conn, "Hit: 1000 items")  # starts with 100 but no %

    resp = client.get("/api/history/search", params={"q": "100%"})
    assert resp.status_code == 200
    ids = _session_ids(resp.json())
    assert target in ids
    assert _decoy not in ids


async def test_percent_literal_message_hit(
    search_client: tuple[TestClient, aiosqlite.Connection],
) -> None:
    """Searching ``100%`` returns only messages containing the literal ``100%``."""
    client, conn = search_client
    sid = await _session(conn, "msg test")
    await _message(conn, sid, "progress is 100% done")
    await _message(conn, sid, "1000 items total")  # decoy — no %

    resp = client.get("/api/history/search", params={"q": "100%"})
    assert resp.status_code == 200
    hits = [r for r in resp.json() if r["kind"] == "message"]
    snippets = [h["snippet"] for h in hits]
    assert any("100%" in s for s in snippets)
    # The decoy message must not appear
    assert not any("1000 items" in s for s in snippets)


# ---------------------------------------------------------------------------
# Integration: underscore wildcard is treated literally
# ---------------------------------------------------------------------------


async def test_underscore_literal_session_hit(
    search_client: tuple[TestClient, aiosqlite.Connection],
) -> None:
    """Searching ``foo_bar`` matches only the literal substring, not any char."""
    client, conn = search_client
    target = await _session(conn, "Result: foo_bar value")
    decoy = await _session(conn, "Result: fooXbar value")  # _ as wildcard would match

    resp = client.get("/api/history/search", params={"q": "foo_bar"})
    assert resp.status_code == 200
    ids = _session_ids(resp.json())
    assert target in ids
    assert decoy not in ids


# ---------------------------------------------------------------------------
# Integration: literal backslash is findable
# ---------------------------------------------------------------------------


async def test_backslash_literal_session_hit(
    search_client: tuple[TestClient, aiosqlite.Connection],
) -> None:
    """A stored backslash is reachable when the user types one."""
    client, conn = search_client
    target = await _session(conn, r"Path: C:\Users\dave")

    resp = client.get("/api/history/search", params={"q": "\\"})
    assert resp.status_code == 200
    ids = _session_ids(resp.json())
    assert target in ids
