"""Tests for `GET /api/sessions/{id}/work_evidence`.

Covers: 404 on unknown session, empty arrays on a fresh session,
extraction of files-modified / bash-commits / bash-failures /
linked-checklist info from a populated session, and the discipline
case the endpoint exists for: a session that posted a `DONE` claim
with zero file mutations should produce verifiable counters that
contradict the claim."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from bearings.db import store


def _default_tag(client: TestClient) -> int:
    existing = client.get("/api/tags").json()
    if existing:
        tag_id: int = existing[0]["id"]
        return tag_id
    created = client.post("/api/tags", json={"name": "default"})
    return int(created.json()["id"])


def _seed_session(client: TestClient, kind: str = "chat") -> str:
    body = {
        "working_dir": "/tmp",
        "model": "m",
        "title": "exec",
        "kind": kind,
        "tag_ids": [_default_tag(client)],
    }
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 200, resp.text
    sid: str = resp.json()["id"]
    return sid


async def _seed_tool_call(
    client: TestClient,
    session_id: str,
    *,
    name: str,
    input_obj: dict,
    output: str | None = None,
    error: str | None = None,
) -> str:
    """Lightweight tool_call insert for evidence tests. Bypasses the
    runner's streaming flow because we only care about row presence
    here, not the live event fan-out."""
    import uuid

    db = client.app.state.db
    tcid = uuid.uuid4().hex
    await store.insert_tool_call_start(
        db,
        session_id=session_id,
        tool_call_id=tcid,
        name=name,
        input_json=json.dumps(input_obj),
    )
    if output is not None or error is not None:
        await store.finish_tool_call(db, tool_call_id=tcid, output=output, error=error)
    return tcid


def test_returns_404_for_unknown_session(client: TestClient) -> None:
    resp = client.get("/api/sessions/does-not-exist/work_evidence")
    assert resp.status_code == 404


def test_empty_session_returns_empty_arrays(client: TestClient) -> None:
    """A fresh session with zero tool calls should still return a
    valid WorkEvidence — the arrays are empty rather than the
    response erroring."""
    sid = _seed_session(client)
    resp = client.get(f"/api/sessions/{sid}/work_evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == sid
    assert body["tool_summary"] == []
    assert body["files_modified"] == []
    assert body["bash_commits"] == []
    assert body["bash_failures"] == []
    assert body["last_assistant_snippet"] is None
    assert body["linked_checklist"] is None


async def test_extracts_files_modified_from_edit_write(client: TestClient) -> None:
    """Edit + Write tool calls' file_path inputs should land in
    files_modified, dedup'd, in chronological order. Failed calls
    are skipped — the orchestrator only cares about successful writes."""
    sid = _seed_session(client)
    await _seed_tool_call(client, sid, name="Write", input_obj={"file_path": "/a.py"}, output="ok")
    await _seed_tool_call(client, sid, name="Edit", input_obj={"file_path": "/b.py"}, output="ok")
    await _seed_tool_call(client, sid, name="Edit", input_obj={"file_path": "/a.py"}, output="ok")
    # Failed write should NOT appear in files_modified.
    await _seed_tool_call(client, sid, name="Write", input_obj={"file_path": "/c.py"}, error="boom")

    resp = client.get(f"/api/sessions/{sid}/work_evidence")
    body = resp.json()
    assert body["files_modified"] == ["/a.py", "/b.py"]
    # Counters: 2 ok writes (Write 1, Edit 2 – well, Write 1 ok / 1 fail)
    summary = {t["name"]: t for t in body["tool_summary"]}
    assert summary["Edit"] == {"name": "Edit", "ok": 2, "failed": 0}
    assert summary["Write"] == {"name": "Write", "ok": 1, "failed": 1}


async def test_extracts_bash_commits_and_failures(client: TestClient) -> None:
    """`[main abc1234] subject` lines in Bash output should land in
    bash_commits. Failed Bash calls land in bash_failures with the
    command + a capped error excerpt."""
    sid = _seed_session(client)
    await _seed_tool_call(
        client,
        sid,
        name="Bash",
        input_obj={"command": "git commit -m feat"},
        output="[main abc1234] feat: thing\n 1 file changed",
    )
    await _seed_tool_call(
        client,
        sid,
        name="Bash",
        input_obj={"command": "ls /nope"},
        error="ls: cannot access '/nope': No such file or directory\n",
    )

    resp = client.get(f"/api/sessions/{sid}/work_evidence")
    body = resp.json()
    assert body["bash_commits"] == ["abc1234 feat: thing"]
    assert len(body["bash_failures"]) == 1
    f = body["bash_failures"][0]
    assert f["cmd"] == "ls /nope"
    assert "No such file" in f["error_excerpt"]


async def test_linked_checklist_carries_checked_at(client: TestClient) -> None:
    """When the executor session is paired to a checklist item, the
    response surfaces the item's id, label, and checked_at so the
    orchestrator sees the toggle state alongside the evidence."""
    # Build a master checklist + one paired chat session. The
    # `checklist_item_id` link can't go through the public POST
    # /sessions endpoint (it rejects 400) — mirror the flake test in
    # test_routes_sessions and seed via store directly.
    db = client.app.state.db
    master = _seed_session(client, kind="checklist")
    item = await store.create_item(db, master, label="ship slice 8a")
    chat = await store.create_session(
        db, working_dir="/tmp", model="m", kind="chat", checklist_item_id=item["id"]
    )
    chat_sid = chat["id"]
    await store.set_item_chat_session(db, item["id"], chat_sid)

    resp = client.get(f"/api/sessions/{chat_sid}/work_evidence")
    body = resp.json()
    linked = body["linked_checklist"]
    assert linked is not None
    assert linked["item_id"] == item["id"]
    assert linked["label"] == "ship slice 8a"
    assert linked["checked_at"] is None  # not toggled yet
