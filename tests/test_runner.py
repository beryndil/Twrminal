"""Unit tests for `bearings.agent.runner`.

The runner is the piece that makes sessions independent of WebSocket
lifetime: turns keep running when the client disconnects, events are
buffered for replay, and the prompt queue serialises turns. These
tests pin that contract directly, without going through the WS layer.

`ScriptedAgent` below subclasses `AgentSession` but overrides `stream`
and `interrupt` so tests can program event sequences and pause
mid-turn via an `asyncio.Event`. That lets us observe "turn in flight"
behavior deterministically instead of racing against wall-clock
timing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from bearings.agent.events import (
    AgentEvent,
    MessageComplete,
    MessageStart,
    Token,
)
from bearings.agent.runner import RING_MAX, RunnerRegistry, SessionRunner
from bearings.agent.session import AgentSession
from bearings.db import store
from bearings.db._common import init_db


class ScriptedAgent(AgentSession):
    """Test stub: yields pre-programmed events per `stream()` call.

    - `scripts`: a list of event-lists, one per turn. The first
      `stream()` call consumes `scripts[0]`, the second `scripts[1]`,
      etc. Running out of scripts yields nothing.
    - `gate`: when set, the *first* turn pauses after yielding its
      first event until `gate.set()` is called. Later turns run
      straight through. This lets a test observe `runner.is_running`
      in the middle of a turn.
    - `interrupt_count`: bumped every time `interrupt()` is called.
      The stub also sets the gate so a gated first turn can wind down
      after a stop request.
    """

    def __init__(
        self,
        session_id: str,
        scripts: list[list[AgentEvent]],
        gate: asyncio.Event | None = None,
    ) -> None:
        super().__init__(session_id, working_dir="/tmp", model="m")
        self._scripts = scripts
        self._gate = gate
        self.interrupt_count = 0
        self.prompts: list[str] = []

    async def stream(self, prompt: str) -> AsyncIterator[AgentEvent]:
        self.prompts.append(prompt)
        script = self._scripts.pop(0) if self._scripts else []
        gate_this_turn = self._gate is not None and len(self.prompts) == 1
        for i, event in enumerate(script):
            yield event
            if gate_this_turn and i == 0 and self._gate is not None:
                await self._gate.wait()

    async def interrupt(self) -> None:
        self.interrupt_count += 1
        if self._gate is not None:
            # Release the gate so a stopped stream can unwind and the
            # runner's loop reaches its `if stopped: break` check.
            self._gate.set()


# ---- fixtures ------------------------------------------------------


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Real sqlite DB + one session row ready for a runner to persist
    into. Separate per test so persistence assertions can inspect the
    DB without cross-test contamination."""
    conn = await init_db(tmp_path / "runner.sqlite")
    await store.create_session(conn, working_dir="/tmp", model="m", title="t")
    yield conn
    await conn.close()


async def _session_id(conn: aiosqlite.Connection) -> str:
    # The db fixture inserted exactly one session; look it up so the
    # ScriptedAgent stamps the right id onto events.
    rows = await store.list_sessions(conn)
    return rows[0]["id"]


def _message_script(sid: str, msg_id: str, text: str) -> list[AgentEvent]:
    """Canonical 3-event turn: start → one token → complete. Enough
    to exercise persistence without flooding the ring buffer."""
    return [
        MessageStart(session_id=sid, message_id=msg_id),
        Token(session_id=sid, text=text),
        MessageComplete(session_id=sid, message_id=msg_id, cost_usd=None),
    ]


