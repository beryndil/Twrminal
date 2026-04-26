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
    ContextUsage,
    ErrorEvent,
    MessageComplete,
    MessageStart,
    Token,
    ToolCallStart,
)
from bearings.agent.registry import RunnerRegistry
from bearings.agent.runner import RING_MAX, SUBSCRIBER_QUEUE_MAX, SessionRunner
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
async def test_subscribe_caught_up_returns_empty_replay(
    db: aiosqlite.Connection,
) -> None:
    """A reconnecting client whose `since_seq` is already at (or past)
    the runner's last seq must get an empty replay — not a duplicate
    flush of the latest events. Edge case introduced when the O(K)
    replay window short-circuits on `since_seq >= last_seq` rather
    than scanning the buffer."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    for i in range(4):
        await runner._emit_event(Token(session_id=sid, text=f"t{i}"))

    # Caller cursor sits exactly at the last seq → nothing newer exists.
    _q1, r1 = await runner.subscribe(since_seq=4)
    assert r1 == []

    # Caller cursor sits past the last seq (e.g. they kept counting
    # against ephemeral seqs that the buffer didn't store) → also empty.
    _q2, r2 = await runner.subscribe(since_seq=99)
    assert r2 == []


@pytest.mark.asyncio
async def test_subscribe_replay_skips_partial_after_evictions(
    db: aiosqlite.Connection,
) -> None:
    """When the ring has rolled past the client's `since_seq`, replay
    returns the full buffer (not just envelopes whose seq exceeds the
    requested gap), and seq order stays ascending. Pins behavior on
    the path that takes `list(event_log)` rather than the reversed-
    iter slice."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    for i in range(RING_MAX + 5):
        await runner._emit_event(Token(session_id=sid, text=str(i)))

    # since_seq < first buffered seq (which is 6 after 5 evictions).
    _queue, replay = await runner.subscribe(since_seq=1)
    assert len(replay) == RING_MAX
    seqs = [env.seq for env in replay]
    assert seqs[0] == 6
    assert seqs[-1] == RING_MAX + 5
    assert seqs == sorted(seqs)


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
async def test_stalled_subscriber_evicted_when_queue_fills(
    db: aiosqlite.Connection,
) -> None:
    """A subscriber that never drains its queue gets evicted once the
    queue hits `SUBSCRIBER_QUEUE_MAX` — the runner must not block fan-
    out for a slow client (security audit 2026-04-21 §3). A second,
    healthy subscriber that drains continues to receive events past
    the eviction."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    stalled, _ = await runner.subscribe(0)
    healthy, _ = await runner.subscribe(0)

    # Drain `healthy` in the background so it never fills; `stalled`
    # is left untouched and must hit the cap.
    drained: list[Any] = []

    async def drain() -> None:
        while True:
            env = await healthy.get()
            drained.append(env)

    drainer = asyncio.create_task(drain())
    try:
        for i in range(SUBSCRIBER_QUEUE_MAX + 1):
            await runner._emit_event(Token(session_id=sid, text=str(i)))
            # Yield so the drainer task can run.
            await asyncio.sleep(0)
    finally:
        drainer.cancel()
        try:
            await drainer
        except asyncio.CancelledError:
            pass

    assert stalled not in runner._subscribers, "stalled subscriber should be evicted"
    assert healthy in runner._subscribers, "healthy subscriber must be retained"
    assert len(drained) == SUBSCRIBER_QUEUE_MAX + 1, "healthy subscriber got every event"


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
async def test_todowrite_tool_call_emits_sidecar_update(db: aiosqlite.Connection) -> None:
    """When the SDK yields a `ToolCallStart` named `TodoWrite`, the
    runner persists the tool call normally AND emits a sidecar
    `TodoWriteUpdate` event carrying the parsed todo list.

    The sidecar is the whole reason the live widget works without
    hand-parsing `tool_calls[*].input` in the frontend: the reducer
    handles a dedicated event type, and the Inspector still sees the
    raw `ToolCallStart` for audit. Order matters — the raw event
    must land before the sidecar so subscribers that peek at
    `tool_calls` on the update see the row already inserted."""
    sid = await _session_id(db)
    todos = [
        {"content": "First step", "activeForm": "Doing first step", "status": "in_progress"},
        {"content": "Second step", "activeForm": "Doing second step", "status": "pending"},
    ]
    script: list[AgentEvent] = [
        MessageStart(session_id=sid, message_id="msg-tw"),
        ToolCallStart(
            session_id=sid,
            tool_call_id="tc-todo-1",
            name="TodoWrite",
            input={"todos": todos},
        ),
        MessageComplete(session_id=sid, message_id="msg-tw", cost_usd=None),
    ]
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[script]), db)
    queue, _ = await runner.subscribe(0)
    runner.start()
    try:
        await runner.submit_prompt("kick off a multi-step task")

        seen: list[dict[str, Any]] = []
        while not any(p["type"] == "message_complete" for p in seen):
            env = await asyncio.wait_for(queue.get(), timeout=2.0)
            seen.append(env.payload)

        types = [p["type"] for p in seen]
        assert "tool_call_start" in types
        assert "todo_write_update" in types
        # Order: raw call must land before the sidecar update so a
        # subscriber reading `tool_calls` on the update sees the row.
        assert types.index("tool_call_start") < types.index("todo_write_update")

        update = next(p for p in seen if p["type"] == "todo_write_update")
        assert update["session_id"] == sid
        assert [t["status"] for t in update["todos"]] == ["in_progress", "pending"]
        assert update["todos"][0]["content"] == "First step"
        # Wire shape: the alias 'activeForm' collapses to the python-
        # side field name 'active_form' on serialisation. The frontend
        # contract (core.ts) mirrors this.
        assert update["todos"][0]["active_form"] == "Doing first step"
    finally:
        await runner.shutdown()


@pytest.mark.asyncio
async def test_todowrite_malformed_input_does_not_crash_turn(
    db: aiosqlite.Connection,
) -> None:
    """A malformed TodoWrite payload (missing `todos`, wrong type on an
    item, etc.) must not kill the turn. The sidecar `TodoWriteUpdate`
    is skipped — the raw `ToolCallStart` still lands and the turn
    completes. Fail-soft because the live widget is a nice-to-have,
    not a correctness-critical path."""
    sid = await _session_id(db)
    script: list[AgentEvent] = [
        MessageStart(session_id=sid, message_id="msg-bad"),
        ToolCallStart(
            session_id=sid,
            tool_call_id="tc-bad",
            name="TodoWrite",
            # Item missing the required `status` field — model_validate rejects.
            input={"todos": [{"content": "no status here"}]},
        ),
        MessageComplete(session_id=sid, message_id="msg-bad", cost_usd=None),
    ]
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[script]), db)
    queue, _ = await runner.subscribe(0)
    runner.start()
    try:
        await runner.submit_prompt("trigger malformed todowrite")
        seen: list[str] = []
        while "message_complete" not in seen:
            env = await asyncio.wait_for(queue.get(), timeout=2.0)
            seen.append(env.payload["type"])
        # Raw tool call still there — only the sidecar was skipped.
        assert "tool_call_start" in seen
        assert "todo_write_update" not in seen
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
async def test_two_runners_execute_concurrently_without_crosstalk(
    db: aiosqlite.Connection,
) -> None:
    """Two sessions, two runners, two turns in flight at once. Events
    must land in the right subscriber queue and persist to the right
    session row. This is the multi-session concurrency guarantee the
    whole walk-away feature rests on — a regression where runners
    shared fan-out state (or where one's worker blocked another's)
    would manifest here, not in single-runner tests.

    Gate on A, release it AFTER B completes, to prove A's parked turn
    does not prevent B from making progress."""
    sid_a = await _session_id(db)
    row_b = await store.create_session(db, working_dir="/tmp", model="m", title="B")
    sid_b = row_b["id"]

    gate_a = asyncio.Event()
    agent_a = ScriptedAgent(
        sid_a,
        scripts=[_message_script(sid_a, "msg-A", "alpha")],
        gate=gate_a,
    )
    agent_b = ScriptedAgent(
        sid_b,
        scripts=[_message_script(sid_b, "msg-B", "beta")],
    )
    runner_a = SessionRunner(sid_a, agent_a, db)
    runner_b = SessionRunner(sid_b, agent_b, db)
    qa, _ = await runner_a.subscribe(0)
    qb, _ = await runner_b.subscribe(0)
    runner_a.start()
    runner_b.start()
    try:
        await runner_a.submit_prompt("P_A")
        await _wait_until(lambda: runner_a.is_running)
        # A is parked on its gate. Kick B; B must complete while A
        # stays parked. If runners shared a worker or lock, B would
        # hang here waiting for A.
        await runner_b.submit_prompt("P_B")

        seen_b: list[str] = []
        while "message_complete" not in seen_b:
            env = await asyncio.wait_for(qb.get(), timeout=2.0)
            # Every envelope B sees must carry B's session id.
            assert env.payload["session_id"] == sid_b
            seen_b.append(env.payload["type"])

        # A is still running (gated). Drain what's already in A's
        # queue — it must include MessageStart but not MessageComplete,
        # and every frame must be tagged for A only.
        assert runner_a.is_running
        drained_a: list[dict[str, Any]] = []
        while True:
            try:
                env = await asyncio.wait_for(qa.get(), timeout=0.05)
            except TimeoutError:
                break
            assert env.payload["session_id"] == sid_a
            drained_a.append(env.payload)
        types_a = {p["type"] for p in drained_a}
        assert "message_start" in types_a
        assert "message_complete" not in types_a

        # Release A; it should now finish.
        gate_a.set()
        while "message_complete" not in types_a:
            env = await asyncio.wait_for(qa.get(), timeout=2.0)
            assert env.payload["session_id"] == sid_a
            types_a.add(env.payload["type"])

        # Persistence is partitioned by session id — no leakage.
        msgs_a = {m["content"] for m in await store.list_messages(db, sid_a)}
        msgs_b = {m["content"] for m in await store.list_messages(db, sid_b)}
        assert {"P_A", "alpha"} <= msgs_a
        assert {"P_B", "beta"} <= msgs_b
        assert msgs_a.isdisjoint({"P_B", "beta"})
        assert msgs_b.isdisjoint({"P_A", "alpha"})
    finally:
        await runner_a.shutdown()
        await runner_b.shutdown()


@pytest.mark.asyncio
async def test_should_reap_requires_idle_and_no_subscribers_past_ttl(
    db: aiosqlite.Connection,
) -> None:
    """Pin the eviction predicate directly: `should_reap` returns True
    only when status is idle, zero subscribers are attached, and the
    quiet duration has passed the TTL. Subscribing a queue or flipping
    to running must immediately disqualify the runner — otherwise the
    reaper could shut down a runner mid-turn or with an active tab."""
    sid = await _session_id(db)
    runner = SessionRunner(sid, ScriptedAgent(sid, scripts=[]), db)
    # Backdate the quiet clock so the TTL comparison can trip without a
    # real sleep. Private attr access is intentional — we're pinning
    # the predicate, not the emergent behavior.
    runner._quiet_since = 0.0

    now = 1000.0
    assert runner.should_reap(now, ttl_seconds=100.0) is True
    # Not yet past TTL.
    assert runner.should_reap(now, ttl_seconds=2000.0) is False

    # Subscriber attached → not reapable regardless of TTL.
    queue, _ = await runner.subscribe(0)
    assert runner.should_reap(now, ttl_seconds=100.0) is False
    # Unsubscribe restarts the quiet clock; still idle, still reapable
    # given enough time.
    runner.unsubscribe(queue)
    assert runner._quiet_since is not None
    runner._quiet_since = 0.0
    assert runner.should_reap(now, ttl_seconds=100.0) is True

    # Mid-turn → not reapable even without subscribers.
    runner._status = "running"
    runner._quiet_since = None
    assert runner.should_reap(now, ttl_seconds=0.0) is False


@pytest.mark.asyncio
async def test_turn_lifecycle_toggles_quiet_clock(db: aiosqlite.Connection) -> None:
    """A turn should park the quiet clock while running and restart it
    on return to idle when no subscriber is attached. This is the
    emergent-behavior companion to the direct `should_reap` test — it
    proves the worker's status transitions wire through to the clock
    without us having to poke `_status` by hand."""
    sid = await _session_id(db)
    gate = asyncio.Event()
    script = _message_script(sid, "msg-q", "hi")
    agent = ScriptedAgent(sid, scripts=[script], gate=gate)
    runner = SessionRunner(sid, agent, db)
    runner.start()
    try:
        assert runner._quiet_since is not None  # fresh runner is quiet

        await runner.submit_prompt("P")
        await _wait_until(lambda: runner.is_running)
        assert runner._quiet_since is None  # turn active → clock off

        gate.set()
        await _wait_until(lambda: not runner.is_running)
        # No subscribers were attached, so idle return restarts the clock.
        assert runner._quiet_since is not None
    finally:
        await runner.shutdown()


@pytest.mark.asyncio
async def test_registry_reaper_evicts_only_quiet_runners(
    db: aiosqlite.Connection,
) -> None:
    """End-to-end reaper behavior across three runners: one quiet past
    TTL (evicted), one mid-turn (kept), one with a live subscriber
    (kept). Guards against a regression where the reaper shuts down
    active work or where an idle-forever runner outlives the TTL."""
    sid = await _session_id(db)
    # Session rows for runners B and C so `_session_id` isn't ambiguous.
    row_b = await store.create_session(db, working_dir="/tmp", model="m", title="B")
    row_c = await store.create_session(db, working_dir="/tmp", model="m", title="C")

    gate_b = asyncio.Event()
    agent_a = ScriptedAgent(sid, scripts=[])
    agent_b = ScriptedAgent(
        row_b["id"],
        scripts=[_message_script(row_b["id"], "msg-B", "b")],
        gate=gate_b,
    )
    agent_c = ScriptedAgent(row_c["id"], scripts=[])

    async def make(a_id: str) -> SessionRunner:
        if a_id == sid:
            return SessionRunner(sid, agent_a, db)
        if a_id == row_b["id"]:
            return SessionRunner(row_b["id"], agent_b, db)
        return SessionRunner(row_c["id"], agent_c, db)

    registry = RunnerRegistry(idle_ttl_seconds=60.0, reap_interval_seconds=3600.0)
    try:
        runner_a = await registry.get_or_create(sid, factory=make)
        runner_b = await registry.get_or_create(row_b["id"], factory=make)
        runner_c = await registry.get_or_create(row_c["id"], factory=make)

        # B: start a turn and hold it on the gate → not reapable.
        await runner_b.submit_prompt("go")
        await _wait_until(lambda: runner_b.is_running)
        # C: attach a subscriber → not reapable.
        _qc, _ = await runner_c.subscribe(0)
        # A: idle, no subs. Backdate so `now` in reap_once trips the TTL.
        runner_a._quiet_since = 0.0

        evicted = await registry.reap_once(now=1000.0)
        assert evicted == [sid]
        assert registry.get(sid) is None
        assert registry.get(row_b["id"]) is runner_b
        assert registry.get(row_c["id"]) is runner_c
        assert runner_a._worker is not None and runner_a._worker.done()

        # Release B so shutdown_all can drain it cleanly.
        gate_b.set()
        await _wait_until(lambda: not runner_b.is_running)
    finally:
        await registry.shutdown_all()


@pytest.mark.asyncio
async def test_registry_reaper_disabled_when_ttl_nonpositive(
    db: aiosqlite.Connection,
) -> None:
    """TTL <= 0 is the opt-out. `reap_once` must short-circuit even
    when a runner is well past any plausible TTL, and `start_reaper`
    must not spawn a task — we reuse the v0.3.13 behavior of
    "runners live until delete or shutdown" when the operator sets
    `idle_ttl_seconds = 0`."""
    sid = await _session_id(db)

    async def factory(session_id: str) -> SessionRunner:
        return SessionRunner(session_id, ScriptedAgent(session_id, scripts=[]), db)

    registry = RunnerRegistry(idle_ttl_seconds=0.0)
    try:
        runner = await registry.get_or_create(sid, factory=factory)
        runner._quiet_since = 0.0
        registry.start_reaper()
        assert registry._reaper is None
        evicted = await registry.reap_once(now=1e9)
        assert evicted == []
        assert registry.get(sid) is runner
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


# ---- context-usage persistence (Option 1 / migration 0013) ---------


@pytest.mark.asyncio
async def test_runner_persists_context_usage_to_session_row(
    db: aiosqlite.Connection,
) -> None:
    """A ContextUsage event in the turn's stream causes the runner to
    write `last_context_pct` / tokens / max onto the session row so a
    fresh page load without an active WS sees a number. Verified by
    replaying a scripted turn that includes a ContextUsage event and
    then reading the row back through the same store helper the UI
    uses."""
    sid = await _session_id(db)
    msg_id = "m1"
    script: list[AgentEvent] = [
        MessageStart(session_id=sid, message_id=msg_id),
        Token(session_id=sid, text="hi"),
        ContextUsage(
            session_id=sid,
            total_tokens=45_000,
            max_tokens=200_000,
            percentage=22.5,
            model="m",
            is_auto_compact_enabled=True,
            auto_compact_threshold=175_000,
        ),
        MessageComplete(session_id=sid, message_id=msg_id, cost_usd=None),
    ]
    agent = ScriptedAgent(sid, scripts=[script])
    runner = SessionRunner(sid, agent, db)
    runner.start()
    try:
        await runner.submit_prompt("hi")
        await _wait_until(lambda: not runner.is_running)
    finally:
        await runner.shutdown()
    row = await store.get_session(db, sid)
    assert row is not None
    assert row["last_context_pct"] == pytest.approx(22.5)
    assert row["last_context_tokens"] == 45_000
    assert row["last_context_max"] == 200_000


# ---- submit_prompt budget gate (Option 7) -------------------------


@pytest.mark.asyncio
async def test_submit_prompt_refuses_when_cap_reached(
    db: aiosqlite.Connection,
) -> None:
    """When `sessions.total_cost_usd >= max_budget_usd`, `submit_prompt`
    refuses the new prompt and emits a user-visible ErrorEvent. The
    SDK's own `max_budget_usd` advisory fires only once cost accrues
    during a turn, so without this gate a user already over-cap can
    kick off another turn that runs to completion before the advisory
    bites. Fail-closed at the gate."""
    sid = await _session_id(db)
    # Arrange: set both the cap and the already-accrued cost so the
    # session is sitting right on the cap. Using the real store helpers
    # exercises the same path a real session would hit.
    await db.execute(
        "UPDATE sessions SET max_budget_usd = ?, total_cost_usd = ? WHERE id = ?",
        (1.00, 1.00, sid),
    )
    await db.commit()

    agent = ScriptedAgent(sid, scripts=[])
    runner = SessionRunner(sid, agent, db)
    queue, _ = await runner.subscribe(0)
    runner.start()
    try:
        await runner.submit_prompt("this should never run")
        env = await asyncio.wait_for(queue.get(), timeout=1.0)
    finally:
        await runner.shutdown()
    assert env.payload["type"] == "error"
    assert "budget" in env.payload["message"].lower()
    # Nothing ever made it onto the worker's prompt queue.
    assert agent.prompts == []


@pytest.mark.asyncio
async def test_submit_prompt_allows_when_cap_not_yet_reached(
    db: aiosqlite.Connection,
) -> None:
    """Converse of the refuse test: cost below the cap passes straight
    through to the worker. Also covers the `max_budget_usd is None`
    default (most sessions) by virtue of the fixture starting with
    no cap set on the cost-under-cap row."""
    sid = await _session_id(db)
    await db.execute(
        "UPDATE sessions SET max_budget_usd = ?, total_cost_usd = ? WHERE id = ?",
        (5.00, 0.10, sid),
    )
    await db.commit()

    msg_id = "m1"
    script: list[AgentEvent] = [
        MessageStart(session_id=sid, message_id=msg_id),
        MessageComplete(session_id=sid, message_id=msg_id, cost_usd=None),
    ]
    agent = ScriptedAgent(sid, scripts=[script])
    runner = SessionRunner(sid, agent, db)
    runner.start()
    try:
        await runner.submit_prompt("go")
        await _wait_until(lambda: agent.prompts == ["go"])
    finally:
        await runner.shutdown()


@pytest.mark.asyncio
async def test_submit_prompt_no_cap_is_always_allowed(
    db: aiosqlite.Connection,
) -> None:
    """The default-case: no `max_budget_usd` set at all (None in the
    DB). Must never refuse — caps are opt-in and absence of the column
    means "no ceiling". Regression guard for a NULL-compare slip."""
    sid = await _session_id(db)
    msg_id = "m1"
    script: list[AgentEvent] = [
        MessageStart(session_id=sid, message_id=msg_id),
        MessageComplete(session_id=sid, message_id=msg_id, cost_usd=None),
    ]
    agent = ScriptedAgent(sid, scripts=[script])
    runner = SessionRunner(sid, agent, db)
    runner.start()
    try:
        await runner.submit_prompt("go")
        await _wait_until(lambda: agent.prompts == ["go"])
    finally:
        await runner.shutdown()
    # Sanity: confirm the ErrorEvent path was not taken.
    errors = [
        env
        for env in runner._event_log
        if isinstance(env.payload, dict) and env.payload.get("type") == "error"
    ]
    assert errors == []
    # Typing-only: reference ErrorEvent so the import doesn't become
    # a lint casualty if the refuse-test is ever pruned.
    assert ErrorEvent.__name__ == "ErrorEvent"
