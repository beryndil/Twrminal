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
        "title": "test session",  # v0.20.6: required at API boundary
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


def _seed_roles(
    db_path: Path,
    session_id: str,
    roles_and_contents: list[tuple[str, str]],
) -> list[str]:
    """Like `_seed_ordered` but lets the test pick a role per row so a
    conversation with alternating assistant/user turns can be built up
    in chronological order."""
    base = datetime.now(UTC)
    ids: list[str] = []
    for i, (role, content) in enumerate(roles_and_contents):
        stamp = (base + timedelta(seconds=i)).isoformat()
        ids.append(_seed_message(db_path, session_id, role, content, created_at=stamp))
    return ids


def _seed_tool_call(
    db_path: Path,
    session_id: str,
    *,
    name: str,
    message_id: str | None,
    tc_id: str | None = None,
) -> str:
    """Insert a tool_calls row for the warning-detector tests. `name`
    shows up in warning messages; `message_id` None models an orphan
    call that should be ignored by the detector."""
    call_id = tc_id or uuid4().hex

    async def _run() -> None:
        conn = await aiosqlite.connect(str(db_path))
        try:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute(
                "INSERT INTO tool_calls (id, session_id, message_id, name, "
                "input, started_at) VALUES (?, ?, ?, ?, ?, ?)",
                (call_id, session_id, message_id, name, "{}", datetime.now(UTC).isoformat()),
            )
            await conn.commit()
        finally:
            await conn.close()

    asyncio.run(_run())
    return call_id


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


# ---------- warnings (Slice 7) ----------------------------------------


def test_move_emits_warning_when_split_would_orphan_tool_call(
    client: TestClient, tmp_settings: Settings
) -> None:
    """Moving an assistant row but leaving its paired tool_result user
    row behind triggers the warn. Source is assistant-then-user; moving
    only the assistant orphans it."""
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    ids = _seed_roles(
        tmp_settings.storage.db_path,
        src["id"],
        [("assistant", "calls tool"), ("user", "tool result")],
    )
    _seed_tool_call(tmp_settings.storage.db_path, src["id"], name="Bash", message_id=ids[0])

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": [ids[0]]},
    )
    assert resp.status_code == 200
    warnings = resp.json()["warnings"]
    assert len(warnings) == 1
    assert warnings[0]["code"] == "orphan_tool_call"
    assert "Bash" in warnings[0]["message"]
    assert warnings[0]["details"]["assistant_message_id"] == ids[0]
    assert warnings[0]["details"]["user_message_id"] == ids[1]


def test_move_no_warning_when_whole_pair_moves(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    ids = _seed_roles(
        tmp_settings.storage.db_path,
        src["id"],
        [("assistant", "calls"), ("user", "result")],
    )
    _seed_tool_call(tmp_settings.storage.db_path, src["id"], name="Bash", message_id=ids[0])

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    assert resp.status_code == 200
    assert resp.json()["warnings"] == []


def test_split_emits_warning_when_boundary_cuts_group(
    client: TestClient, tmp_settings: Settings
) -> None:
    """Split after the assistant leaves the user tool_result stranded
    on the new session — same orphan, same warning."""
    src = _create(client, title="src")
    ids = _seed_roles(
        tmp_settings.storage.db_path,
        src["id"],
        [("user", "kickoff"), ("assistant", "calls"), ("user", "result")],
    )
    _seed_tool_call(tmp_settings.storage.db_path, src["id"], name="Read", message_id=ids[1])
    tag_id = _default_tag(client)

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": ids[1],  # assistant stays, user result moves
            "new_session": {"title": "spin", "tag_ids": [tag_id]},
        },
    )
    assert resp.status_code == 201
    warnings = resp.json()["result"]["warnings"]
    assert len(warnings) == 1
    assert warnings[0]["code"] == "orphan_tool_call"
    assert warnings[0]["details"]["tool_names"] == "Read"


def test_merge_never_emits_warnings(client: TestClient, tmp_settings: Settings) -> None:
    """Merge moves every source row together — the pair always rides
    the same boundary, so the detector has nothing to flag."""
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    ids = _seed_roles(
        tmp_settings.storage.db_path,
        src["id"],
        [("assistant", "calls"), ("user", "result")],
    )
    _seed_tool_call(tmp_settings.storage.db_path, src["id"], name="Bash", message_id=ids[0])

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": dst["id"], "delete_source": False},
    )
    assert resp.status_code == 200
    assert resp.json()["warnings"] == []


# ---------- Prometheus counter (Slice 7) -----------------------------


