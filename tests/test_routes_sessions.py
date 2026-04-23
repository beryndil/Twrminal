from __future__ import annotations

from fastapi.testclient import TestClient


def _default_tag(client: TestClient) -> int:
    """Every session must carry ≥1 tag (v0.2.13). The tests don't
    particularly care which tag, so we seed a single "default" tag
    per client and hand out its id. Per-test client fixtures start
    with an empty DB, so the POST only creates once per test."""
    existing = client.get("/api/tags").json()
    if existing:
        tag_id: int = existing[0]["id"]
        return tag_id
    created = client.post("/api/tags", json={"name": "default"})
    return int(created.json()["id"])


def _create(client: TestClient, **kwargs: object) -> dict:
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
    return resp.json()


def test_post_rejects_session_without_tags(client: TestClient) -> None:
    resp = client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "tag_ids": []},
    )
    assert resp.status_code == 400


def test_post_rejects_nonexistent_tag_id(client: TestClient) -> None:
    resp = client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "tag_ids": [9999]},
    )
    assert resp.status_code == 400


def test_post_create_returns_session(client: TestClient) -> None:
    data = _create(client, title="hello")
    assert len(data["id"]) == 32
    assert data["working_dir"] == "/tmp"
    assert data["model"] == "claude-sonnet-4-6"
    assert data["title"] == "hello"
    assert data["max_budget_usd"] is None
    assert data["created_at"]
    assert data["updated_at"]


def test_post_create_persists_budget(client: TestClient) -> None:
    data = _create(client, title="bounded", max_budget_usd=1.25)
    assert data["max_budget_usd"] == 1.25
    roundtrip = client.get(f"/api/sessions/{data['id']}").json()
    assert roundtrip["max_budget_usd"] == 1.25


def test_get_list_includes_created(client: TestClient) -> None:
    created = _create(client)
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert created["id"] in ids


def test_get_session_round_trip(client: TestClient) -> None:
    created = _create(client, title="round-trip")
    resp = client.get(f"/api/sessions/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == created


def test_get_missing_returns_404(client: TestClient) -> None:
    resp = client.get("/api/sessions/" + "0" * 32)
    assert resp.status_code == 404


def test_delete_then_get_404(client: TestClient) -> None:
    created = _create(client)
    resp = client.delete(f"/api/sessions/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}
    resp = client.get(f"/api/sessions/{created['id']}")
    assert resp.status_code == 404


def test_delete_missing_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/sessions/" + "0" * 32)
    assert resp.status_code == 404


def test_patch_updates_title(client: TestClient) -> None:
    created = _create(client, title="before")
    before_updated = created["updated_at"]
    resp = client.patch(
        f"/api/sessions/{created['id']}",
        json={"title": "after"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "after"
    # Other fields untouched.
    assert body["working_dir"] == created["working_dir"]
    assert body["model"] == created["model"]
    assert body["max_budget_usd"] == created["max_budget_usd"]
    # updated_at bumped.
    assert body["updated_at"] != before_updated


def test_patch_can_clear_title(client: TestClient) -> None:
    created = _create(client, title="named")
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={"title": None},
    ).json()
    assert body["title"] is None


def test_patch_updates_budget(client: TestClient) -> None:
    created = _create(client, max_budget_usd=1.0)
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={"max_budget_usd": 5.5},
    ).json()
    assert body["max_budget_usd"] == 5.5


def test_post_create_persists_description(client: TestClient) -> None:
    data = _create(client, title="noted", description="investigating the auth bug")
    assert data["description"] == "investigating the auth bug"
    roundtrip = client.get(f"/api/sessions/{data['id']}").json()
    assert roundtrip["description"] == "investigating the auth bug"


def test_patch_updates_description(client: TestClient) -> None:
    created = _create(client, description="first pass")
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={"description": "revised notes"},
    ).json()
    assert body["description"] == "revised notes"
    # Title untouched by description-only patch.
    assert body["title"] == created["title"]


def test_patch_can_clear_description(client: TestClient) -> None:
    created = _create(client, description="temporary")
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={"description": None},
    ).json()
    assert body["description"] is None


