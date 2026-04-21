"""Per-session runner that owns agent execution independently of any
WebSocket connection.

Why: in v0.2.x the agent loop lived inside the WS handler, so closing
the socket (navigate-away, session switch, tab close) killed the
in-flight stream. Sessions are meant to be independent — you should be
able to kick off work in one and walk away. The runner owns the
`AgentSession`, the streaming task, and a ring buffer of recent events.
WebSocket handlers become thin subscribers that can come and go without
disturbing execution. Completed messages/tool calls are already
persisted to SQLite (see `_execute_turn`), so "closed the tab, came
back an hour later" also works across server restarts.

Lifecycle:
- First WS connect for a session constructs a runner and registers it.
- Runner lives until the app shuts down or the session is deleted.
- Subscribers (WS connections) attach via `subscribe(since_seq)`; any
  buffered events with seq > since_seq are replayed so a reconnecting
  client catches up.
- A single worker task drains a prompt queue; prompts submitted during
  an in-flight turn wait their turn.

Nothing in here depends on FastAPI or WebSockets — that's deliberate so
the runner is trivially testable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Literal
from uuid import uuid4

import aiosqlite

from bearings import metrics
from bearings.agent.approval_broker import ApprovalBroker
from bearings.agent.events import (
    AgentEvent,
    ErrorEvent,
    MessageComplete,
    MessageStart,
    Thinking,
    Token,
    ToolCallEnd,
    ToolCallStart,
    ToolOutputDelta,
)
from bearings.agent.session import AgentSession
from bearings.db import store

log = logging.getLogger(__name__)

# How many recent events to keep for reconnect replay. Five thousand
# comfortably covers a long multi-tool turn where each token is a
# separate event; old entries roll off the front. If a client is away
# longer than this buffer's window, it misses intermediate tokens but
# still catches the final `message_complete` (and the completed
# assistant message is in the DB either way).
RING_MAX = 5000


# Sentinel queued into `_prompts` by `shutdown()` so the worker exits
# its blocking `get()` and winds down cleanly.
class _Shutdown:
    pass


_SHUTDOWN = _Shutdown()

RunnerStatus = Literal["idle", "running"]


class _Envelope:
    """Event plus its monotonically-increasing sequence number.

    Subscribers receive envelopes so they can update their own
    `lastSeq` cursor for future reconnects. Using a small class rather
    than a tuple to keep attribute access obvious at call sites."""

    __slots__ = ("seq", "payload")

    def __init__(self, seq: int, payload: dict[str, Any]) -> None:
        self.seq = seq
        self.payload = payload


class SessionRunner:
    """Owns one session's agent execution. Long-lived; decoupled from
    WebSocket connections so sessions keep running when the UI walks
    away."""

    def __init__(
        self,
        session_id: str,
        agent: AgentSession,
        db: aiosqlite.Connection,
    ) -> None:
        self.session_id = session_id
        self.agent = agent
        self.db = db
        self._prompts: asyncio.Queue[str | _Shutdown] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._subscribers: set[asyncio.Queue[_Envelope]] = set()
        self._event_log: deque[_Envelope] = deque(maxlen=RING_MAX)
        self._next_seq = 1
        self._status: RunnerStatus = "idle"
        # True while a turn is mid-flight and the user asked to stop.
        # The stream loop checks this between events and calls
        # `agent.interrupt()` to cancel any in-flight tool call. A turn
        # clears it on entry so stale stop flags don't short-circuit
        # the next prompt.
        self._stop_requested = False
        # Tool-use approval state lives in its own small helper so this
        # class stays focused on the stream / prompt queue. The broker
        # owns the pending-Futures dict and the `ApprovalRequest` /
        # `ApprovalResolved` event emission; the runner just forwards
        # `resolve_approval` from the WS handler and tells it to deny
        # everything on stop / shutdown.
        self._approval = ApprovalBroker(session_id, self._emit_event)
        # Monotonic timestamp of the moment the runner most recently
        # became "quiet" — idle AND zero subscribers. The registry's
        # reaper uses `now - _quiet_since` vs. the configured TTL to
        # decide whether to evict. `None` means the runner is currently
        # active on at least one axis (a turn is running or a WS is
        # attached); initialized at construction because a just-built
        # runner has no subscribers yet and status is idle — the ws
        # handler flips the clock off via `subscribe()` immediately,
        # so this initial window is effectively zero.
        self._quiet_since: float | None = time.monotonic()

    # ---- lifecycle -------------------------------------------------

    def start(self) -> None:
        """Spawn the worker task. Idempotent — safe to call twice."""
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(
                self._run_forever(), name=f"runner:{self.session_id}"
            )

    async def shutdown(self) -> None:
        """Drain the prompt queue and stop the worker. Used on app
        shutdown and on session deletion. If a turn is in flight, the
        SDK client is interrupted first so the subprocess winds down."""
        self._stop_requested = True
        # Deny any pending approvals with `interrupt=True` so the SDK
        # stops waiting for a user decision that will never come and
        # the stream loop can reach its shutdown path.
        await self._approval.deny_all("runner shutting down", interrupt=True)
        try:
            await self.agent.interrupt()
        except Exception:
            # Best-effort — the worker's own exception handling will
            # log if the stream dies unexpectedly.
            pass
        await self._prompts.put(_SHUTDOWN)
        if self._worker is not None:
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    # ---- public API ------------------------------------------------

    @property
    def status(self) -> RunnerStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._status == "running"

    async def submit_prompt(self, prompt: str) -> None:
        """Queue a prompt for this session. Prompts are processed
        sequentially — if a turn is already in flight, this one waits."""
        await self._prompts.put(prompt)

    async def set_permission_mode(self, mode: Any) -> None:
        """Update the SDK's permission mode AND retro-apply it to any
        approval already parked on a user decision.

        Forwarding to the SDK is not enough on its own: the SDK only
        consults the new mode the *next* time it calls `can_use_tool`,
        so a user who flips the header selector to `bypassPermissions`
        while a modal is on screen would still be stuck clicking the
        modal. Handing the new mode to the broker lets it clear the
        current Future per the accept-edits / bypass matrix and emits
        `approval_resolved` so every mirroring tab drops its modal too.

        Persists the choice to `sessions.permission_mode` (migration
        0012) so a browser reload or socket drop restores the same
        mode instead of silently dropping to 'default'."""
        self.agent.set_permission_mode(mode)
        if isinstance(mode, str):
            await self._approval.resolve_for_mode(mode)
        # Persist str modes and explicit None (== clear the override).
        # Non-string truthy values are treated as malformed wire frames
        # and left alone — don't clobber a good DB value with a bad
        # one. Invalid strings are rejected by the store helper; we
        # swallow that ValueError so a bad frame can't crash the runner.
        if isinstance(mode, str) or mode is None:
            try:
                await store.set_session_permission_mode(self.db, self.session_id, mode)
            except ValueError:
                log.warning(
                    "runner %s: rejected unknown permission mode %r",
                    self.session_id,
                    mode,
                )

    async def request_stop(self) -> None:
        """User-initiated stop of the current turn. Flags the worker
        loop and calls `agent.interrupt()` so the SDK aborts any
        in-flight tool call. Safe to call when idle (no-op)."""
        self._stop_requested = True
        # If the turn is parked on a pending approval, the stream won't
        # make any progress toward the stop flag until the Future is
        # resolved. Deny them all with `interrupt=True` so the SDK
        # unwinds and the loop reaches the stop check.
        await self._approval.deny_all("stopped by user", interrupt=True)
        try:
            await self.agent.interrupt()
        except Exception:
            pass

    # ---- tool-use approval ----------------------------------------

    @property
    def can_use_tool(self) -> Any:
        """Callback bound onto `AgentSession.can_use_tool` by
        `ws_agent._build_runner`. Forwarding property so callers don't
        need to know a broker exists; the runner remains the single
        public surface the WS layer talks to."""
        return self._approval.can_use_tool

    async def resolve_approval(
        self, request_id: str, decision: str, reason: str | None = None
    ) -> None:
        """WS → broker forwarder. Kept on the runner so the WS handler
        has one object to hold (runner), not two (runner + broker)."""
        await self._approval.resolve(request_id, decision, reason)

    async def subscribe(
        self, since_seq: int = 0
    ) -> tuple[asyncio.Queue[_Envelope], list[_Envelope]]:
        """Register a subscriber queue and return buffered events with
        seq > since_seq for replay. Reconnecting clients pass the last
        seq they saw; fresh clients pass 0 to replay the whole window."""
        queue: asyncio.Queue[_Envelope] = asyncio.Queue()
        self._subscribers.add(queue)
        # A WS is attached — not quiet anymore. Clearing unconditionally
        # is simpler than checking prior state; the idle→running path
        # clears it too.
        self._quiet_since = None
        replay = [env for env in self._event_log if env.seq > since_seq]
        return queue, replay

    def unsubscribe(self, queue: asyncio.Queue[_Envelope]) -> None:
        self._subscribers.discard(queue)
        # If the last WS just walked away and no turn is in flight, the
        # reaper clock starts now. If a turn is still running, wait for
        # the worker's idle transition to start the clock — we don't
        # want to evict a runner that's actively producing events even
        # though its client left.
        if self._status == "idle" and not self._subscribers:
            self._quiet_since = time.monotonic()

    # ---- reaper hook ----------------------------------------------

    def should_reap(self, now: float, ttl_seconds: float) -> bool:
        """Does this runner qualify for idle eviction?

        True iff it's currently quiet (idle, no subscribers) AND has
        been quiet for at least `ttl_seconds`. The registry reaper
        calls this under its lock; the runner itself does not take
        action on eviction — that's the registry's job (pop + shutdown).
        """
        if self._status != "idle":
            return False
        if self._subscribers:
            return False
        if self._quiet_since is None:
            return False
        return (now - self._quiet_since) >= ttl_seconds

    # ---- worker ----------------------------------------------------

    async def _run_forever(self) -> None:
        while True:
            item = await self._prompts.get()
            if isinstance(item, _Shutdown):
                return
            self._status = "running"
            # A turn is live — not quiet regardless of subscriber count.
            # Clear here rather than spread the condition through every
            # status mutation site.
            self._quiet_since = None
            self._stop_requested = False
            try:
                await self._execute_turn(item)
            except Exception as exc:
                log.exception("runner %s: turn failed", self.session_id)
                await self._emit_event(ErrorEvent(session_id=self.session_id, message=str(exc)))
            finally:
                self._status = "idle"
                # If nobody's watching, start the reaper clock. A
                # connected subscriber keeps the clock off until it
                # unsubscribes.
                if not self._subscribers:
                    self._quiet_since = time.monotonic()

    async def _execute_turn(self, prompt: str) -> None:  # noqa: C901
        """Run one agent turn end-to-end. Mirrors the pre-runner
        ws_agent loop: persist user message, stream agent events,
        persist assistant turn + tool calls as they complete. Events
        are fanned out to subscribers via `_emit_event`."""
        await store.insert_message(self.db, session_id=self.session_id, role="user", content=prompt)
        metrics.messages_persisted.labels(role="user").inc()
        # Intentionally not emitting a `user_message` event here. The
        # frontend pushes the user message optimistically on submit,
        # and a second client that subscribes while the turn is in
        # flight will catch up via `GET /messages` on session load —
        # the ring buffer only needs to carry *streamed* output.

        buf: list[str] = []
        thinking_buf: list[str] = []
        tool_call_ids: list[str] = []
        current_message_id: str | None = None
        persisted = False
        stopped = False

        async for event in self.agent.stream(prompt):
            await self._emit_event(event)
            if isinstance(event, MessageStart):
                current_message_id = event.message_id
            elif isinstance(event, Token):
                buf.append(event.text)
            elif isinstance(event, Thinking):
                thinking_buf.append(event.text)
            elif isinstance(event, ToolCallStart):
                await store.insert_tool_call_start(
                    self.db,
                    session_id=self.session_id,
                    tool_call_id=event.tool_call_id,
                    name=event.name,
                    input_json=json.dumps(event.input),
                )
                tool_call_ids.append(event.tool_call_id)
                metrics.tool_calls_started.inc()
            elif isinstance(event, ToolOutputDelta):
                # Persist each chunk as it arrives so the history
                # endpoint + any reconnecting WebSocket see the
                # cumulative output. `finish_tool_call` later
                # overwrites with the canonical final string, so a
                # missed delta doesn't leave a permanent gap.
                await store.append_tool_output(
                    self.db,
                    tool_call_id=event.tool_call_id,
                    chunk=event.delta,
                )
            elif isinstance(event, ToolCallEnd):
                await store.finish_tool_call(
                    self.db,
                    tool_call_id=event.tool_call_id,
                    output=event.output,
                    error=event.error,
                )
                metrics.tool_calls_finished.labels(ok=str(event.ok).lower()).inc()
            elif isinstance(event, MessageComplete):
                await _persist_assistant_turn(
                    self.db,
                    session_id=self.session_id,
                    message_id=event.message_id,
                    content="".join(buf),
                    thinking="".join(thinking_buf) or None,
                    tool_call_ids=tool_call_ids,
                    cost_usd=event.cost_usd,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                    cache_read_tokens=event.cache_read_tokens,
                    cache_creation_tokens=event.cache_creation_tokens,
                )
                if self.agent.sdk_session_id is not None:
                    await store.set_sdk_session_id(
                        self.db, self.session_id, self.agent.sdk_session_id
                    )
                persisted = True
                break

            if self._stop_requested:
                stopped = True
                try:
                    await self.agent.interrupt()
                except Exception:
                    pass
                break

        if stopped and not persisted:
            msg_id = current_message_id or uuid4().hex
            synthetic = MessageComplete(
                session_id=self.session_id, message_id=msg_id, cost_usd=None
            )
            await self._emit_event(synthetic)
            await _persist_assistant_turn(
                self.db,
                session_id=self.session_id,
                message_id=msg_id,
                content="".join(buf),
                thinking="".join(thinking_buf) or None,
                tool_call_ids=tool_call_ids,
                cost_usd=None,
            )

    async def _emit_event(self, event: AgentEvent) -> None:
        """Fan an event out to every subscriber and append to the ring
        buffer. Subscriber queues are unbounded — if a subscriber isn't
        keeping up, the event is still delivered; only OS memory and
        the overall replay window bound this. Broken queues from dead
        subscribers are swept on the next emit."""
        payload = event.model_dump()
        env = _Envelope(self._next_seq, payload)
        self._next_seq += 1
        self._event_log.append(env)
        metrics.ws_events_sent.labels(type=event.type).inc()
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(env)
            except Exception:
                # Unbounded queue shouldn't raise, but if a subscriber
                # somehow misbehaves we drop it rather than block the
                # runner. The WS handler will notice its queue is dead
                # and clean up.
                self._subscribers.discard(queue)


async def _persist_assistant_turn(
    conn: aiosqlite.Connection,
    *,
    session_id: str,
    message_id: str,
    content: str,
    thinking: str | None,
    tool_call_ids: list[str],
    cost_usd: float | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_creation_tokens: int | None = None,
) -> None:
    await store.insert_message(
        conn,
        session_id=session_id,
        id=message_id,
        role="assistant",
        content=content,
        thinking=thinking,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )
    metrics.messages_persisted.labels(role="assistant").inc()
    await store.attach_tool_calls_to_message(
        conn, message_id=message_id, tool_call_ids=tool_call_ids
    )
    if cost_usd is not None:
        await store.add_session_cost(conn, session_id, cost_usd)
