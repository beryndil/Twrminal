"""Tests for ``POST /api/sessions/{id}/approvals/{request_id}``.

Per Slice A4 of ``~/.claude/plans/wiring-agent-loop.md``: the route
resolves the per-session :class:`ApprovalBroker` future with the
user's choice. Coverage:

* Allow / Deny — body ``{approved: true|false}`` resolves the
  pending future and the route returns 204.
* 404 when no broker is registered for the session id (no live
  supervisor / unknown session).
* 409 when the broker rejects the resolution (unknown / already
  resolved request_id).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from bearings.agent.approval import ApprovalBroker
from bearings.agent.runner import SessionRunner
from bearings.db.connection import load_schema
from bearings.web.app import create_app
from bearings.web.runner_factory import InProcessRunnerRegistry


@pytest.fixture
async def conn(tmp_path: Path):
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as connection:
        await load_schema(connection)
        yield connection


def _app_with_broker(
    conn: aiosqlite.Connection,
    session_id: str,
    broker: ApprovalBroker,
):
    factory = InProcessRunnerRegistry()
    factory._approval_brokers[session_id] = broker
    app = create_app(runner_factory=factory, db_connection=conn)
    return app, factory


async def test_resolve_allow_returns_204_and_unblocks_open(
    conn: aiosqlite.Connection,
) -> None:
    runner = SessionRunner("ses_t")
    broker = ApprovalBroker(runner)
    app, _ = _app_with_broker(conn, "ses_t", broker)

    open_task = asyncio.create_task(
        broker.open(request_id="r1", tool_name="Read", tool_input={"x": 1})
    )
    await asyncio.sleep(0)

    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/ses_t/approvals/r1",
            json={"approved": True},
        )
        assert response.status_code == 204
    assert await open_task is True


async def test_resolve_deny_returns_204(conn: aiosqlite.Connection) -> None:
    runner = SessionRunner("ses_t")
    broker = ApprovalBroker(runner)
    app, _ = _app_with_broker(conn, "ses_t", broker)

    open_task = asyncio.create_task(broker.open(request_id="r2", tool_name="Bash", tool_input={}))
    await asyncio.sleep(0)

    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/ses_t/approvals/r2",
            json={"approved": False},
        )
        assert response.status_code == 204
    assert await open_task is False


async def test_resolve_returns_404_when_no_broker(
    conn: aiosqlite.Connection,
) -> None:
    """Session with no live supervisor / no broker registered."""
    factory = InProcessRunnerRegistry()
    app = create_app(runner_factory=factory, db_connection=conn)
    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/ses_unknown/approvals/r3",
            json={"approved": True},
        )
        assert response.status_code == 404
        assert "no approval broker" in response.json()["detail"]


async def test_resolve_returns_409_for_unknown_request_id(
    conn: aiosqlite.Connection,
) -> None:
    """Broker is registered but the request_id was never opened."""
    runner = SessionRunner("ses_t")
    broker = ApprovalBroker(runner)
    app, _ = _app_with_broker(conn, "ses_t", broker)

    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/ses_t/approvals/never_opened",
            json={"approved": True},
        )
        assert response.status_code == 409
        assert "unknown or already resolved" in response.json()["detail"]


async def test_resolve_returns_409_on_duplicate(
    conn: aiosqlite.Connection,
) -> None:
    """A second resolution for the same request_id is rejected per
    the broker's contract — defends against duplicate REST + WS
    resolutions."""
    runner = SessionRunner("ses_t")
    broker = ApprovalBroker(runner)
    app, _ = _app_with_broker(conn, "ses_t", broker)

    open_task = asyncio.create_task(broker.open(request_id="r4", tool_name="A", tool_input={}))
    await asyncio.sleep(0)

    with TestClient(app) as client:
        first = client.post("/api/sessions/ses_t/approvals/r4", json={"approved": True})
        second = client.post("/api/sessions/ses_t/approvals/r4", json={"approved": False})
        assert first.status_code == 204
        assert second.status_code == 409
    await open_task


async def test_resolve_rejects_missing_field(conn: aiosqlite.Connection) -> None:
    """Pydantic validates the request body — missing ``approved``
    surfaces as 422."""
    runner = SessionRunner("ses_t")
    broker = ApprovalBroker(runner)
    app, _ = _app_with_broker(conn, "ses_t", broker)
    with TestClient(app) as client:
        response = client.post("/api/sessions/ses_t/approvals/r5", json={})
        assert response.status_code == 422


async def test_resolve_with_answer_passes_to_broker(conn: aiosqlite.Connection) -> None:
    """When ``answer`` is included the broker threads it to the SDK
    callback as ``updated_input``; the route still returns 204."""
    runner = SessionRunner("ses_t")
    broker = ApprovalBroker(runner)
    app, _ = _app_with_broker(conn, "ses_t", broker)

    open_task = asyncio.create_task(
        broker.open(request_id="r_ans", tool_name="AskUserQuestion", tool_input={"question": "Hi?"})
    )
    await asyncio.sleep(0)

    with TestClient(app) as client:
        response = client.post(
            "/api/sessions/ses_t/approvals/r_ans",
            json={"approved": True, "answer": "Hello there"},
        )
        assert response.status_code == 204
    # The Future result is plain True (approved bool); the answer is
    # consumed by the SDK callback via the broker's _answers side-channel.
    # We verify the broker resolved successfully here:
    assert await open_task is True