def test_patch_empty_body_is_noop(client: TestClient) -> None:
    created = _create(client, title="stays")
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={},
    ).json()
    assert body["title"] == "stays"


def test_patch_missing_session_returns_404(client: TestClient) -> None:
    resp = client.patch(
        "/api/sessions/" + "0" * 32,
        json={"title": "whatever"},
    )
    assert resp.status_code == 404


def test_export_missing_session_returns_404(client: TestClient) -> None:
    resp = client.get("/api/sessions/" + "0" * 32 + "/export")
    assert resp.status_code == 404


def test_export_empty_session(client: TestClient) -> None:
    created = _create(client, title="exported")
    body = client.get(f"/api/sessions/{created['id']}/export").json()
    assert body["session"]["id"] == created["id"]
    assert body["session"]["title"] == "exported"
    assert body["messages"] == []
    assert body["tool_calls"] == []


def test_import_roundtrip_preserves_content(
    client: TestClient, mock_agent_tool_stream: None
) -> None:
    import time

    # Seed a session with a full turn + a tool call.
    src = _create(client, title="source")
    with client.websocket_connect(f"/ws/sessions/{src['id']}") as ws:
        ws.send_json({"type": "prompt", "content": "read hosts"})
        for _ in range(4):
            ws.receive_text()
        for _ in range(50):
            body = client.get(f"/api/sessions/{src['id']}/export").json()
            if body["tool_calls"] and body["tool_calls"][0]["message_id"]:
                break
            time.sleep(0.02)

    export = client.get(f"/api/sessions/{src['id']}/export").json()

    # Round-trip.
    resp = client.post("/api/sessions/import", json=export)
    assert resp.status_code == 200
    imported = resp.json()
    assert imported["id"] != src["id"]
    assert imported["title"] == "source"
    assert imported["total_cost_usd"] == 0.0  # reset on import
    assert imported["message_count"] == 2

    # Messages and tool calls carried over with remapped ids.
    messages = client.get(f"/api/sessions/{imported['id']}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "read hosts"

    tool_calls = client.get(f"/api/sessions/{imported['id']}/tool_calls").json()
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "Read"
    # message_id was remapped to the newly-inserted assistant message.
    assert tool_calls[0]["message_id"] == messages[1]["id"]


def test_import_rejects_missing_session_key(client: TestClient) -> None:
    resp = client.post(
        "/api/sessions/import",
        json={"messages": [], "tool_calls": []},
    )
    assert resp.status_code == 400


def test_export_includes_messages_and_tool_calls(
    client: TestClient, mock_agent_tool_stream: None
) -> None:
    import time

    created = _create(client, title="with-activity")
    with client.websocket_connect(f"/ws/sessions/{created['id']}") as ws:
        ws.send_json({"type": "prompt", "content": "read it"})
        for _ in range(4):
            ws.receive_text()
        # Wait for the WS handler to finish persisting post-send writes
        # before the context cancels the server task.
        for _ in range(50):
            body = client.get(f"/api/sessions/{created['id']}/export").json()
            if body["tool_calls"] and body["tool_calls"][0]["message_id"]:
                break
            time.sleep(0.02)

    body = client.get(f"/api/sessions/{created['id']}/export").json()
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant"]
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["name"] == "Read"


def test_get_messages_empty_for_new_session(client: TestClient) -> None:
    created = _create(client)
    resp = client.get(f"/api/sessions/{created['id']}/messages")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_messages_missing_session_returns_404(client: TestClient) -> None:
    resp = client.get("/api/sessions/" + "0" * 32 + "/messages")
    assert resp.status_code == 404


def test_get_tool_calls_empty_for_new_session(client: TestClient) -> None:
    created = _create(client)
    resp = client.get(f"/api/sessions/{created['id']}/tool_calls")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_tool_calls_missing_session_returns_404(client: TestClient) -> None:
    resp = client.get("/api/sessions/" + "0" * 32 + "/tool_calls")
    assert resp.status_code == 404


def test_get_tool_calls_returns_persisted_rows(
    client: TestClient, mock_agent_tool_stream: None
) -> None:
    created = _create(client, title="tc")
    with client.websocket_connect(f"/ws/sessions/{created['id']}") as ws:
        ws.send_json({"type": "prompt", "content": "read hosts"})
        for _ in range(4):
            ws.receive_text()

    rows = client.get(f"/api/sessions/{created['id']}/tool_calls").json()
    assert len(rows) == 1
    call = rows[0]
    assert call["id"] == "tool-1"
    assert call["name"] == "Read"
    assert call["input"] == '{"path": "/etc/hosts"}'
    assert call["output"] == "127.0.0.1 localhost"
    assert call["error"] is None
    assert call["started_at"]
    assert call["finished_at"]


def test_get_tool_calls_filters_by_message_ids(
    client: TestClient, mock_agent_tool_stream: None
) -> None:
    """The conversation pane scopes the fetch to the on-screen message
    window — confirms `?message_ids=<id>` narrows the response and that
    a bogus id returns an empty list instead of everything."""
    created = _create(client, title="tc-filter")
    with client.websocket_connect(f"/ws/sessions/{created['id']}") as ws:
        ws.send_json({"type": "prompt", "content": "read hosts"})
        for _ in range(4):
            ws.receive_text()

    rows = client.get(f"/api/sessions/{created['id']}/tool_calls").json()
    assert len(rows) == 1
    parent_msg_id = rows[0]["message_id"]
    assert parent_msg_id is not None

    # Matching id returns the row.
    scoped = client.get(
        f"/api/sessions/{created['id']}/tool_calls",
        params={"message_ids": parent_msg_id},
    ).json()
    assert [r["id"] for r in scoped] == ["tool-1"]

    # A non-matching id returns an empty list — the orphan drop.
    bogus = client.get(
        f"/api/sessions/{created['id']}/tool_calls",
        params={"message_ids": "0" * 32},
    ).json()
    assert bogus == []


def test_tokens_endpoint_missing_session_returns_404(client: TestClient) -> None:
    """The /tokens endpoint is gated on session existence — a bogus id
    must 404 rather than leaking a zero-valued row a non-existent
    session would never accumulate."""
    resp = client.get("/api/sessions/" + "0" * 32 + "/tokens")
    assert resp.status_code == 404


def test_tokens_endpoint_empty_session_returns_zeros(client: TestClient) -> None:
    """A freshly-created session has no messages yet. The endpoint
    must return all-zeros (not null, not 500) so the frontend can
    render its placeholder without null-guarding every field."""
    created = _create(client, title="empty")
    body = client.get(f"/api/sessions/{created['id']}/tokens").json()
    assert body == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
    }


