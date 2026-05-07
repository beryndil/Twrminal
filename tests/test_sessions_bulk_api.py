"""Integration tests for ``POST /api/sessions/bulk`` (gap-cycle-13-001).

Covers:
* Each op (close, delete, export, tag, untag) — happy-path and partial failure.
* Transactional semantics: a missing ID in the middle does not abort the batch.
* Export bundle round-trips through ``POST /api/sessions/import``.
* 422 on unknown op, missing tag_id for tag/untag.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db import tags as tags_db
from bearings.db.connection import load_schema
from bearings.web.app import create_app


@pytest.fixture
async def app_and_db(tmp_path: Path) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection]]:
    db_path = tmp_path / "bulk.db"
    conn = await aiosqlite.connect(db_path)
    try:
        await load_schema(conn)
        app = create_app(db_connection=conn)
        yield app, conn
    finally:
        await conn.close()


async def _new_chat(conn: aiosqlite.Connection, title: str = "t") -> str:
    s = await sessions_db.create(conn, kind="chat", title=title, working_dir="/wd", model="sonnet")
    return s.id


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def test_bulk_unknown_op_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "bogus", "session_ids": ["x"]},
        )
    assert resp.status_code == 422


async def test_bulk_empty_session_ids_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "close", "session_ids": []},
        )
    assert resp.status_code == 422


async def test_bulk_tag_missing_tag_id_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "tag", "session_ids": [sid]},
        )
    assert resp.status_code == 422


async def test_bulk_untag_missing_tag_id_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "untag", "session_ids": [sid]},
        )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# op=close
# ---------------------------------------------------------------------------


async def test_bulk_close_all_succeed(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    s1 = await _new_chat(conn, "a")
    s2 = await _new_chat(conn, "b")
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "close", "session_ids": [s1, s2]},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["op"] == "close"
    results = {r["session_id"]: r for r in body["results"]}
    assert results[s1]["ok"] is True
    assert results[s2]["ok"] is True
    # Verify DB state
    row1 = await sessions_db.get(conn, s1)
    row2 = await sessions_db.get(conn, s2)
    assert row1 is not None and row1.closed_at is not None
    assert row2 is not None and row2.closed_at is not None


async def test_bulk_close_partial_failure(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Missing ID in the middle does not abort the batch."""
    app, conn = app_and_db
    s1 = await _new_chat(conn, "a")
    s2 = await _new_chat(conn, "b")
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "close", "session_ids": [s1, "not-real", s2]},
        )
    assert resp.status_code == 200
    body = resp.json()
    results = {r["session_id"]: r for r in body["results"]}
    assert results[s1]["ok"] is True
    assert results["not-real"]["ok"] is False
    assert results[s2]["ok"] is True
    # Both real sessions closed despite the missing one.
    row1 = await sessions_db.get(conn, s1)
    row2 = await sessions_db.get(conn, s2)
    assert row1 is not None and row1.closed_at is not None
    assert row2 is not None and row2.closed_at is not None


# ---------------------------------------------------------------------------
# op=delete
# ---------------------------------------------------------------------------


async def test_bulk_delete_all_succeed(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    s1 = await _new_chat(conn, "a")
    s2 = await _new_chat(conn, "b")
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "delete", "session_ids": [s1, s2]},
        )
    assert resp.status_code == 200
    body = resp.json()
    results = {r["session_id"]: r for r in body["results"]}
    assert results[s1]["ok"] is True
    assert results[s2]["ok"] is True
    assert await sessions_db.get(conn, s1) is None
    assert await sessions_db.get(conn, s2) is None


async def test_bulk_delete_partial_failure(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    s1 = await _new_chat(conn, "a")
    s2 = await _new_chat(conn, "b")
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "delete", "session_ids": [s1, "missing", s2]},
        )
    assert resp.status_code == 200
    body = resp.json()
    results = {r["session_id"]: r for r in body["results"]}
    assert results[s1]["ok"] is True
    assert results["missing"]["ok"] is False
    assert "detail" in results["missing"]
    assert results[s2]["ok"] is True
    assert await sessions_db.get(conn, s1) is None
    assert await sessions_db.get(conn, s2) is None


# ---------------------------------------------------------------------------
# op=tag / op=untag
# ---------------------------------------------------------------------------


async def test_bulk_tag_attaches_to_all(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    s1 = await _new_chat(conn, "a")
    s2 = await _new_chat(conn, "b")
    tag = await tags_db.create(conn, name="bearings/exec")
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "tag", "session_ids": [s1, s2], "tag_id": tag.id},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert all(r["ok"] for r in body["results"])
    tags_s1 = await tags_db.list_for_session(conn, s1)
    tags_s2 = await tags_db.list_for_session(conn, s2)
    assert any(t.id == tag.id for t in tags_s1)
    assert any(t.id == tag.id for t in tags_s2)


async def test_bulk_untag_detaches_from_all(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    s1 = await _new_chat(conn, "a")
    s2 = await _new_chat(conn, "b")
    tag = await tags_db.create(conn, name="bearings/exec")
    await tags_db.attach(conn, session_id=s1, tag_id=tag.id)
    await tags_db.attach(conn, session_id=s2, tag_id=tag.id)
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "untag", "session_ids": [s1, s2], "tag_id": tag.id},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert all(r["ok"] for r in body["results"])
    tags_s1 = await tags_db.list_for_session(conn, s1)
    tags_s2 = await tags_db.list_for_session(conn, s2)
    assert not any(t.id == tag.id for t in tags_s1)
    assert not any(t.id == tag.id for t in tags_s2)


# ---------------------------------------------------------------------------
# op=export
# ---------------------------------------------------------------------------


async def test_bulk_export_returns_bundle(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    s1 = await _new_chat(conn, "session-one")
    s2 = await _new_chat(conn, "session-two")
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "export", "session_ids": [s1, s2]},
        )
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    body = resp.json()
    assert "sessions" in body
    assert len(body["sessions"]) == 2
    ids = {b["session"]["id"] for b in body["sessions"] if b is not None}
    assert ids == {s1, s2}


async def test_bulk_export_missing_id_produces_null_slot(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    s1 = await _new_chat(conn, "real")
    with TestClient(app) as client:
        resp = client.post(
            "/api/sessions/bulk",
            json={"op": "export", "session_ids": [s1, "ghost"]},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sessions"][0] is not None
    assert body["sessions"][1] is None


async def test_bulk_export_round_trips_via_import(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Export bundle from /bulk should be importable via POST /api/sessions/import."""
    app, conn = app_and_db
    # Create a session with a message so the export has meaningful content.
    sid = await _new_chat(conn, "round-trip")
    await messages_db.insert_user(conn, session_id=sid, content="hello")
    with TestClient(app) as client:
        export_resp = client.post(
            "/api/sessions/bulk",
            json={"op": "export", "session_ids": [sid]},
        )
        assert export_resp.status_code == 200
        bundle = export_resp.json()
        session_export = bundle["sessions"][0]
        assert session_export is not None

        # Delete the original so import can recreate it.
        client.delete(f"/api/sessions/{sid}")

        # Import via the existing single-session import endpoint.
        import_resp = client.post("/api/sessions/import", json=session_export)
    assert import_resp.status_code == 201
    imported = import_resp.json()
    assert imported["id"] == sid
    assert imported["title"] == "round-trip"
