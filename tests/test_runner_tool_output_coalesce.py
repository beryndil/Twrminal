"""Coalescing tests for `ToolOutputDelta` → DB writes.

The runner buffers `ToolOutputDelta` chunks per `tool_call_id` and
flushes on either a chunk-count or a time threshold, collapsing what
used to be one UPDATE + commit per delta into one UPDATE + commit per
flush window. These tests pin the contract: same persisted output,
fewer writes, canonical final-string semantics preserved.

We count `store.append_tool_output` calls via monkeypatch rather than
racing wall-clock delays, so the tests stay fast and deterministic.
The `FLUSH_INTERVAL` is short (~75ms) so the time-based paths use real
`asyncio.sleep` and still complete inside a normal test timeout.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.events import (
    AgentEvent,
    MessageComplete,
    MessageStart,
    ToolCallEnd,
    ToolCallStart,
    ToolOutputDelta,
)
from bearings.agent.runner import SessionRunner
from bearings.agent.session import AgentSession
from bearings.agent.tool_output_coalescer import (
    FLUSH_CHUNK_COUNT,
    FLUSH_INTERVAL_S,
)
from bearings.db import store
from bearings.db._common import init_db


class ScriptedAgent(AgentSession):
    """Minimal stub that yields a pre-programmed event list once.

    Duplicated (small) from `test_runner.py` to keep this file free of
    that module's `gate` machinery — none of these tests need mid-turn
    pausing, so a simpler stub keeps intent obvious."""

    def __init__(self, session_id: str, script: list[AgentEvent]) -> None:
        super().__init__(session_id, working_dir="/tmp", model="m")
        self._script = script

    async def stream(self, prompt: str) -> AsyncIterator[AgentEvent]:
        for event in self._script:
            yield event

    async def interrupt(self) -> None:  # pragma: no cover - unused here
        pass


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    conn = await init_db(tmp_path / "coalesce.sqlite")
    await store.create_session(conn, working_dir="/tmp", model="m", title="t")
    yield conn
    await conn.close()


async def _session_id(conn: aiosqlite.Connection) -> str:
    rows = await store.list_sessions(conn)
    return rows[0]["id"]


def _make_runner(sid: str, db: aiosqlite.Connection, script: list[AgentEvent]) -> SessionRunner:
    return SessionRunner(sid, ScriptedAgent(sid, script), db)


async def _drain_turn(runner: SessionRunner) -> None:
    """Submit an empty prompt-equivalent turn and wait for it to finish.

    Tests feed events directly into the runner's helpers rather than
    going through `submit_prompt`/the worker for the unit cases. The
    integration-flavored tests that DO run a full turn start the worker
    and wait on `is_running` to clear."""
    runner.start()
    await runner.submit_prompt("go")
    # Wait for turn completion: worker transitions back to idle when
    # the scripted events exhaust.
    for _ in range(400):
        await asyncio.sleep(0.01)
        if not runner.is_running:
            return
    raise AssertionError("turn did not complete within timeout")


# ---- coalescer.buffer: count-triggered flush ------------------------


@pytest.mark.asyncio
async def test_count_threshold_flushes_immediately(
    db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hitting `FLUSH_CHUNK_COUNT` chunks triggers a flush without
    waiting for the timer. Keeps burst tools (grep/find/etc.) from
    sitting on a backlog just because the 75ms window hasn't elapsed
    yet."""
    sid = await _session_id(db)
    runner = _make_runner(sid, db, script=[])

    calls: list[tuple[str, str]] = []
    original = store.append_tool_output

    async def spy(conn: aiosqlite.Connection, *, tool_call_id: str, chunk: str) -> bool:
        calls.append((tool_call_id, chunk))
        return await original(conn, tool_call_id=tool_call_id, chunk=chunk)

    monkeypatch.setattr(store, "append_tool_output", spy)

    await store.insert_tool_call_start(
        db, session_id=sid, tool_call_id="t-burst", name="bash", input_json="{}"
    )

    for i in range(FLUSH_CHUNK_COUNT):
        await runner._coalescer.buffer("t-burst", f"c{i}|")

    # Exactly one flush, containing every chunk joined.
    assert len(calls) == 1
    assert calls[0][0] == "t-burst"
    assert calls[0][1] == "".join(f"c{i}|" for i in range(FLUSH_CHUNK_COUNT))

    # Buffer is drained; no pending timer.
    assert "t-burst" not in runner._coalescer._buffers