def test_tokens_endpoint_sums_assistant_turns(
    client: TestClient, mock_agent_cost_stream: None
) -> None:
    """After a real turn completes through the WS the aggregate
    reflects whatever usage the mocked ResultMessage carried. The
    cost-stream fixture doesn't populate usage, so the totals stay
    at zero — that's the PAYG-no-usage case and it should not 500."""
    created = _create(client, title="summed")
    with client.websocket_connect(f"/ws/sessions/{created['id']}") as ws:
        ws.send_json({"type": "prompt", "content": "go"})
        # Drain a few frames so the turn persists before we poll.
        for _ in range(4):
            ws.receive_text()
    body = client.get(f"/api/sessions/{created['id']}/tokens").json()
    # All four keys are present and non-negative ints.
    assert set(body.keys()) == {
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
    }
    for v in body.values():
        assert isinstance(v, int)
        assert v >= 0


def test_running_endpoint_empty_when_no_runners(client: TestClient) -> None:
    """/api/sessions/running returns [] when no session has a runner
    mid-turn. This is the idle-state the sidebar poll sees on fresh
    boot — it must not claim any session is busy."""
    # Create a session but never open a WS — no runner is spawned.
    _create(client, title="idle")
    resp = client.get("/api/sessions/running")
    assert resp.status_code == 200
    assert resp.json() == []