async def _wait_until(predicate: Any, timeout: float = 2.0, interval: float = 0.01) -> None:
    """Poll an async-friendly condition. Tests use this to wait for
    the worker to reach a state without sleeping for a fixed duration,
    keeping them fast when the condition trips immediately and robust
    when CI is slow."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        if predicate():
            return
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("condition did not hold within timeout")
        await asyncio.sleep(interval)


# ---- _emit_event + ring buffer + subscribers -----------------------


@pytest.mark.asyncio
async def test_subscribe_replays_events_after_since_seq(
    db: aiosqlite.Connection,
) -> None:
    """Events with seq > since_seq come back in the replay list in
    order. Foundation of reconnect-and-catch-up: client passes its
    last-seen seq and the runner replays only the gap."""
    sid = await _session_id(db)
    agent = ScriptedAgent(sid, scripts=[])
    runner = SessionRunner(sid, agent, db)
    for i in range(5):
        await runner._emit_event(Token(session_id=sid, text=f"t{i}"))

    _queue, replay = await runner.subscribe(since_seq=2)
    assert [env.seq for env in replay] == [3, 4, 5]
    assert [env.payload["text"] for env in replay] == ["t2", "t3", "t4"]


@pytest.mark.asyncio
async def test_subscribe_from_zero_replays_whole_buffer(
    db: aiosqlite.Connection,
) -> None:
    """Fresh client (since_seq=0) gets everything still in the ring.
    This is the first-connect path — the client has nothing rendered
    yet, so any buffered events are fair game."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    for i in range(3):
        await runner._emit_event(Token(session_id=sid, text=f"t{i}"))

    _queue, replay = await runner.subscribe(since_seq=0)
    assert [env.seq for env in replay] == [1, 2, 3]


@pytest.mark.asyncio
async def test_multiple_subscribers_each_receive_live_events(
    db: aiosqlite.Connection,
) -> None:
    """Two clients attached to the same runner each get every live
    event. Covers the "open two tabs pointing at the same session"
    case; both should see the same stream."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    q1, _ = await runner.subscribe(0)
    q2, _ = await runner.subscribe(0)
    await runner._emit_event(Token(session_id=sid, text="x"))

    env1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    env2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert env1.seq == env2.seq == 1
    assert env1.payload["text"] == env2.payload["text"] == "x"


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery(db: aiosqlite.Connection) -> None:
    """Removing a subscriber means no further envelopes arrive on its
    queue. Handlers call this on WS disconnect; a leak here would
    keep old queues pinned in memory and flood them with every event
    emitted for the rest of the runner's life."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    queue, _ = await runner.subscribe(0)
    await runner._emit_event(Token(session_id=sid, text="first"))
    env1 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert env1.payload["text"] == "first"

    runner.unsubscribe(queue)
    await runner._emit_event(Token(session_id=sid, text="second"))
    # After unsubscribe the queue is inert — a short wait must time out.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.05)