# ---- coalescer.buffer: timer-triggered flush ------------------------


@pytest.mark.asyncio
async def test_time_threshold_flushes_small_burst(
    db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A few chunks below the count threshold flush within one
    `FLUSH_INTERVAL_S` window. This is the "tool that drips output
    slowly" case — the user must still see progress land in the DB,
    just at a coarser cadence than before."""
    sid = await _session_id(db)
    runner = _make_runner(sid, db, script=[])

    calls: list[tuple[str, str]] = []
    original = store.append_tool_output

    async def spy(conn: aiosqlite.Connection, *, tool_call_id: str, chunk: str) -> bool:
        calls.append((tool_call_id, chunk))
        return await original(conn, tool_call_id=tool_call_id, chunk=chunk)

    monkeypatch.setattr(store, "append_tool_output", spy)

    await store.insert_tool_call_start(
        db, session_id=sid, tool_call_id="t-drip", name="bash", input_json="{}"
    )

    await runner._coalescer.buffer("t-drip", "a")
    await runner._coalescer.buffer("t-drip", "b")
    await runner._coalescer.buffer("t-drip", "c")
    # Not flushed yet — still inside the window.
    assert calls == []
    assert "t-drip" in runner._coalescer._buffers

    # Wait past the window + a generous margin for CI jitter.
    await asyncio.sleep(FLUSH_INTERVAL_S * 3)

    assert len(calls) == 1
    assert calls[0] == ("t-drip", "abc")
    assert "t-drip" not in runner._coalescer._buffers


# ---- coalescer.drop: ToolCallEnd discards buffered deltas -----------


@pytest.mark.asyncio
async def test_drop_buffer_cancels_pending_timer(
    db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When `ToolCallEnd` lands with buffered chunks still pending,
    the runner drops them without writing. `finish_tool_call` would
    overwrite `output` anyway, so the extra UPDATE would just be
    write amplification."""
    sid = await _session_id(db)
    runner = _make_runner(sid, db, script=[])

    calls: list[str] = []
    original = store.append_tool_output

    async def spy(conn: aiosqlite.Connection, *, tool_call_id: str, chunk: str) -> bool:
        calls.append(chunk)
        return await original(conn, tool_call_id=tool_call_id, chunk=chunk)

    monkeypatch.setattr(store, "append_tool_output", spy)

    await store.insert_tool_call_start(
        db, session_id=sid, tool_call_id="t-end", name="bash", input_json="{}"
    )

    await runner._coalescer.buffer("t-end", "buffered")
    assert "t-end" in runner._coalescer._buffers

    runner._coalescer.drop("t-end")
    assert "t-end" not in runner._coalescer._buffers

    # Wait well past the flush window — no write should happen.
    await asyncio.sleep(FLUSH_INTERVAL_S * 3)
    assert calls == []


# ---- coalescer.flush_all: turn teardown flushes everything ----------


@pytest.mark.asyncio
async def test_flush_all_drains_every_pending_buffer(
    db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiple concurrent tool calls each keep their own buffer;
    `flush_all` drains every one. Exercised on turn teardown paths
    so mid-stream chunks aren't stranded if no `ToolCallEnd` arrives
    (e.g. user-initiated stop)."""
    sid = await _session_id(db)
    runner = _make_runner(sid, db, script=[])

    calls: list[tuple[str, str]] = []
    original = store.append_tool_output

    async def spy(conn: aiosqlite.Connection, *, tool_call_id: str, chunk: str) -> bool:
        calls.append((tool_call_id, chunk))
        return await original(conn, tool_call_id=tool_call_id, chunk=chunk)

    monkeypatch.setattr(store, "append_tool_output", spy)

    for tid in ("t-1", "t-2"):
        await store.insert_tool_call_start(
            db, session_id=sid, tool_call_id=tid, name="bash", input_json="{}"
        )
        await runner._coalescer.buffer(tid, f"{tid}:part1|")
        await runner._coalescer.buffer(tid, f"{tid}:part2|")

    assert calls == []  # nothing flushed yet

    await runner._coalescer.flush_all()

    by_tid = {tid: chunk for tid, chunk in calls}
    assert by_tid == {
        "t-1": "t-1:part1|t-1:part2|",
        "t-2": "t-2:part1|t-2:part2|",
    }
    assert runner._coalescer._buffers == {}


# ---- integration: full turn with streaming tool call ---------------


@pytest.mark.asyncio
async def test_full_turn_coalesces_and_writes_canonical_final(
    db: aiosqlite.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: a scripted turn with N small deltas produces far
    fewer `append_tool_output` calls than deltas, and `ToolCallEnd`
    still leaves the canonical `output` on disk. The key user-visible
    invariant — history endpoint shows the final tool output — is
    preserved while the write volume drops."""
    sid = await _session_id(db)

    calls: list[tuple[str, str]] = []
    original = store.append_tool_output

    async def spy(conn: aiosqlite.Connection, *, tool_call_id: str, chunk: str) -> bool:
        calls.append((tool_call_id, chunk))
        return await original(conn, tool_call_id=tool_call_id, chunk=chunk)

    monkeypatch.setattr(store, "append_tool_output", spy)

    # Build a turn with 10 small deltas (well below the count
    # threshold) so coalescing leans on the timer path.
    events: list[AgentEvent] = [
        MessageStart(session_id=sid, message_id="m-1"),
        ToolCallStart(session_id=sid, tool_call_id="t-int", name="bash", input={}),
    ]
    for i in range(10):
        events.append(ToolOutputDelta(session_id=sid, tool_call_id="t-int", delta=f"L{i}\n"))
    events.append(
        ToolCallEnd(
            session_id=sid,
            tool_call_id="t-int",
            ok=True,
            output="CANONICAL\n",
            error=None,
        )
    )
    events.append(MessageComplete(session_id=sid, message_id="m-1", cost_usd=None))

    runner = _make_runner(sid, db, script=events)
    try:
        await _drain_turn(runner)
    finally:
        await runner.shutdown()

    # All 10 deltas arrived before `ToolCallEnd`, which drops the
    # buffer — net `append_tool_output` calls should be zero. In the
    # worst case the timer beats the end event and we see one flush;
    # assert ≤1 to stay robust without losing the signal.
    assert len(calls) <= 1, f"expected ≤1 coalesced write, got {len(calls)}"

    rows = await store.list_tool_calls(db, sid)
    assert len(rows) == 1
    # `finish_tool_call` wins regardless of whether a pre-flush landed.
    assert rows[0]["output"] == "CANONICAL\n"
    assert rows[0]["finished_at"] is not None


@pytest.mark.asyncio
async def test_interrupted_turn_flushes_deltas_without_end_event(
    db: aiosqlite.Connection,
) -> None:
    """If a turn unwinds before `ToolCallEnd` fires (user stop,
    exception), the try/finally in `_execute_turn` flushes buffered
    deltas so mid-stream output is visible in history. Without this
    the interrupted tool call would have an empty `output` column
    despite deltas having been emitted on the wire."""
    sid = await _session_id(db)

    events: list[AgentEvent] = [
        MessageStart(session_id=sid, message_id="m-int"),
        ToolCallStart(session_id=sid, tool_call_id="t-orphan", name="bash", input={}),
        ToolOutputDelta(session_id=sid, tool_call_id="t-orphan", delta="partial-1\n"),
        ToolOutputDelta(session_id=sid, tool_call_id="t-orphan", delta="partial-2\n"),
        # No ToolCallEnd, no MessageComplete — stream ends abruptly.
    ]

    runner = _make_runner(sid, db, script=events)
    try:
        await _drain_turn(runner)
    finally:
        await runner.shutdown()

    rows = await store.list_tool_calls(db, sid)
    assert len(rows) == 1
    # Both deltas persisted, concatenated, in one coalesced write.
    assert rows[0]["output"] == "partial-1\npartial-2\n"
    # No `ToolCallEnd` means `finished_at` stays null.
    assert rows[0]["finished_at"] is None
