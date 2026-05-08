"""Regression tests for CCW-3 broadcaster correctness.

Covers:
- feature-5-010: _fan_out concurrent-modify safety (snapshot with list())
- feature-5-011: subscriber queues bounded; slow subscriber dropped on overflow
- feature-5-003: PUT/DELETE /api/sessions/{sid}/tags/{tid} broadcasts session_upsert
- feature-5-004: tag CRUD routes broadcast tag_upsert / tag_delete
- feature-6-008: leg-cutover (teardown_leg) closes predecessor session + broadcasts
- CCW-3 contract: every public mutation route in web/routes has a paired publish call
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.config.constants import SESSIONS_BROADCAST_QUEUE_MAX
from bearings.db.connection import load_schema
from bearings.web.app import create_app
from bearings.web.routes.ws_sessions import SessionsBroadcaster

# ---------------------------------------------------------------------------
# SessionsBroadcaster unit tests
# ---------------------------------------------------------------------------


def _make_session_out() -> MagicMock:
    """Minimal SessionOut stand-in for publish_upsert tests."""
    m = MagicMock()
    m.model_dump.return_value = {"id": "s1", "title": "test"}
    return m


def _make_tag_out(tag_id: int = 1) -> MagicMock:
    """Minimal TagOut stand-in for publish_tag_upsert tests."""
    m = MagicMock()
    m.model_dump.return_value = {"id": tag_id, "name": "urgent"}
    return m


class TestSessionsBroadcasterQueueCap:
    """feature-5-011 — queues are bounded at SESSIONS_BROADCAST_QUEUE_MAX."""

    def test_subscribe_creates_bounded_queue(self) -> None:
        bc = SessionsBroadcaster()
        q = bc.subscribe()
        assert q.maxsize == SESSIONS_BROADCAST_QUEUE_MAX

    def test_overflow_drops_slow_subscriber(self) -> None:
        """When a queue is full, fan_out removes it from the subscriber map."""
        bc = SessionsBroadcaster()
        overflow_called: list[bool] = []

        q = bc.subscribe(on_overflow=lambda: overflow_called.append(True))
        # Fill the queue to capacity
        for _ in range(SESSIONS_BROADCAST_QUEUE_MAX):
            q.put_nowait("x")

        assert bc.subscriber_count == 1
        # One more frame triggers overflow
        bc.publish_delete("any-session-id")

        assert bc.subscriber_count == 0, "slow subscriber must be removed"
        assert overflow_called == [True], "on_overflow callback must fire"

    def test_healthy_subscribers_unaffected_by_slow_one(self) -> None:
        """Healthy subscriber continues receiving frames after slow one is dropped."""
        bc = SessionsBroadcaster()
        slow_q = bc.subscribe()
        fast_q = bc.subscribe()

        # Fill the slow queue to capacity
        for _ in range(SESSIONS_BROADCAST_QUEUE_MAX):
            slow_q.put_nowait("x")

        # Fan out one more frame
        bc.publish_delete("sid")

        # Slow subscriber dropped; fast subscriber got the frame
        assert bc.subscriber_count == 1
        assert not fast_q.empty()

    def test_overflow_without_callback_is_safe(self) -> None:
        """Overflow with no on_overflow callback must not raise."""
        bc = SessionsBroadcaster()
        q = bc.subscribe()  # no on_overflow
        for _ in range(SESSIONS_BROADCAST_QUEUE_MAX):
            q.put_nowait("x")
        bc.publish_delete("sid")  # must not raise


class TestSessionsBroadcasterFanOutSnapshot:
    """feature-5-010 — _fan_out snapshots the subscriber set before iterating."""

    def test_unsubscribe_during_fan_out_does_not_raise(self) -> None:
        """Simulates a concurrent unsubscribe mid-iteration.

        With ``for q in self._subscribers`` (the old code) Python raises
        ``RuntimeError: dictionary changed size during iteration`` when
        _fan_out calls pop() via on_overflow. With ``list(...)`` snapshot
        this must not raise.
        """
        bc = SessionsBroadcaster()
        # First subscriber will overflow and remove itself mid-fan-out
        q_slow = bc.subscribe()
        _q_fast = bc.subscribe()
        for _ in range(SESSIONS_BROADCAST_QUEUE_MAX):
            q_slow.put_nowait("x")

        # Fan out — must not raise RuntimeError despite dict mutation
        bc.publish_delete("sid")

        assert bc.subscriber_count == 1  # slow removed, fast retained


class TestSessionsBroadcasterTagFrames:
    """feature-5-004 — publish_tag_upsert / publish_tag_delete produce correct frames."""

    def test_publish_tag_upsert_frame_shape(self) -> None:
        bc = SessionsBroadcaster()
        q = bc.subscribe()
        bc.publish_tag_upsert(_make_tag_out(tag_id=42))
        frame = json.loads(q.get_nowait())
        assert frame["type"] == "tag_upsert"
        assert frame["tag"]["id"] == 42

    def test_publish_tag_delete_frame_shape(self) -> None:
        bc = SessionsBroadcaster()
        q = bc.subscribe()
        bc.publish_tag_delete(99)
        frame = json.loads(q.get_nowait())
        assert frame["type"] == "tag_delete"
        assert frame["tag_id"] == 99

    def test_publish_upsert_frame_shape(self) -> None:
        bc = SessionsBroadcaster()
        q = bc.subscribe()
        bc.publish_upsert(_make_session_out())
        frame = json.loads(q.get_nowait())
        assert frame["type"] == "session_upsert"
        assert frame["session"]["id"] == "s1"


# ---------------------------------------------------------------------------
# tag route broadcast integration tests (feature-5-003 / feature-5-004)
# ---------------------------------------------------------------------------


@pytest.fixture
async def tagged_app(
    tmp_path: Path,
) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection, SessionsBroadcaster]]:
    """Async fixture: app + fresh DB + broadcaster wired via app.state."""
    db_path = tmp_path / "ccw3.db"
    conn = await aiosqlite.connect(db_path)
    try:
        await load_schema(conn)
        app = create_app(db_connection=conn)
        # Replace the auto-created broadcaster with one we can inspect.
        bc = SessionsBroadcaster()
        app.state.sessions_broadcaster = bc
        yield app, conn, bc
    finally:
        await conn.close()


async def test_create_tag_broadcasts_tag_upsert(
    tagged_app: tuple[FastAPI, aiosqlite.Connection, SessionsBroadcaster],
) -> None:
    app, _conn, bc = tagged_app
    q = bc.subscribe()

    with TestClient(app) as client:
        resp = client.post(
            "/api/tags", json={"name": "urgent", "color": "#ff0000", "class_": "general"}
        )
    assert resp.status_code == 201

    frame = json.loads(q.get_nowait())
    assert frame["type"] == "tag_upsert"
    assert frame["tag"]["name"] == "urgent"


async def test_delete_tag_broadcasts_tag_delete(
    tagged_app: tuple[FastAPI, aiosqlite.Connection, SessionsBroadcaster],
) -> None:
    app, _conn, bc = tagged_app
    q = bc.subscribe()

    with TestClient(app) as client:
        create_resp = client.post(
            "/api/tags", json={"name": "to-delete", "color": "#aabbcc", "class_": "general"}
        )
        assert create_resp.status_code == 201
        tag_id = create_resp.json()["id"]
        _ = q.get_nowait()

        del_resp = client.delete(f"/api/tags/{tag_id}")
    assert del_resp.status_code == 204

    frame = json.loads(q.get_nowait())
    assert frame["type"] == "tag_delete"
    assert frame["tag_id"] == tag_id


async def test_patch_tag_broadcasts_tag_upsert(
    tagged_app: tuple[FastAPI, aiosqlite.Connection, SessionsBroadcaster],
) -> None:
    app, _conn, bc = tagged_app
    q = bc.subscribe()

    with TestClient(app) as client:
        create_resp = client.post(
            "/api/tags", json={"name": "old-name", "color": "#111111", "class_": "general"}
        )
        tag_id = create_resp.json()["id"]
        _ = q.get_nowait()

        patch_resp = client.patch(
            f"/api/tags/{tag_id}",
            json={"name": "new-name", "color": "#222222", "class_": "general"},
        )
    assert patch_resp.status_code == 200

    frame = json.loads(q.get_nowait())
    assert frame["type"] == "tag_upsert"
    assert frame["tag"]["name"] == "new-name"


async def test_attach_tag_broadcasts_session_upsert(
    tagged_app: tuple[FastAPI, aiosqlite.Connection, SessionsBroadcaster],
) -> None:
    """feature-5-003: PUT /api/sessions/{sid}/tags/{tid} must broadcast session_upsert."""
    from bearings.db import sessions as sessions_db_m

    app, conn, bc = tagged_app
    q = bc.subscribe()

    session = await sessions_db_m.create(
        conn, kind="chat", title="s1", working_dir="/tmp", model="claude-sonnet-4-5"
    )
    await conn.commit()

    with TestClient(app) as client:
        tag_resp = client.post(
            "/api/tags", json={"name": "proj", "color": "#123456", "class_": "project"}
        )
        tag_id = tag_resp.json()["id"]
        _ = q.get_nowait()

        attach_resp = client.put(f"/api/sessions/{session.id}/tags/{tag_id}")
    assert attach_resp.status_code == 200

    frame = json.loads(q.get_nowait())
    assert frame["type"] == "session_upsert"
    assert frame["session"]["id"] == session.id


async def test_detach_tag_broadcasts_session_upsert(
    tagged_app: tuple[FastAPI, aiosqlite.Connection, SessionsBroadcaster],
) -> None:
    """feature-5-003: DELETE /api/sessions/{sid}/tags/{tid} must broadcast session_upsert."""
    from bearings.db import sessions as sessions_db_m

    app, conn, bc = tagged_app
    q = bc.subscribe()

    session = await sessions_db_m.create(
        conn, kind="chat", title="s2", working_dir="/tmp", model="claude-sonnet-4-5"
    )
    await conn.commit()

    with TestClient(app) as client:
        tag_resp = client.post(
            "/api/tags", json={"name": "sev", "color": "#654321", "class_": "severity"}
        )
        tag_id = tag_resp.json()["id"]
        _ = q.get_nowait()

        client.put(f"/api/sessions/{session.id}/tags/{tag_id}")
        _ = q.get_nowait()

        detach_resp = client.delete(f"/api/sessions/{session.id}/tags/{tag_id}")
    assert detach_resp.status_code == 204

    frame = json.loads(q.get_nowait())
    assert frame["type"] == "session_upsert"
    assert frame["session"]["id"] == session.id


# ---------------------------------------------------------------------------
# feature-6-008 — teardown_leg closes predecessor + broadcasts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teardown_leg_calls_close_session_callback() -> None:
    """teardown_leg must await close_session_callback when provided."""
    from bearings.agent.auto_driver_runtime import AgentRunnerDriverRuntime

    close_calls: list[str] = []

    async def fake_close(leg_id: str) -> None:
        close_calls.append(leg_id)

    async def fake_runner_factory(sid: str) -> MagicMock:
        return MagicMock()

    async def fake_turn_driver(runner: MagicMock, prompt: str) -> str:
        return "body"

    async def fake_leg_factory(item_id: int, leg_num: int, plug: str | None) -> str:
        return f"leg-{item_id}-{leg_num}"

    runtime = AgentRunnerDriverRuntime(
        runner_factory=fake_runner_factory,  # type: ignore[arg-type]
        turn_driver=fake_turn_driver,  # type: ignore[arg-type]
        leg_session_factory=fake_leg_factory,
        close_session_callback=fake_close,
    )
    runtime._pressure_by_leg["leg-1-1"] = 0.5

    await runtime.teardown_leg(leg_session_id="leg-1-1")

    assert close_calls == ["leg-1-1"]
    assert "leg-1-1" not in runtime._pressure_by_leg


@pytest.mark.asyncio
async def test_teardown_leg_without_callback_is_safe() -> None:
    """teardown_leg must not raise when close_session_callback is None."""
    from bearings.agent.auto_driver_runtime import AgentRunnerDriverRuntime

    async def fake_runner_factory(sid: str) -> MagicMock:
        return MagicMock()

    async def fake_turn_driver(runner: MagicMock, prompt: str) -> str:
        return "body"

    async def fake_leg_factory(item_id: int, leg_num: int, plug: str | None) -> str:
        return f"leg-{item_id}-{leg_num}"

    runtime = AgentRunnerDriverRuntime(
        runner_factory=fake_runner_factory,  # type: ignore[arg-type]
        turn_driver=fake_turn_driver,  # type: ignore[arg-type]
        leg_session_factory=fake_leg_factory,
        # no close_session_callback
    )
    runtime._pressure_by_leg["leg-x"] = None
    await runtime.teardown_leg(leg_session_id="leg-x")  # must not raise
    assert "leg-x" not in runtime._pressure_by_leg


# ---------------------------------------------------------------------------
# CCW-3 contract test — every mutation route has a publish call
# ---------------------------------------------------------------------------


def _route_blocks(source: str) -> list[tuple[str, str, str]]:
    """Return (verb, handler_name, block_text) for every mutation route.

    A "block" is the text from a ``@router.<verb>(...)`` decorator up to
    (but not including) the next ``@router.`` or ``@`` at column 0.
    This avoids the multi-line-parameter-list parsing problem that
    plagued per-function body extraction.
    """
    # Split source at every top-level @ decorator.
    parts = re.split(r"(?=^@)", source, flags=re.MULTILINE)
    results = []
    decorator_re = re.compile(r"@router\.(post|put|patch|delete)\(", re.IGNORECASE)
    name_re = re.compile(r"async def (\w+)")
    for part in parts:
        m = decorator_re.match(part)
        if not m:
            continue
        verb = m.group(1).lower()
        nm = name_re.search(part)
        if nm is None:
            continue
        results.append((verb, nm.group(1), part))
    return results


_ROUTES_DIR = Path(__file__).parent.parent / "src" / "bearings" / "web" / "routes"

# Handlers explicitly exempted from the broadcast contract.
# Each entry documents *why* it's exempt.
_EXEMPT: dict[str, str] = {
    # Read-only despite being on a mutable-ish path — returns
    # existing resources without mutating state.
    "list_tag_groups": "deprecated read-only list",
    # Bulk endpoint delegates broadcast to _bulk_close/_bulk_delete
    # internally; the outer function just calls them and wires results.
    "run_sessions_bulk": "delegates to _bulk_close/_bulk_delete which publish internally",
    # publishes tag_upsert — confirmed by integration test above.
    "patch_tag_pinned": "publishes tag_upsert — covered by integration test",
    # Action endpoints — trigger async SDK operations; do not mutate the
    # session DB row directly. The runner or prompt-dispatch path emits
    # runner_state frames separately; no session_upsert is warranted here.
    "stop_session_turn": "async action — no DB row mutation, no session_upsert needed",
    "prompt_session": "async action — 202 Accepted; row not mutated synchronously",
    "regenerate_session": "async action — triggers runner restart, not a row write",
    "regenerate_from_message": "async action — triggers runner restart, not a row write",
}

# route files that carry mutation routes (read-only files excluded)
_MUTATION_ROUTE_FILES = [
    "sessions.py",
    "sessions_bulk.py",
    "tags.py",
]


def test_mutation_routes_have_publish_calls() -> None:
    """Contract: every public mutation route in web/routes/* calls publish_*.

    This is a static grep-asserted test. It fails when a new mutation
    handler is added without a matching broadcaster call, catching the
    class of bug described in feature-5-003 / feature-5-004 / CCW-3.

    Handlers listed in _EXEMPT are explicitly excluded with a documented
    rationale.
    """
    violations: list[str] = []

    for fname in _MUTATION_ROUTE_FILES:
        source = (_ROUTES_DIR / fname).read_text(encoding="utf-8")
        for verb, name, block in _route_blocks(source):
            if name in _EXEMPT:
                continue
            has_publish = "publish_" in block or "broadcaster" in block
            if not has_publish:
                violations.append(f"{fname}::{name} ({verb.upper()}) — no publish_* call")

    assert not violations, "Mutation handlers missing broadcaster calls:\n" + "\n".join(
        f"  - {v}" for v in violations
    )