def test_running_endpoint_reports_session_with_live_turn(
    client: TestClient, mock_agent_long_stream: None
) -> None:
    """While a turn is in flight, the session id appears in the
    running list. This is what powers the sidebar's "still working"
    badge — regression here means Daisy walks away from a prompt and
    the UI gives no signal that it's still streaming."""
    import json

    existing = client.get("/api/tags").json()
    tag_id = (
        existing[0]["id"]
        if existing
        else client.post("/api/tags", json={"name": "default"}).json()["id"]
    )
    sid = client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "tag_ids": [tag_id]},
    ).json()["id"]

    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        # Drain initial runner_status frame.
        assert json.loads(ws.receive_text())["type"] == "runner_status"
        ws.send_json({"type": "prompt", "content": "work"})
        # Wait until at least one streamed event arrives so the runner
        # is visibly mid-turn by the time we poll the endpoint.
        assert json.loads(ws.receive_text())["type"] == "message_start"
        assert json.loads(ws.receive_text())["type"] == "token"

        running = client.get("/api/sessions/running").json()
        assert sid in running

        # Stop cleanly so the test shuts down the turn instead of
        # leaving the long-stream mock hanging.
        ws.send_json({"type": "stop"})


# ---- respawn-on-edit ------------------------------------------------
#
# Edits to fields that feed the assembled system prompt (description,
# session_instructions, tag attach/detach) must drop any live runner
# for the session. The runner holds a claude subprocess spawned with
# `--system-prompt` set once at launch, so in-place DB edits don't
# reach it. Dropping forces the next WS turn to respawn with the new
# assembled prompt.


class _ShutdownTracker:
    """Mock runner that only records shutdown() calls. Planted into
    `registry._runners` so the edit routes can call `drop()` on a real
    registry entry without needing a real `SessionRunner` (and the SDK
    subprocess it would spawn)."""

    def __init__(self) -> None:
        self.shutdown_calls = 0

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


def _plant_runner(client: TestClient, session_id: str) -> _ShutdownTracker:
    tracker = _ShutdownTracker()
    registry = client.app.state.runners  # type: ignore[attr-defined]
    registry._runners[session_id] = tracker  # type: ignore[assignment]
    return tracker


def test_patch_description_drops_live_runner(client: TestClient) -> None:
    created = _create(client, description="first pass")
    tracker = _plant_runner(client, created["id"])

    resp = client.patch(
        f"/api/sessions/{created['id']}",
        json={"description": "revised brief"},
    )
    assert resp.status_code == 200
    assert tracker.shutdown_calls == 1
    registry = client.app.state.runners  # type: ignore[attr-defined]
    assert created["id"] not in registry._runners


def test_patch_session_instructions_drops_live_runner(client: TestClient) -> None:
    created = _create(client, title="under review")
    tracker = _plant_runner(client, created["id"])

    resp = client.patch(
        f"/api/sessions/{created['id']}",
        json={"session_instructions": "respond in bullet points only"},
    )
    assert resp.status_code == 200
    assert tracker.shutdown_calls == 1


def test_patch_title_only_does_not_drop_runner(client: TestClient) -> None:
    """Title doesn't appear in the assembled prompt, so renaming a
    session must not knock its live runner offline mid-conversation."""
    created = _create(client, title="before")
    tracker = _plant_runner(client, created["id"])

    resp = client.patch(
        f"/api/sessions/{created['id']}",
        json={"title": "after"},
    )
    assert resp.status_code == 200
    assert tracker.shutdown_calls == 0
    registry = client.app.state.runners  # type: ignore[attr-defined]
    assert created["id"] in registry._runners


def test_patch_budget_only_does_not_drop_runner(client: TestClient) -> None:
    created = _create(client, title="bounded", max_budget_usd=1.0)
    tracker = _plant_runner(client, created["id"])

    resp = client.patch(
        f"/api/sessions/{created['id']}",
        json={"max_budget_usd": 2.5},
    )
    assert resp.status_code == 200
    assert tracker.shutdown_calls == 0


