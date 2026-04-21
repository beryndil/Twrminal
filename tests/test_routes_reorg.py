"""Tests for the `/api/sessions/{id}/reorg/*` routes — Slice 2 of the
Session Reorg plan. Covers move + split with their happy paths,
validation branches, and the runner-stop side effect.

Seeds messages via a separate aiosqlite connection (WAL mode lets the
app's connection see the committed rows). There is no public HTTP
surface for creating a message outside the WS agent flow, and this
keeps the tests synchronous alongside the other `test_routes_*`
files.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite
from fastapi.testclient import TestClient

from bearings.config import Settings


def _default_tag(client: TestClient) -> int:
    existing = client.get("/api/tags").json()
    if existing:
        tag_id: int = existing[0]["id"]
        return tag_id
    created = client.post("/api/tags", json={"name": "default"})
    return int(created.json()["id"])


def _create(client: TestClient, **kwargs: Any) -> dict[str, Any]:
    tag_ids = kwargs.pop("tag_ids", None) or [_default_tag(client)]
    body = {
        "working_dir": "/tmp",
        "model": "claude-sonnet-4-6",
        "title": None,
        "tag_ids": tag_ids,
        **kwargs,
    }
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _seed_message(
    db_path: Path,
    session_id: str,
    role: str,
    content: str,
    *,
    created_at: str | None = None,
) -> str:
    """Insert a message row via a fresh aiosqlite connection.

    WAL mode means the app's long-lived connection picks the row up on
    the next read. Pass an explicit `created_at` (ISO string) when the
    test relies on strict chronological ordering — `datetime.now` can
    collide at microsecond resolution across back-to-back inserts.
    """
    msg_id = uuid4().hex
    stamp = created_at or datetime.now(UTC).isoformat()

    async def _run() -> None:
        conn = await aiosqlite.connect(str(db_path))
        try:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute(
                "INSERT INTO messages (id, session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (msg_id, session_id, role, content, stamp),
            )
            await conn.commit()
        finally:
            await conn.close()

    asyncio.run(_run())
    return msg_id


def _seed_ordered(
    db_path: Path, session_id: str, contents: list[str], role: str = "user"
) -> list[str]:
    """Seed N messages with strictly increasing created_at stamps so
    `list_messages` order is deterministic. Returns ids in order."""
    base = datetime.now(UTC)
    ids: list[str] = []
    for i, content in enumerate(contents):
        stamp = (base + timedelta(seconds=i)).isoformat()
        ids.append(_seed_message(db_path, session_id, role, content, created_at=stamp))
    return ids


# ---------- move ------------------------------------------------------


def test_move_happy_path(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b", "c"])

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids[:2]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["moved"] == 2
    assert body["tool_calls_followed"] == 0
    assert body["warnings"] == []

    src_after = client.get(f"/api/sessions/{src['id']}").json()
    dst_after = client.get(f"/api/sessions/{dst['id']}").json()
    assert src_after["message_count"] == 1
    assert dst_after["message_count"] == 2


def test_move_rejects_empty_message_ids(client: TestClient) -> None:
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": []},
    )
    assert resp.status_code == 400
    assert "non-empty" in resp.json()["detail"]


def test_move_rejects_same_source_and_target(client: TestClient) -> None:
    src = _create(client, title="src")
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": src["id"], "message_ids": ["x"]},
    )
    assert resp.status_code == 400
    assert "must differ" in resp.json()["detail"]


def test_move_404_on_missing_source(client: TestClient) -> None:
    dst = _create(client, title="dst")
    resp = client.post(
        "/api/sessions/ghost/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ["x"]},
    )
    assert resp.status_code == 404
    assert "source" in resp.json()["detail"]


def test_move_404_on_missing_target(client: TestClient) -> None:
    src = _create(client, title="src")
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": "ghost", "message_ids": ["x"]},
    )
    assert resp.status_code == 404
    assert "target" in resp.json()["detail"]


class _MockRunner:
    """Minimal stand-in for `SessionRunner` when the test only cares
    about which lifecycle methods the reorg route calls. `shutdown`
    exists because the FastAPI lifespan drain iterates every runner on
    exit and awaits `shutdown()`; without it the TestClient teardown
    raises AttributeError and taints an otherwise-passing test."""

    def __init__(self, name: str, stops: list[str]) -> None:
        self._name = name
        self._stops = stops

    async def request_stop(self) -> None:
        self._stops.append(self._name)

    async def shutdown(self) -> None:
        # Lifespan drain path — nothing to tear down for the mock.
        return None


def test_move_stops_live_runners(client: TestClient, tmp_settings: Settings) -> None:
    """Both source and target runners get `request_stop()` so the
    SDK's in-memory context rebuilds against the new DB state on the
    next turn."""
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    msg_id = _seed_message(tmp_settings.storage.db_path, src["id"], "user", "x")

    stops: list[str] = []
    registry = client.app.state.runners  # type: ignore[attr-defined]
    registry._runners[src["id"]] = _MockRunner("src", stops)  # type: ignore[assignment]
    registry._runners[dst["id"]] = _MockRunner("dst", stops)  # type: ignore[assignment]

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": [msg_id]},
    )
    assert resp.status_code == 200
    assert sorted(stops) == ["dst", "src"]


# ---------- split -----------------------------------------------------


def test_split_happy_path(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src", working_dir="/src/dir", model="claude-haiku-4")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b", "c", "d"])
    tag_id = _default_tag(client)

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": ids[1],
            "new_session": {"title": "after-b", "tag_ids": [tag_id]},
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["result"]["moved"] == 2
    assert body["result"]["warnings"] == []
    new_session = body["session"]
    assert new_session["title"] == "after-b"
    # Defaults copied from source.
    assert new_session["working_dir"] == "/src/dir"
    assert new_session["model"] == "claude-haiku-4"

    src_after = client.get(f"/api/sessions/{src['id']}").json()
    new_after = client.get(f"/api/sessions/{new_session['id']}").json()
    assert src_after["message_count"] == 2
    assert new_after["message_count"] == 2


def test_split_overrides_model_and_working_dir(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src", working_dir="/src/dir", model="claude-haiku-4")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])
    tag_id = _default_tag(client)

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": ids[0],
            "new_session": {
                "title": "override",
                "tag_ids": [tag_id],
                "working_dir": "/other",
                "model": "claude-opus-4",
            },
        },
    )
    assert resp.status_code == 201
    new_session = resp.json()["session"]
    assert new_session["working_dir"] == "/other"
    assert new_session["model"] == "claude-opus-4"


def test_split_attaches_tags(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])
    t1 = _default_tag(client)
    t2 = int(client.post("/api/tags", json={"name": "second"}).json()["id"])

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": ids[0],
            "new_session": {"title": "x", "tag_ids": [t1, t2]},
        },
    )
    assert resp.status_code == 201
    new_id = resp.json()["session"]["id"]
    tag_ids = {row["id"] for row in client.get(f"/api/sessions/{new_id}/tags").json()}
    assert tag_ids == {t1, t2}


def test_split_404_on_missing_source(client: TestClient) -> None:
    tag_id = _default_tag(client)
    resp = client.post(
        "/api/sessions/ghost/reorg/split",
        json={
            "after_message_id": "irrelevant",
            "new_session": {"title": "x", "tag_ids": [tag_id]},
        },
    )
    assert resp.status_code == 404


def test_split_404_on_anchor_not_in_session(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    _seed_message(tmp_settings.storage.db_path, src["id"], "user", "x")
    tag_id = _default_tag(client)
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": "ghost",
            "new_session": {"title": "x", "tag_ids": [tag_id]},
        },
    )
    assert resp.status_code == 404
    assert "not in session" in resp.json()["detail"]


def test_split_400_when_no_messages_after_anchor(
    client: TestClient, tmp_settings: Settings
) -> None:
    src = _create(client, title="src")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])
    tag_id = _default_tag(client)
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": ids[-1],
            "new_session": {"title": "x", "tag_ids": [tag_id]},
        },
    )
    assert resp.status_code == 400
    assert "no messages after" in resp.json()["detail"]


def test_split_400_on_missing_tag_ids(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": ids[0],
            "new_session": {"title": "x", "tag_ids": []},
        },
    )
    assert resp.status_code == 400
    assert "tag_id" in resp.json()["detail"]


def test_split_400_on_bad_tag_id(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": ids[0],
            "new_session": {"title": "x", "tag_ids": [9999]},
        },
    )
    assert resp.status_code == 400
    assert "9999" in resp.json()["detail"]


def test_split_stops_source_runner(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])
    tag_id = _default_tag(client)

    stops: list[str] = []
    registry = client.app.state.runners  # type: ignore[attr-defined]
    registry._runners[src["id"]] = _MockRunner("src", stops)  # type: ignore[assignment]

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": ids[0],
            "new_session": {"title": "x", "tag_ids": [tag_id]},
        },
    )
    assert resp.status_code == 201
    assert stops == ["src"]


# ---------- merge -----------------------------------------------------


def test_merge_happy_path(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b", "c"])

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": dst["id"], "delete_source": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["moved"] == 3
    assert body["deleted_source"] is False
    assert body["warnings"] == []

    # Source kept, emptied; target grew to 3.
    src_after = client.get(f"/api/sessions/{src['id']}").json()
    dst_after = client.get(f"/api/sessions/{dst['id']}").json()
    assert src_after["message_count"] == 0
    assert dst_after["message_count"] == 3


def test_merge_deletes_source_when_requested(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": dst["id"], "delete_source": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted_source"] is True

    # Source gone, target kept both messages (delete runs AFTER the
    # move so the cascade doesn't swallow the just-moved rows).
    assert client.get(f"/api/sessions/{src['id']}").status_code == 404
    dst_after = client.get(f"/api/sessions/{dst['id']}").json()
    assert dst_after["message_count"] == 2


def test_merge_empty_source_is_noop(client: TestClient) -> None:
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": dst["id"], "delete_source": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["moved"] == 0
    assert body["deleted_source"] is False


def test_merge_empty_source_deletes_when_requested(client: TestClient) -> None:
    """delete_source honored even when there were no messages to move
    — lets the UI clear out an orphaned empty session with one click."""
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": dst["id"], "delete_source": True},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted_source"] is True
    assert client.get(f"/api/sessions/{src['id']}").status_code == 404


def test_merge_rejects_same_source_and_target(client: TestClient) -> None:
    src = _create(client, title="src")
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": src["id"], "delete_source": False},
    )
    assert resp.status_code == 400
    assert "must differ" in resp.json()["detail"]


def test_merge_404_on_missing_source(client: TestClient) -> None:
    dst = _create(client, title="dst")
    resp = client.post(
        "/api/sessions/ghost/reorg/merge",
        json={"target_session_id": dst["id"], "delete_source": False},
    )
    assert resp.status_code == 404
    assert "source" in resp.json()["detail"]


def test_merge_404_on_missing_target(client: TestClient) -> None:
    src = _create(client, title="src")
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": "ghost", "delete_source": False},
    )
    assert resp.status_code == 404
    assert "target" in resp.json()["detail"]


def test_merge_stops_both_runners(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    _seed_message(tmp_settings.storage.db_path, src["id"], "user", "x")

    stops: list[str] = []
    registry = client.app.state.runners  # type: ignore[attr-defined]
    registry._runners[src["id"]] = _MockRunner("src", stops)  # type: ignore[assignment]
    registry._runners[dst["id"]] = _MockRunner("dst", stops)  # type: ignore[assignment]

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": dst["id"], "delete_source": False},
    )
    assert resp.status_code == 200
    assert sorted(stops) == ["dst", "src"]


# ---------- audits ----------------------------------------------------


def test_move_records_audit(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    # Response echoes the audit id so the undo handler can DELETE it
    # directly without a follow-up list call.
    body = resp.json()
    assert isinstance(body["audit_id"], int)
    audits = client.get(f"/api/sessions/{src['id']}/reorg/audits").json()
    assert len(audits) == 1
    assert audits[0]["id"] == body["audit_id"]
    assert audits[0]["op"] == "move"
    assert audits[0]["message_count"] == 2
    assert audits[0]["target_session_id"] == dst["id"]
    assert audits[0]["target_title_snapshot"] == "dst"


def test_split_records_audit(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b", "c"])
    tag_id = _default_tag(client)
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": ids[0],
            "new_session": {"title": "spin-off", "tag_ids": [tag_id]},
        },
    )
    split_body = resp.json()
    new_id = split_body["session"]["id"]
    assert isinstance(split_body["result"]["audit_id"], int)
    audits = client.get(f"/api/sessions/{src['id']}/reorg/audits").json()
    assert [a["op"] for a in audits] == ["split"]
    assert audits[0]["id"] == split_body["result"]["audit_id"]
    assert audits[0]["target_session_id"] == new_id
    assert audits[0]["target_title_snapshot"] == "spin-off"


def test_merge_records_audit_and_preserves_after_target_delete(
    client: TestClient, tmp_settings: Settings
) -> None:
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a"])
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": dst["id"], "delete_source": False},
    )
    merge_body = resp.json()
    assert isinstance(merge_body["audit_id"], int)
    # Delete the target — audit row's target_session_id flips to null
    # but the snapshotted title stays so the UI has something to show.
    client.delete(f"/api/sessions/{dst['id']}")
    audits = client.get(f"/api/sessions/{src['id']}/reorg/audits").json()
    assert len(audits) == 1
    assert audits[0]["id"] == merge_body["audit_id"]
    assert audits[0]["op"] == "merge"
    assert audits[0]["target_session_id"] is None
    assert audits[0]["target_title_snapshot"] == "dst"


def test_merge_skips_audit_when_source_deleted(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": dst["id"], "delete_source": True},
    )
    # No audit row was written — cascade would've dropped it anyway.
    assert resp.json()["audit_id"] is None
    # Source is gone so the audit endpoint 404s.
    assert client.get(f"/api/sessions/{src['id']}/reorg/audits").status_code == 404


def test_audit_list_empty_for_untouched_session(client: TestClient) -> None:
    s = _create(client, title="solo")
    resp = client.get(f"/api/sessions/{s['id']}/reorg/audits")
    assert resp.status_code == 200
    assert resp.json() == []


def test_audit_list_404_on_missing_session(client: TestClient) -> None:
    resp = client.get("/api/sessions/ghost/reorg/audits")
    assert resp.status_code == 404


def test_delete_audit_round_trip(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a"])
    client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    audits = client.get(f"/api/sessions/{src['id']}/reorg/audits").json()
    assert len(audits) == 1
    audit_id = audits[0]["id"]

    resp = client.delete(f"/api/sessions/{src['id']}/reorg/audits/{audit_id}")
    assert resp.status_code == 204
    # Row gone, list is empty again.
    assert client.get(f"/api/sessions/{src['id']}/reorg/audits").json() == []


def test_delete_audit_404_on_wrong_session(client: TestClient, tmp_settings: Settings) -> None:
    """A stale URL can't delete another session's audits."""
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    other = _create(client, title="other")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a"])
    client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    audit_id = client.get(f"/api/sessions/{src['id']}/reorg/audits").json()[0]["id"]
    resp = client.delete(f"/api/sessions/{other['id']}/reorg/audits/{audit_id}")
    assert resp.status_code == 404


def test_delete_audit_404_on_missing_id(client: TestClient) -> None:
    src = _create(client, title="src")
    resp = client.delete(f"/api/sessions/{src['id']}/reorg/audits/99999")
    assert resp.status_code == 404


def test_noop_move_records_no_audit(client: TestClient, tmp_settings: Settings) -> None:
    """Idempotent re-run with zero real moves leaves no divider."""
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a"])
    first = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    assert first.status_code == 200
    # Second call moves 0 since the row is already on dst — source
    # audit list must still be 1, not 2.
    second = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["moved"] == 0
    # No divider recorded → audit_id is null, not the first op's id.
    assert second_body["audit_id"] is None
    audits = client.get(f"/api/sessions/{src['id']}/reorg/audits").json()
    assert len(audits) == 1
