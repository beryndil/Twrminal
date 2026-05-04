"""Integration tests for the checkpoints API endpoints (G6).

Covers the full surface:

* ``POST /api/checkpoints`` — create a checkpoint anchored at a message.
* ``GET /api/checkpoints?session_id=...`` — list checkpoints for one session.
* ``DELETE /api/checkpoints/{id}`` — delete one.
* ``POST /api/checkpoints/{id}/fork`` — clone the source session +
  copy messages up to and including the anchor.

The fork test exercises the DB-level branching primitive Bearings owns
(per the SDK-primitives memory) — verifies the new session row exists,
inherits the source's working_dir + model + routing fields, and that
the new session's transcript reproduces the source's history up to the
anchor message.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.config.constants import (
    DEFAULT_CHECKPOINT_LABEL_TEMPLATE,
    SESSION_KIND_CHAT,
)
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.web.app import create_app


@pytest.fixture
async def app_and_db(tmp_path: Path) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection]]:
    db_path = tmp_path / "checkpoints_api.db"
    conn = await aiosqlite.connect(db_path)
    try:
        await load_schema(conn)
        app = create_app(db_connection=conn)
        yield app, conn
    finally:
        await conn.close()


async def _new_chat(conn: aiosqlite.Connection, title: str = "t") -> str:
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title=title, working_dir="/wd", model="sonnet"
    )
    return session.id


async def _seed_turn(
    conn: aiosqlite.Connection,
    session_id: str,
    user_content: str = "hi",
    assistant_content: str = "hello",
) -> tuple[str, str]:
    """Insert one user + one assistant message; return their ids."""
    user = await messages_db.insert_user(conn, session_id=session_id, content=user_content)
    assistant = await messages_db._insert(
        conn, session_id=session_id, role="assistant", content=assistant_content
    )
    return user.id, assistant.id


async def test_create_checkpoint_returns_201_and_row(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    _user, anchor = await _seed_turn(conn, sid)
    with TestClient(app) as client:
        response = client.post(
            "/api/checkpoints",
            json={"session_id": sid, "message_id": anchor, "label": "Before refactor"},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["session_id"] == sid
    assert body["message_id"] == anchor
    assert body["label"] == "Before refactor"
    assert body["id"].startswith("cpt_")
    assert isinstance(body["created_at"], str) and len(body["created_at"]) > 0


async def test_create_checkpoint_synthesises_label_when_omitted(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Omitting label falls back to ``DEFAULT_CHECKPOINT_LABEL_TEMPLATE``."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    _user, anchor = await _seed_turn(conn, sid)
    with TestClient(app) as client:
        first = client.post("/api/checkpoints", json={"session_id": sid, "message_id": anchor})
        second = client.post("/api/checkpoints", json={"session_id": sid, "message_id": anchor})
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["label"] == DEFAULT_CHECKPOINT_LABEL_TEMPLATE.format(n=1)
    assert second.json()["label"] == DEFAULT_CHECKPOINT_LABEL_TEMPLATE.format(n=2)


async def test_create_checkpoint_404_on_missing_session(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    _user, anchor = await _seed_turn(conn, sid)
    with TestClient(app) as client:
        response = client.post(
            "/api/checkpoints",
            json={"session_id": "ses_nope", "message_id": anchor},
        )
    assert response.status_code == 404


async def test_create_checkpoint_404_on_message_not_in_session(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid_a = await _new_chat(conn, title="a")
    sid_b = await _new_chat(conn, title="b")
    _user, anchor_b = await _seed_turn(conn, sid_b)
    with TestClient(app) as client:
        response = client.post(
            "/api/checkpoints",
            json={"session_id": sid_a, "message_id": anchor_b},
        )
    assert response.status_code == 404


async def test_list_checkpoints_returns_newest_first(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    _user, anchor = await _seed_turn(conn, sid)
    with TestClient(app) as client:
        for label in ("first", "second", "third"):
            response = client.post(
                "/api/checkpoints",
                json={"session_id": sid, "message_id": anchor, "label": label},
            )
            assert response.status_code == 201
        listing = client.get("/api/checkpoints", params={"session_id": sid})
    assert listing.status_code == 200
    rows = listing.json()
    assert {row["label"] for row in rows} == {"first", "second", "third"}
    assert rows[0]["label"] == "third"


async def test_list_checkpoints_empty_for_unknown_session(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.get("/api/checkpoints", params={"session_id": "ses_nope"})
    assert response.status_code == 200
    assert response.json() == []


async def test_delete_checkpoint_204_and_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    _user, anchor = await _seed_turn(conn, sid)
    with TestClient(app) as client:
        created = client.post(
            "/api/checkpoints",
            json={"session_id": sid, "message_id": anchor, "label": "rm"},
        )
        cp_id = created.json()["id"]
        first_delete = client.delete(f"/api/checkpoints/{cp_id}")
        second_delete = client.delete(f"/api/checkpoints/{cp_id}")
    assert first_delete.status_code == 204
    assert second_delete.status_code == 404


async def test_fork_checkpoint_clones_session_and_messages_up_to_anchor(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """The fork primitive copies history up to (and including) the anchor."""
    app, conn = app_and_db
    sid = await _new_chat(conn, title="Source session")
    # Seed three turns.
    _user1, anchor = await _seed_turn(conn, sid, "first user", "first assistant")
    _user2, _assistant2 = await _seed_turn(conn, sid, "second user", "second assistant")
    _user3, _assistant3 = await _seed_turn(conn, sid, "third user", "third assistant")
    with TestClient(app) as client:
        cp_resp = client.post(
            "/api/checkpoints",
            json={"session_id": sid, "message_id": anchor, "label": "boundary"},
        )
        cp_id = cp_resp.json()["id"]
        fork_resp = client.post(f"/api/checkpoints/{cp_id}/fork")
    assert fork_resp.status_code == 201
    fork_body = fork_resp.json()
    new_sid = fork_body["new_session_id"]
    assert fork_body["source_session_id"] == sid
    assert fork_body["checkpoint_id"] == cp_id
    # Anchor was the second message overall (after one user); fork copies
    # messages with rowid ≤ anchor.seq, so we expect 2 messages.
    assert fork_body["message_count"] == 2
    # Verify the new session row exists + inherits source fields.
    new_session = await sessions_db.get(conn, new_sid)
    assert new_session is not None
    assert new_session.title.endswith("(fork)")
    assert new_session.working_dir == "/wd"
    assert new_session.model == "sonnet"
    # Verify transcript copy.
    new_messages = await messages_db.list_for_session(conn, new_sid)
    assert len(new_messages) == 2
    assert new_messages[0].role == "user"
    assert new_messages[0].content == "first user"
    assert new_messages[1].role == "assistant"
    assert new_messages[1].content == "first assistant"
    # Source session is untouched.
    src_messages = await messages_db.list_for_session(conn, sid)
    assert len(src_messages) == 6


async def test_fork_checkpoint_404_when_checkpoint_missing(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.post("/api/checkpoints/cpt_nope/fork")
    assert response.status_code == 404