def test_attach_tag_drops_live_runner(client: TestClient) -> None:
    created = _create(client, title="needs more context")
    extra_tag_id = client.post("/api/tags", json={"name": "extra"}).json()["id"]
    tracker = _plant_runner(client, created["id"])

    resp = client.post(f"/api/sessions/{created['id']}/tags/{extra_tag_id}")
    assert resp.status_code == 200
    assert tracker.shutdown_calls == 1


def test_detach_tag_drops_live_runner(client: TestClient) -> None:
    default_tag_id = _default_tag(client)
    created = _create(client, title="retagging")
    tracker = _plant_runner(client, created["id"])

    resp = client.delete(f"/api/sessions/{created['id']}/tags/{default_tag_id}")
    assert resp.status_code == 200
    assert tracker.shutdown_calls == 1


# v0.3.25 — lifecycle close/reopen routes.


def test_post_close_marks_session_closed(client: TestClient) -> None:
    created = _create(client, title="finished charter")
    assert created["closed_at"] is None

    resp = client.post(f"/api/sessions/{created['id']}/close")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == created["id"]
    assert body["closed_at"] is not None


def test_post_close_is_idempotent(client: TestClient) -> None:
    """Second close re-stamps `closed_at` instead of 409'ing. The UI
    can fire the button naïvely without tracking current state."""
    created = _create(client, title="double-close")
    first = client.post(f"/api/sessions/{created['id']}/close").json()
    second = client.post(f"/api/sessions/{created['id']}/close").json()
    assert first["closed_at"] is not None
    assert second["closed_at"] is not None
    # Timestamps may match (same clock tick) but must never regress.
    assert second["closed_at"] >= first["closed_at"]


def test_post_reopen_clears_closed_at(client: TestClient) -> None:
    created = _create(client, title="back to work")
    client.post(f"/api/sessions/{created['id']}/close")
    resp = client.post(f"/api/sessions/{created['id']}/reopen")
    assert resp.status_code == 200
    assert resp.json()["closed_at"] is None


def test_post_close_missing_session_returns_404(client: TestClient) -> None:
    resp = client.post("/api/sessions/" + "0" * 32 + "/close")
    assert resp.status_code == 404


def test_post_reopen_missing_session_returns_404(client: TestClient) -> None:
    resp = client.post("/api/sessions/" + "0" * 32 + "/reopen")
    assert resp.status_code == 404


def test_close_does_not_drop_live_runner(client: TestClient) -> None:
    """Closed state doesn't enter the system prompt; no runner respawn
    needed. Matches the budget-edit precedent."""
    created = _create(client, title="quiet close")
    tracker = _plant_runner(client, created["id"])

    resp = client.post(f"/api/sessions/{created['id']}/close")
    assert resp.status_code == 200
    assert tracker.shutdown_calls == 0


# v0.7.x — view-tracking route (migration 0020).


