"""Unit tests for tool-use approval flow.

Pins the `can_use_tool` → `ApprovalRequest` → `resolve_approval`
round-trip the WS layer depends on. Direct runner tests (no WS /
SDK) — the protocol contract is what matters here, not the transport.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from bearings.agent.runner import SessionRunner
from bearings.db import store
from bearings.db._common import init_db
from tests.test_runner import ScriptedAgent


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    conn = await init_db(tmp_path / "approval.sqlite")
    await store.create_session(conn, working_dir="/tmp", model="m", title="t")
    yield conn
    await conn.close()


async def _session_id(conn: aiosqlite.Connection) -> str:
    rows = await store.list_sessions(conn)
    return rows[0]["id"]


def _ctx(tool_use_id: str = "tu_1") -> ToolPermissionContext:
    return ToolPermissionContext(tool_use_id=tool_use_id)


@pytest.mark.asyncio
async def test_can_use_tool_emits_request_and_waits(
    db: aiosqlite.Connection,
) -> None:
    """`can_use_tool` fans an `ApprovalRequest` event to subscribers
    and parks on a Future until `resolve_approval` fires. Subscribers
    see the request before any decision is made."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    queue, _ = await runner.subscribe(0)

    task = asyncio.create_task(runner.can_use_tool("ExitPlanMode", {"plan": "# plan"}, _ctx()))
    env = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert env.payload["type"] == "approval_request"
    assert env.payload["tool_name"] == "ExitPlanMode"
    assert env.payload["input"] == {"plan": "# plan"}
    request_id = env.payload["request_id"]

    await runner.resolve_approval(request_id, "allow")
    result = await asyncio.wait_for(task, timeout=1.0)
    assert isinstance(result, PermissionResultAllow)

    # A matching `approval_resolved` must fan out so other tabs can
    # drop their own modal copies.
    resolved = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert resolved.payload["type"] == "approval_resolved"
    assert resolved.payload["decision"] == "allow"
    assert resolved.payload["request_id"] == request_id


@pytest.mark.asyncio
async def test_resolve_approval_deny_returns_deny_with_reason(
    db: aiosqlite.Connection,
) -> None:
    """Deny response surfaces through as `PermissionResultDeny`. Reason
    from the frontend rides along so the agent sees a useful message;
    `interrupt=False` because a user-initiated deny isn't an emergency
    and shouldn't abort the broader stream the way a stop does."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    await runner.subscribe(0)

    task = asyncio.create_task(runner.can_use_tool("Edit", {"path": "/etc/passwd"}, _ctx("tu_2")))
    await asyncio.sleep(0)  # let the coroutine register the future
    request_id = next(iter(runner._approval._pending))
    await runner.resolve_approval(request_id, "deny", reason="not today")

    result = await asyncio.wait_for(task, timeout=1.0)
    assert isinstance(result, PermissionResultDeny)
    assert result.message == "not today"
    assert result.interrupt is False


@pytest.mark.asyncio
async def test_resolve_unknown_id_is_noop(db: aiosqlite.Connection) -> None:
    """A late / duplicate response from a second tab for an already-
    resolved id must not crash. Two tabs answering the same modal is
    a real UX and the second one's click just loses the race."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    # Doesn't raise:
    await runner.resolve_approval("does-not-exist", "allow")


@pytest.mark.asyncio
async def test_request_stop_denies_pending_with_interrupt(
    db: aiosqlite.Connection,
) -> None:
    """User clicks Stop while the agent is parked on an approval. The
    pending Future must be denied with `interrupt=True` so the SDK
    aborts its in-flight turn rather than hanging forever. A matching
    `approval_resolved(decision=deny)` event clears the modal on any
    other tab mirroring this session."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    queue, _ = await runner.subscribe(0)

    task = asyncio.create_task(runner.can_use_tool("Bash", {"command": "rm -rf /"}, _ctx()))
    req = await asyncio.wait_for(queue.get(), timeout=1.0)
    request_id = req.payload["request_id"]

    await runner.request_stop()

    result = await asyncio.wait_for(task, timeout=1.0)
    assert isinstance(result, PermissionResultDeny)
    assert result.interrupt is True

    resolved = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert resolved.payload["type"] == "approval_resolved"
    assert resolved.payload["request_id"] == request_id
    assert resolved.payload["decision"] == "deny"


@pytest.mark.asyncio
async def test_shutdown_denies_all_pending(
    db: aiosqlite.Connection,
) -> None:
    """App shutdown with multiple parked approvals (one session with
    several tool calls in flight) must unblock every Future so the
    worker can wind down. Without this the shutdown hangs waiting on
    a user that is never coming back."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    runner.start()
    await runner.subscribe(0)

    t1 = asyncio.create_task(runner.can_use_tool("A", {}, _ctx("a")))
    t2 = asyncio.create_task(runner.can_use_tool("B", {}, _ctx("b")))
    await asyncio.sleep(0.01)
    assert len(runner._approval._pending) == 2

    await runner.shutdown()

    r1 = await asyncio.wait_for(t1, timeout=1.0)
    r2 = await asyncio.wait_for(t2, timeout=1.0)
    assert isinstance(r1, PermissionResultDeny)
    assert isinstance(r2, PermissionResultDeny)
    assert r1.interrupt is True and r2.interrupt is True