def _counter_value(client: TestClient, op: str) -> float:
    """Read bearings_session_reorg_total{op=...} from /metrics. Returns
    0.0 when the label combo hasn't been incremented yet — the counter
    only materializes the label pair on first `.inc()`."""
    from bearings.metrics import session_reorg_total

    return float(session_reorg_total.labels(op=op)._value.get())


def test_metric_increments_on_move(client: TestClient, tmp_settings: Settings) -> None:
    before = _counter_value(client, "move")
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a"])
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    assert resp.status_code == 200
    assert _counter_value(client, "move") == before + 1


def test_metric_increments_on_split(client: TestClient, tmp_settings: Settings) -> None:
    before = _counter_value(client, "split")
    src = _create(client, title="src")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])
    tag_id = _default_tag(client)
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": ids[0],
            "new_session": {"title": "x", "tag_ids": [tag_id]},
        },
    )
    assert resp.status_code == 201
    assert _counter_value(client, "split") == before + 1


def test_metric_increments_on_merge(client: TestClient, tmp_settings: Settings) -> None:
    before = _counter_value(client, "merge")
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a"])
    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": dst["id"], "delete_source": False},
    )
    assert resp.status_code == 200
    assert _counter_value(client, "merge") == before + 1


def test_metric_does_not_increment_on_noop_move(client: TestClient, tmp_settings: Settings) -> None:
    """Idempotent re-run with zero moves must not inflate the counter —
    it only reflects real ops."""
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a"])
    first = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    assert first.status_code == 200
    before_second = _counter_value(client, "move")
    second = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    assert second.status_code == 200
    assert second.json()["moved"] == 0
    assert _counter_value(client, "move") == before_second


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


# ---------- v0.3.25: auto-reopen on reorg -----------------------------


def test_move_reopens_closed_source(client: TestClient, tmp_settings: Settings) -> None:
    """Moving messages out of a closed source auto-clears `closed_at`
    on the source — work resumed means the flag is stale."""
    src = _create(client, title="closed source")
    dst = _create(client, title="dst")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])
    client.post(f"/api/sessions/{src['id']}/close")
    assert client.get(f"/api/sessions/{src['id']}").json()["closed_at"] is not None

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids[:1]},
    )
    assert resp.status_code == 200
    assert resp.json()["moved"] == 1
    assert client.get(f"/api/sessions/{src['id']}").json()["closed_at"] is None


def test_move_reopens_closed_target(client: TestClient, tmp_settings: Settings) -> None:
    """Moving messages INTO a closed target auto-reopens it — the
    charter is being amended."""
    src = _create(client, title="src")
    dst = _create(client, title="closed charter")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a"])
    client.post(f"/api/sessions/{dst['id']}/close")

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    assert resp.status_code == 200
    assert client.get(f"/api/sessions/{dst['id']}").json()["closed_at"] is None


def test_noop_move_leaves_closed_flag_alone(client: TestClient, tmp_settings: Settings) -> None:
    """An idempotent re-run with zero real moves must NOT reopen —
    we only reset the flag when actual work landed."""
    src = _create(client, title="src")
    dst = _create(client, title="dst")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a"])
    client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    client.post(f"/api/sessions/{src['id']}/close")

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/move",
        json={"target_session_id": dst["id"], "message_ids": ids},
    )
    assert resp.status_code == 200
    assert resp.json()["moved"] == 0
    assert client.get(f"/api/sessions/{src['id']}").json()["closed_at"] is not None


def test_split_reopens_closed_source(client: TestClient, tmp_settings: Settings) -> None:
    """Splitting off a closed session reopens the source — the user
    just amended it."""
    src = _create(client, title="closed, then split")
    ids = _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b", "c"])
    client.post(f"/api/sessions/{src['id']}/close")
    tag_id = _default_tag(client)

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/split",
        json={
            "after_message_id": ids[0],
            "new_session": {"title": "offshoot", "tag_ids": [tag_id]},
        },
    )
    assert resp.status_code == 201
    assert client.get(f"/api/sessions/{src['id']}").json()["closed_at"] is None


def test_merge_reopens_closed_target(client: TestClient, tmp_settings: Settings) -> None:
    """Merging messages into a closed target reopens it."""
    src = _create(client, title="live src")
    dst = _create(client, title="closed charter")
    _seed_ordered(tmp_settings.storage.db_path, src["id"], ["a", "b"])
    client.post(f"/api/sessions/{dst['id']}/close")

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/merge",
        json={"target_session_id": dst["id"], "delete_source": False},
    )
    assert resp.status_code == 200
    assert resp.json()["moved"] == 2
    assert client.get(f"/api/sessions/{dst['id']}").json()["closed_at"] is None