def test_post_viewed_stamps_last_viewed_at(client: TestClient) -> None:
    created = _create(client, title="mark me viewed")
    assert created["last_viewed_at"] is None

    resp = client.post(f"/api/sessions/{created['id']}/viewed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == created["id"]
    assert body["last_viewed_at"] is not None


def test_post_viewed_is_idempotent(client: TestClient) -> None:
    """Second call just refreshes the timestamp — the UI can fire it
    on every tab-focus without tracking prior state."""
    created = _create(client, title="double-viewed")
    first = client.post(f"/api/sessions/{created['id']}/viewed").json()
    second = client.post(f"/api/sessions/{created['id']}/viewed").json()
    assert first["last_viewed_at"] is not None
    assert second["last_viewed_at"] >= first["last_viewed_at"]


def test_post_viewed_does_not_change_sort(client: TestClient) -> None:
    """Viewing must not bump `updated_at`: opening an idle session
    shouldn't shove it above sessions with actual new activity."""
    older = _create(client, title="older")
    newer = _create(client, title="newer")
    before = client.get("/api/sessions").json()
    assert [s["id"] for s in before] == [newer["id"], older["id"]]

    client.post(f"/api/sessions/{older['id']}/viewed")
    after = client.get("/api/sessions").json()
    assert [s["id"] for s in after] == [newer["id"], older["id"]]


def test_post_viewed_missing_session_returns_404(client: TestClient) -> None:
    resp = client.post("/api/sessions/" + "0" * 32 + "/viewed")
    assert resp.status_code == 404


# -- GET /api/sessions/{id}/todos ----------------------------------------
# First-paint snapshot used to seed the LiveTodos widget before the next
# live `todo_write_update` event lands over the WebSocket.


def _seed_todowrite(
    client: TestClient, session_id: str, tool_call_id: str, input_json: str
) -> None:
    """Backfill a raw TodoWrite tool_call row via the app's db handle.
    Uses the same path the agent runner writes through in production,
    so the REST layer sees exactly what it would see post-turn.

    Uses `asyncio.Runner` rather than `get_event_loop().run_until_complete`
    — the latter raises a DeprecationWarning on Python 3.12+ because
    there's no pre-existing loop in the sync test context."""
    import asyncio

    from bearings.db.store import insert_tool_call_start

    async def _go() -> None:
        await insert_tool_call_start(
            client.app.state.db,  # type: ignore[attr-defined]
            session_id=session_id,
            tool_call_id=tool_call_id,
            name="TodoWrite",
            input_json=input_json,
        )

    with asyncio.Runner() as runner:
        runner.run(_go())


def test_get_todos_returns_null_when_session_has_never_called_todowrite(
    client: TestClient,
) -> None:
    created = _create(client, title="no-todos")
    resp = client.get(f"/api/sessions/{created['id']}/todos")
    assert resp.status_code == 200
    assert resp.json() == {"todos": None}


def test_get_todos_returns_latest_payload_in_snake_case(client: TestClient) -> None:
    """Pins the wire shape: the REST response ships `active_form`
    (snake_case) even though the raw DB payload is `activeForm`
    (camelCase, as the SDK emits). The frontend `TodoItem` type and
    `LiveTodos.svelte` read `active_form`; a regression to bidirectional
    aliasing would silently break the "Working on X…" header line."""
    created = _create(client, title="snake-wire")
    _seed_todowrite(
        client,
        created["id"],
        "tw-1",
        '{"todos":[{"content":"Do X","activeForm":"Doing X","status":"in_progress"}]}',
    )
    resp = client.get(f"/api/sessions/{created['id']}/todos")
    assert resp.status_code == 200
    body = resp.json()
    assert body["todos"] == [{"content": "Do X", "active_form": "Doing X", "status": "in_progress"}]
    assert "activeForm" not in body["todos"][0]


def test_get_todos_returns_most_recent_call_only(client: TestClient) -> None:
    """Full-replacement semantics: later TodoWrite wins. The helper
    returns *one* list — the latest — not a merge or a history."""
    created = _create(client, title="latest-wins")
    _seed_todowrite(
        client,
        created["id"],
        "tw-early",
        '{"todos":[{"content":"A","activeForm":"Aing","status":"pending"}]}',
    )
    _seed_todowrite(
        client,
        created["id"],
        "tw-late",
        (
            '{"todos":['
            '{"content":"A","activeForm":"Aing","status":"completed"},'
            '{"content":"B","activeForm":"Bing","status":"in_progress"}'
            "]}"
        ),
    )
    resp = client.get(f"/api/sessions/{created['id']}/todos")
    body = resp.json()
    assert [t["status"] for t in body["todos"]] == ["completed", "in_progress"]
    assert body["todos"][1]["active_form"] == "Bing"


def test_get_todos_returns_empty_list_when_agent_cleared(client: TestClient) -> None:
    """`todos: []` is distinct from `todos: null` — the agent
    explicitly wrote an empty list, so the widget should render a
    "no active todos" footer instead of hiding."""
    created = _create(client, title="cleared")
    _seed_todowrite(client, created["id"], "tw-empty", '{"todos":[]}')
    resp = client.get(f"/api/sessions/{created['id']}/todos")
    assert resp.status_code == 200
    assert resp.json() == {"todos": []}


def test_get_todos_on_missing_session_returns_404(client: TestClient) -> None:
    """Consistent with the rest of the /sessions/{id} surface — unknown
    id is a client error, not an empty result. The frontend only hits
    this route from `conversation.load()`, which already handles a
    missing session via the parallel `getSession` 404, so a second
    404 here adds no burden."""
    resp = client.get("/api/sessions/" + "0" * 32 + "/todos")
    assert resp.status_code == 404


# ---- Phase 4a.1 PATCH extensions (pinned + model) -------------------
#
# Migration 0022 + plan §2.1. `pinned` floats the session in sidebar
# sort (pure UX, no runner impact); `model` powers "Change model for
# continuation" and forces the runner subprocess to respawn so the
# next turn uses the new model.


def test_post_create_defaults_pinned_false(client: TestClient) -> None:
    """Post-migration-0022 default: every freshly created session is
    unpinned. SessionOut coerces SQLite's INTEGER 0 to bool False."""
    data = _create(client, title="fresh")
    assert data["pinned"] is False


def test_patch_sets_pinned_true(client: TestClient) -> None:
    created = _create(client, title="pinnable")
    assert created["pinned"] is False
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={"pinned": True},
    ).json()
    assert body["pinned"] is True
    roundtrip = client.get(f"/api/sessions/{created['id']}").json()
    assert roundtrip["pinned"] is True


