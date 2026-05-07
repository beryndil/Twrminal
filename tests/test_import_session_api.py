"""Integration tests for ``POST /api/sessions/import``.

Per ``docs/behavior/sessions.md`` §"Import contract":

* 201 with correct SessionOut on a fresh import.
* Round-trip: export a session, import to a second DB, verify rows match.
* 409 on duplicate session_id (without force).
* ``?force=true`` deletes existing and reimports cleanly.
* 422 on malformed body.
* Messages, tool_calls, and checkpoints are all restored.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.config.constants import SESSION_KIND_CHAT
from bearings.db import checkpoints as checkpoints_db
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.web.app import create_app


@pytest.fixture
async def app_and_db(tmp_path: Path) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection]]:
    db_path = tmp_path / "import.db"
    conn = await aiosqlite.connect(db_path)
    try:
        await load_schema(conn)
        app = create_app(db_connection=conn)
        yield app, conn
    finally:
        await conn.close()


async def _make_session(conn: aiosqlite.Connection, title: str = "Orig") -> str:
    s = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title=title,
        working_dir="/wd",
        model="claude-sonnet-4-5",
    )
    return s.id


def _export_blob(client: TestClient, session_id: str) -> dict[str, object]:
    resp = client.get(f"/api/sessions/{session_id}/export")
    assert resp.status_code == 200
    result: dict[str, object] = resp.json()
    return result


# ---------------------------------------------------------------------------
# Round-trip: export from one DB, import into another
# ---------------------------------------------------------------------------


async def test_import_round_trip(tmp_path: Path) -> None:
    """Export a session (with messages + checkpoint) and import it elsewhere."""
    # Source DB
    src_conn = await aiosqlite.connect(tmp_path / "src.db")
    await load_schema(src_conn)
    src_app = create_app(db_connection=src_conn)

    sid = await _make_session(src_conn, "Round-Trip")
    user_msg = await messages_db.insert_user(src_conn, session_id=sid, content="hello")
    await checkpoints_db.create(src_conn, session_id=sid, message_id=user_msg.id, label="snap1")

    with TestClient(src_app) as src_client:
        blob = _export_blob(src_client, sid)

    await src_conn.close()

    # Destination DB
    dst_conn = await aiosqlite.connect(tmp_path / "dst.db")
    await load_schema(dst_conn)
    dst_app = create_app(db_connection=dst_conn)

    with TestClient(dst_app) as dst_client:
        resp = dst_client.post("/api/sessions/import", json=blob)

    assert resp.status_code == 201
    out = resp.json()
    assert out["id"] == sid
    assert out["title"] == "Round-Trip"

    # Messages preserved
    msgs = await messages_db.list_for_session(dst_conn, sid)
    assert len(msgs) == 1
    assert msgs[0].id == user_msg.id
    assert msgs[0].content == "hello"

    # Checkpoint preserved
    cps = await checkpoints_db.list_for_session(dst_conn, sid)
    assert len(cps) == 1
    assert cps[0].label == "snap1"

    await dst_conn.close()


# ---------------------------------------------------------------------------
# 409 on duplicate
# ---------------------------------------------------------------------------


async def test_import_409_on_duplicate(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _make_session(conn, "Dup Test")
    with TestClient(app) as client:
        blob = _export_blob(client, sid)
        # First import succeeds — but sid already in the DB (same conn).
        # Delete the original so we can import fresh then attempt a second import.
        client.delete(f"/api/sessions/{sid}")
        resp1 = client.post("/api/sessions/import", json=blob)
        assert resp1.status_code == 201
        # Second import: same session_id → 409
        resp2 = client.post("/api/sessions/import", json=blob)
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"]


# ---------------------------------------------------------------------------
# ?force=true overwrites
# ---------------------------------------------------------------------------


async def test_import_force_overwrites(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _make_session(conn, "Force Test")
    with TestClient(app) as client:
        blob = _export_blob(client, sid)
        # Delete so we can do a clean first import
        client.delete(f"/api/sessions/{sid}")
        resp1 = client.post("/api/sessions/import", json=blob)
        assert resp1.status_code == 201
        # Force reimport → should succeed with 201
        resp2 = client.post("/api/sessions/import?force=true", json=blob)
        assert resp2.status_code == 201
        assert resp2.json()["id"] == sid


# ---------------------------------------------------------------------------
# 422 on malformed body
# ---------------------------------------------------------------------------


async def test_import_422_on_bad_body(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        resp = client.post("/api/sessions/import", json={"not": "a session export"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# All message roles are restored
# ---------------------------------------------------------------------------


async def test_import_restores_all_message_roles(tmp_path: Path) -> None:
    src_conn = await aiosqlite.connect(tmp_path / "src.db")
    await load_schema(src_conn)
    src_app = create_app(db_connection=src_conn)

    sid = await _make_session(src_conn)
    await messages_db.insert_user(src_conn, session_id=sid, content="u")
    await messages_db.insert_system(src_conn, session_id=sid, content="s")
    await src_conn.close()

    # re-open to export
    src_conn = await aiosqlite.connect(tmp_path / "src.db")
    src_app = create_app(db_connection=src_conn)
    with TestClient(src_app) as src_client:
        blob = _export_blob(src_client, sid)
    await src_conn.close()

    dst_conn = await aiosqlite.connect(tmp_path / "dst.db")
    await load_schema(dst_conn)
    dst_app = create_app(db_connection=dst_conn)
    with TestClient(dst_app) as dst_client:
        resp = dst_client.post("/api/sessions/import", json=blob)
    assert resp.status_code == 201
    msgs = await messages_db.list_for_session(dst_conn, sid)
    roles = {m.role for m in msgs}
    assert roles == {"user", "system"}
    await dst_conn.close()


# ---------------------------------------------------------------------------
# Location header is set on 201
# ---------------------------------------------------------------------------


async def test_import_location_header(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _make_session(conn, "Loc Test")
    with TestClient(app) as client:
        blob = _export_blob(client, sid)
        client.delete(f"/api/sessions/{sid}")
        resp = client.post("/api/sessions/import", json=blob)
    assert resp.status_code == 201
    assert resp.headers.get("location") == f"/api/sessions/{sid}"