@pytest.mark.asyncio
async def test_ring_buffer_rolls_off_oldest(db: aiosqlite.Connection) -> None:
    """Emitting more than `RING_MAX` events drops the oldest from the
    replay window but keeps seq numbers monotonically increasing.
    A reconnecting client that was further behind than the buffer
    depth loses intermediate events — the frontend dedupes on
    `message_complete` so the final turn result still lands."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    for i in range(RING_MAX + 10):
        await runner._emit_event(Token(session_id=sid, text=str(i)))

    _queue, replay = await runner.subscribe(since_seq=0)
    assert len(replay) == RING_MAX
    # Oldest envelope in the buffer has rolled forward past seq 1.
    assert replay[0].seq == 11
    assert replay[-1].seq == RING_MAX + 10


# ---- worker: prompt queue + persistence ----------------------------


@pytest.mark.asyncio
async def test_worker_executes_turn_and_persists(db: aiosqlite.Connection) -> None:
    """Happy path: submit one prompt, the worker runs it to completion,
    user + assistant messages land in the DB, and subscribers see the
    full event sequence including MessageComplete."""
    sid = await _session_id(db)
    script = _message_script(sid, "msg-1", "hello")
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[script]), db)
    queue, _ = await runner.subscribe(0)
    runner.start()
    try:
        await runner.submit_prompt("hi")

        seen_types: list[str] = []
        while "message_complete" not in seen_types:
            env = await asyncio.wait_for(queue.get(), timeout=2.0)
            seen_types.append(env.payload["type"])
        assert seen_types == ["message_start", "token", "message_complete"]

        # Persistence: user prompt + assistant reply, in order.
        rows = await store.list_messages(db, sid)
        roles_and_content = [(r["role"], r["content"]) for r in rows]
        assert ("user", "hi") in roles_and_content
        assert ("assistant", "hello") in roles_and_content
    finally:
        await runner.shutdown()


@pytest.mark.asyncio
async def test_prompt_queue_is_sequential(db: aiosqlite.Connection) -> None:
    """Prompts submitted while a turn is in flight queue up; the
    worker processes them strictly in submission order. Without this
    the SDK would see interleaved queries on the same session and
    wedge — the prompt queue is what makes the runner safe to
    hammer from multiple callers."""
    sid = await _session_id(db)
    gate = asyncio.Event()
    scripts = [
        _message_script(sid, "msg-A", "a"),
        _message_script(sid, "msg-B", "b"),
    ]
    agent = ScriptedAgent(sid, scripts=scripts, gate=gate)
    runner = SessionRunner(sid, agent, db)
    runner.start()
    try:
        await runner.submit_prompt("A")
        # Wait for the worker to actually enter turn A (gated after
        # MessageStart). Status flips to running once the worker
        # pulled the prompt off the queue.
        await _wait_until(lambda: runner.is_running)
        await _wait_until(lambda: agent.prompts == ["A"])

        # Queue B while A is parked. B must not start until A finishes.
        await runner.submit_prompt("B")
        await asyncio.sleep(0.05)
        assert agent.prompts == ["A"], "B started before A finished"

        # Release A; B should follow.
        gate.set()
        await _wait_until(lambda: agent.prompts == ["A", "B"])
    finally:
        await runner.shutdown()


@pytest.mark.asyncio
async def test_request_stop_mid_turn_persists_partial(
    db: aiosqlite.Connection,
) -> None:
    """Stopping a turn between events calls the SDK's interrupt, ends
    the stream, emits a synthetic MessageComplete, and persists the
    partial assistant content to the DB. Without synthesis the UI
    would sit in 'streaming' state forever waiting for a complete
    frame that can never arrive."""
    sid = await _session_id(db)
    gate = asyncio.Event()
    # Script that would finish normally if the gate released; we stop
    # it after the first token so MessageComplete never fires.
    script = [
        MessageStart(session_id=sid, message_id="msg-stop"),
        Token(session_id=sid, text="partial"),
        Token(session_id=sid, text="-more"),
        MessageComplete(session_id=sid, message_id="msg-stop", cost_usd=None),
    ]
    agent = ScriptedAgent(sid, scripts=[script], gate=gate)
    runner = SessionRunner(sid, agent, db)
    queue, _ = await runner.subscribe(0)
    runner.start()
    try:
        await runner.submit_prompt("stop me")
        await _wait_until(lambda: runner.is_running)
        # Drain the first event off our subscriber so we know the
        # turn actually started streaming.
        env = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert env.payload["type"] == "message_start"

        await runner.request_stop()
        # interrupt called at least once (stop path; may be called
        # twice if shutdown also fires it — we assert >= to stay
        # robust).
        assert agent.interrupt_count >= 1

        # Drain remaining events; a synthetic MessageComplete must
        # appear before the runner returns to idle.
        saw_complete = False
        deadline = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                env = await asyncio.wait_for(queue.get(), timeout=0.1)
            except TimeoutError:
                if not runner.is_running:
                    break
                continue
            if env.payload["type"] == "message_complete":
                saw_complete = True
                break
        assert saw_complete, "no synthetic MessageComplete emitted"

        # Partial token was persisted as the assistant message.
        rows = await store.list_messages(db, sid)
        assistant = [r for r in rows if r["role"] == "assistant"]
        assert len(assistant) == 1
        assert "partial" in assistant[0]["content"]
    finally:
        await runner.shutdown()


@pytest.mark.asyncio
async def test_shutdown_interrupts_in_flight_turn(
    db: aiosqlite.Connection,
) -> None:
    """App-shutdown path: runner.shutdown() must call the SDK's
    interrupt so a live tool call gets told to abort, then stop the
    worker task. Without this the uvicorn process can't exit cleanly
    while a turn is streaming."""
    sid = await _session_id(db)
    gate = asyncio.Event()
    script = _message_script(sid, "msg-sd", "x")
    agent = ScriptedAgent(sid, scripts=[script], gate=gate)
    runner = SessionRunner(sid, agent, db)
    runner.start()

    await runner.submit_prompt("go")
    await _wait_until(lambda: runner.is_running)
    assert agent.interrupt_count == 0

    await runner.shutdown()
    assert agent.interrupt_count >= 1
    assert runner._worker is not None and runner._worker.done()


# ---- RunnerRegistry ------------------------------------------------


@pytest.mark.asyncio
async def test_registry_get_or_create_is_race_safe(
    db: aiosqlite.Connection,
) -> None:
    """Two concurrent WS connects for the same session id must land
    on the same runner instance — the registry's internal lock is
    what prevents a double-spawn that would duplicate every event."""
    sid = await _session_id(db)
    factory_calls = 0

    async def factory(session_id: str) -> SessionRunner:
        nonlocal factory_calls
        factory_calls += 1
        # Brief sleep widens the race window; without the lock both
        # callers would see "no runner yet" and construct one each.
        await asyncio.sleep(0.01)
        return SessionRunner(session_id, ScriptedAgent(session_id, scripts=[]), db)

    registry = RunnerRegistry()
    try:
        r1, r2 = await asyncio.gather(
            registry.get_or_create(sid, factory=factory),
            registry.get_or_create(sid, factory=factory),
        )
        assert r1 is r2
        assert factory_calls == 1
    finally:
        await registry.shutdown_all()


@pytest.mark.asyncio
async def test_registry_drop_shuts_down_runner(db: aiosqlite.Connection) -> None:
    """Deleting a session drops its runner — the worker task exits
    and a subsequent lookup returns None. Leaving orphan runners
    around would keep SDK subprocesses alive for deleted sessions."""
    sid = await _session_id(db)

    async def factory(session_id: str) -> SessionRunner:
        return SessionRunner(session_id, ScriptedAgent(session_id, scripts=[]), db)

    registry = RunnerRegistry()
    runner = await registry.get_or_create(sid, factory=factory)
    assert registry.get(sid) is runner

    await registry.drop(sid)
    assert registry.get(sid) is None
    assert runner._worker is not None and runner._worker.done()


@pytest.mark.asyncio
async def test_registry_running_ids_reflects_live_turns(
    db: aiosqlite.Connection,
) -> None:
    """`running_ids()` is what powers the sidebar's "this session is
    still working" badge. It must include sessions mid-turn and
    exclude idle ones, so the UI doesn't claim a session is busy
    when it isn't."""
    sid = await _session_id(db)
    gate = asyncio.Event()
    script = _message_script(sid, "msg-live", "y")
    agent = ScriptedAgent(sid, scripts=[script], gate=gate)

    async def factory(session_id: str) -> SessionRunner:
        return SessionRunner(session_id, agent, db)

    registry = RunnerRegistry()
    try:
        runner = await registry.get_or_create(sid, factory=factory)
        assert registry.running_ids() == set()  # idle

        await runner.submit_prompt("go")
        await _wait_until(lambda: sid in registry.running_ids())

        # Release the gate; runner returns to idle after the turn.
        gate.set()
        await _wait_until(lambda: registry.running_ids() == set())
    finally:
        await registry.shutdown_all()


@pytest.mark.asyncio
async def test_registry_shutdown_all_drains_every_runner(
    db: aiosqlite.Connection,
) -> None:
    """Lifespan teardown depends on this: every runner gets a clean
    shutdown (interrupt + worker join) before the DB connection
    closes, so in-flight SDK subprocesses don't outlive their
    persistence layer."""
    sid = await _session_id(db)
    # Two runners pointing at the same session row is fine for this
    # test — we're exercising the registry's iteration, not session
    # uniqueness. Use distinct keys so both land in the dict.
    agents = [ScriptedAgent(sid, scripts=[]) for _ in range(2)]

    async def make(i: int) -> SessionRunner:
        return SessionRunner(sid, agents[i], db)

    registry = RunnerRegistry()
    r0 = await registry.get_or_create("k0", factory=lambda _sid: make(0))
    r1 = await registry.get_or_create("k1", factory=lambda _sid: make(1))

    await registry.shutdown_all()
    for runner in (r0, r1):
        assert runner._worker is not None and runner._worker.done()
    assert registry.get("k0") is None
    assert registry.get("k1") is None