def test_patch_clears_pinned_back_to_false(client: TestClient) -> None:
    """Unpinning is a PATCH with `pinned: false`, not an explicit
    null (the column is NOT NULL). Round-trips through the same code
    path as pinning."""
    created = _create(client, title="toggle")
    client.patch(f"/api/sessions/{created['id']}", json={"pinned": True})
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={"pinned": False},
    ).json()
    assert body["pinned"] is False


def test_patch_pinned_does_not_drop_runner(client: TestClient) -> None:
    """Pinning is pure sidebar sort — must not knock the live runner
    offline or the user loses their in-flight turn just for clicking
    a pin icon."""
    created = _create(client, title="pin live")
    tracker = _plant_runner(client, created["id"])
    resp = client.patch(
        f"/api/sessions/{created['id']}",
        json={"pinned": True},
    )
    assert resp.status_code == 200
    assert tracker.shutdown_calls == 0


def test_patch_rejects_non_boolean_pinned(client: TestClient) -> None:
    """Pydantic rejects a non-bool at the boundary so a typo in the
    JSON body (`"pinned": "true"` with quotes) surfaces as a 422
    instead of coercing into a truthy 1 silently."""
    created = _create(client, title="strict")
    resp = client.patch(
        f"/api/sessions/{created['id']}",
        # Dict is unambiguously not a bool; FastAPI / Pydantic rejects.
        json={"pinned": {"nope": True}},
    )
    assert resp.status_code == 422


def test_patch_updates_model(client: TestClient) -> None:
    """Phase 4a.1 / plan §2.1 — "Change model for continuation"
    mutates the model column in place, no fork."""
    created = _create(client, title="swap")
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={"model": "claude-opus-4-8"},
    ).json()
    assert body["model"] == "claude-opus-4-8"


def test_patch_model_drops_live_runner(client: TestClient) -> None:
    """The SDK subprocess was spawned with the old model baked in; a
    model change only reaches the agent after the runner is dropped
    and re-created on the next WS turn."""
    created = _create(client, title="respawn")
    tracker = _plant_runner(client, created["id"])
    resp = client.patch(
        f"/api/sessions/{created['id']}",
        json={"model": "claude-sonnet-4-7"},
    )
    assert resp.status_code == 200
    assert tracker.shutdown_calls == 1
    registry = client.app.state.runners  # type: ignore[attr-defined]
    assert created["id"] not in registry._runners


def test_pinned_round_trips_through_list(client: TestClient) -> None:
    """GET /sessions surfaces the pinned flag so the sidebar can sort
    without re-fetching each row individually."""
    created = _create(client, title="listed")
    client.patch(f"/api/sessions/{created['id']}", json={"pinned": True})
    rows = client.get("/api/sessions").json()
    match = next(r for r in rows if r["id"] == created["id"])
    assert match["pinned"] is True
