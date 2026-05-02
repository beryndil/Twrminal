# mypy: disable-error-code=explicit-any
"""Unit tests for ``bearings.agent.approval.ApprovalBroker``.

Per Slice A4 of ``~/.claude/plans/wiring-agent-loop.md``: the broker
mediates between the SDK's ``can_use_tool`` callback (which awaits a
boolean) and the user-side approval modal (which resolves via either
the REST route or an inbound WS ``approval_resolved`` frame).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from claude_agent_sdk.types import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from bearings.agent.approval import ApprovalBroker
from bearings.agent.events import ApprovalRequest, ApprovalResolved
from bearings.agent.runner import SessionRunner


def _runner() -> SessionRunner:
    return SessionRunner("ses_t")


def _ctx() -> ToolPermissionContext:
    return ToolPermissionContext(
        signal=None,
        suggestions=[],
        tool_use_id="tool_use_1",
        agent_id=None,
    )


# ---------------------------------------------------------------------------
# Open / resolve happy paths
# ---------------------------------------------------------------------------


async def test_resolve_allow_unblocks_open() -> None:
    """``open()`` blocks; ``resolve(approved=True)`` unblocks it
    with ``True``."""
    runner = _runner()
    broker = ApprovalBroker(runner)
    request_id = "req_a"

    open_task = asyncio.create_task(
        broker.open(request_id=request_id, tool_name="Read", tool_input={"path": "/x"})
    )
    # Yield so open() reaches its await on the future.
    await asyncio.sleep(0)
    assert broker.pending_count == 1
    assert await broker.resolve(request_id, approved=True) is True
    result = await open_task
    assert result is True
    assert broker.pending_count == 0


async def test_resolve_deny_returns_false() -> None:
    runner = _runner()
    broker = ApprovalBroker(runner)
    open_task = asyncio.create_task(
        broker.open(request_id="r", tool_name="Bash", tool_input={"cmd": "rm -rf /"})
    )
    await asyncio.sleep(0)
    await broker.resolve("r", approved=False)
    assert await open_task is False


async def test_open_emits_approval_request_event() -> None:
    """The ApprovalRequest AgentEvent fires on the runner's ring
    buffer so the conversation pane opens its modal."""
    runner = _runner()
    broker = ApprovalBroker(runner)
    open_task = asyncio.create_task(
        broker.open(request_id="r1", tool_name="Edit", tool_input={"k": "v"})
    )
    await asyncio.sleep(0)
    events = [event for _, event in runner._buffer]
    requests = [e for e in events if isinstance(e, ApprovalRequest)]
    assert len(requests) == 1
    assert requests[0].request_id == "r1"
    assert requests[0].tool_name == "Edit"
    assert json.loads(requests[0].tool_input_json) == {"k": "v"}
    await broker.resolve("r1", approved=True)
    await open_task


async def test_resolve_emits_approval_resolved_event() -> None:
    runner = _runner()
    broker = ApprovalBroker(runner)
    open_task = asyncio.create_task(broker.open(request_id="r2", tool_name="Read", tool_input={}))
    await asyncio.sleep(0)
    await broker.resolve("r2", approved=False)
    await open_task
    resolved = [event for _, event in runner._buffer if isinstance(event, ApprovalResolved)]
    assert len(resolved) == 1
    assert resolved[0].request_id == "r2"
    assert resolved[0].approved is False


# ---------------------------------------------------------------------------
# Defensive paths
# ---------------------------------------------------------------------------


async def test_resolve_unknown_request_id_is_no_op() -> None:
    """Resolving an unknown id returns False; safe against duplicate
    REST + WS resolutions."""
    runner = _runner()
    broker = ApprovalBroker(runner)
    assert await broker.resolve("never_opened", approved=True) is False


async def test_double_open_with_same_id_rejected() -> None:
    runner = _runner()
    broker = ApprovalBroker(runner)
    open_a = asyncio.create_task(broker.open(request_id="dup", tool_name="A", tool_input={}))
    await asyncio.sleep(0)
    with pytest.raises(ValueError, match="already pending"):
        await broker.open(request_id="dup", tool_name="B", tool_input={})
    await broker.resolve("dup", approved=True)
    await open_a


async def test_open_rejects_empty_request_id() -> None:
    runner = _runner()
    broker = ApprovalBroker(runner)
    with pytest.raises(ValueError, match="request_id"):
        await broker.open(request_id="", tool_name="A", tool_input={})


async def test_cancel_all_unblocks_pending_open() -> None:
    """``cancel_all()`` cancels the future so the SDK callback gets
    CancelledError instead of hanging."""
    runner = _runner()
    broker = ApprovalBroker(runner)
    open_task = asyncio.create_task(broker.open(request_id="r3", tool_name="A", tool_input={}))
    await asyncio.sleep(0)
    broker.cancel_all()
    with pytest.raises(asyncio.CancelledError):
        await open_task


async def test_concurrent_open_resolves_independently() -> None:
    """Two in-flight requests with distinct ids resolve independently
    in any order."""
    runner = _runner()
    broker = ApprovalBroker(runner)

    a = asyncio.create_task(broker.open(request_id="a", tool_name="A", tool_input={}))
    b = asyncio.create_task(broker.open(request_id="b", tool_name="B", tool_input={}))
    await asyncio.sleep(0)
    assert broker.pending_count == 2
    # Resolve in reverse order.
    await broker.resolve("b", approved=False)
    await broker.resolve("a", approved=True)
    assert await a is True
    assert await b is False


# ---------------------------------------------------------------------------
# SDK callback shape
# ---------------------------------------------------------------------------


async def test_callback_returns_allow_on_approval() -> None:
    """The SDK-shape callback returns ``PermissionResultAllow`` when
    the user clicks Allow."""
    runner = _runner()
    broker = ApprovalBroker(runner)
    callback = broker.callback()
    task = asyncio.create_task(callback("Read", {"path": "/x"}, _ctx()))
    await asyncio.sleep(0)
    # Pull the request_id off the emitted event so we can resolve.
    events = [e for _, e in runner._buffer if isinstance(e, ApprovalRequest)]
    assert events
    request_id = events[0].request_id
    await broker.resolve(request_id, approved=True)
    result = await task
    assert isinstance(result, PermissionResultAllow)
    assert result.behavior == "allow"


async def test_callback_returns_deny_on_rejection() -> None:
    runner = _runner()
    broker = ApprovalBroker(runner)
    callback = broker.callback()
    task = asyncio.create_task(callback("Bash", {"cmd": "x"}, _ctx()))
    await asyncio.sleep(0)
    events = [e for _, e in runner._buffer if isinstance(e, ApprovalRequest)]
    request_id = events[0].request_id
    await broker.resolve(request_id, approved=False)
    result = await task
    assert isinstance(result, PermissionResultDeny)
    assert result.behavior == "deny"
    assert "denied" in result.message.lower()


async def test_no_timeout_in_v1() -> None:
    """Per sign-off Q4 — no timeout on approval. The future blocks
    indefinitely until resolved or cancelled."""
    runner = _runner()
    broker = ApprovalBroker(runner)
    open_task = asyncio.create_task(
        broker.open(request_id="r_no_timeout", tool_name="A", tool_input={})
    )
    # Wait longer than any plausible UI timeout would be.
    await asyncio.sleep(0.2)
    assert not open_task.done()
    # Resolve to clean up.
    await broker.resolve("r_no_timeout", approved=True)
    await open_task


async def test_fresh_request_id_collisions_are_unlikely() -> None:
    """The internal id generator uses ``secrets.token_hex(16)`` — 32
    hex chars = 128 bits. Two fresh ids never collide in a short
    burst."""
    seen: set[str] = set()
    for _ in range(100):
        rid = ApprovalBroker._fresh_id()
        assert rid not in seen
        seen.add(rid)
        assert len(rid) == 32
