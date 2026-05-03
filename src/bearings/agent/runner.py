# mypy: disable-error-code=explicit-any
"""Per-session runner — ring buffer + subscriber set + emit + idle reap.

Item 1.1 declared the type surface (``SessionRunner`` placeholder,
:class:`RunnerStatus`, :class:`RunnerFactory` Protocol). Item 1.2 fills
the body per arch §1.1.4: a per-session ring buffer of streamed
:class:`AgentEvent` items, a subscriber set the WS handler joins on
connect, and an :meth:`emit` method the agent-side glue (item 1.3+)
calls when the SDK produces text/thinking/tool-output deltas.

Three design decisions worth naming, all derived from arch + behavior:

1. **Ring buffer ⊆ subscriber fan-out.**
   Every emit appends to the ring buffer first, then fans out to every
   live subscriber's queue. The buffer is capped at
   :data:`bearings.config.constants.RING_BUFFER_MAX`; oldest entries
   drop on overflow. A new subscriber's :meth:`subscribe` call is
   atomic vs. concurrent ``emit`` (single-threaded asyncio: no awaits
   inside the critical section). Per
   ``docs/behavior/tool-output-streaming.md`` §"Reconnect / replay" the
   user observes: "any chunks the agent emitted while the client was
   away are replayed in order — the user sees the tool row's body fill
   in retroactively." That's a since-seq replay against this buffer.

2. **ToolOutputDelta chunking.**
   The behavior doc §"Multi-byte safety" reads: "the streaming chunks
   are split on safe boundaries … so a chunk never splits a multibyte
   UTF-8 codepoint." Python's ``str`` is codepoint-indexed already
   (slicing a ``str`` never splits within a codepoint), so the chunker
   uses ``str``-level slicing and is codepoint-safe by construction.
   :data:`bearings.config.constants.STREAM_MAX_DELTA_CHARS` caps any
   single :class:`ToolOutputDelta` event the wire carries; oversized
   deltas split into N events, each ≤ the cap.

3. **Hard-cap truncation.**
   Per behavior doc §"Very-long-output truncation rules" — "the marker
   always appears at the end of the persisted body, never in the
   middle." :data:`bearings.config.constants.STREAM_MAX_TOOL_OUTPUT_CHARS`
   caps total chars per ``tool_call_id``; once exceeded, the runner
   emits one final :class:`ToolOutputDelta` carrying
   :data:`bearings.config.constants.STREAM_TRUNCATION_MARKER_TEMPLATE`
   formatted with the elided count, then drops further deltas for that
   ``tool_call_id`` until a :class:`ToolCallEnd` resets the counter.

The streaming-source side (``agent/session.py:stream``) is item 1.3+
territory; item 1.2 leaves a clean ``emit``-from-anywhere surface so
the integration test can drive the runner directly without booting the
SDK subprocess. Per the auditor's 1.1 a1 note: ``session.py`` (406
lines) is left untouched in 1.2 because the streaming work is purely
additive in ``web/`` + this module — no growth in ``session.py``.

References:

* ``docs/architecture-v1.md`` §1.1.4 — runner ≤450 lines (the one
  documented over-cap exception); ring buffer + subscriber set live
  here.
* ``docs/architecture-v1.md`` §3.1, §3.2 — layer rules; runner does
  not import :mod:`bearings.web`.
* ``docs/architecture-v1.md`` §4.5 — :class:`RunnerFactory` Protocol.
* ``docs/architecture-v1.md`` §4.11 — :class:`RunnerStatus` shape.
* ``docs/behavior/tool-output-streaming.md`` — load-bearing for the
  emit / chunk / truncate / replay choices above.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from bearings.agent.events import (
    AgentEvent,
    MessageStart,
    RunnerStatusEvent,
    ToolCallEnd,
    ToolOutputDelta,
)
from bearings.agent.routing import RoutingDecision
from bearings.config.constants import (
    RING_BUFFER_MAX,
    STREAM_MAX_DELTA_CHARS,
    STREAM_MAX_TOOL_OUTPUT_CHARS,
    STREAM_TRUNCATION_MARKER_TEMPLATE,
)


def _monotonic_ns() -> int:
    """``time.monotonic_ns`` indirection so tests can patch it without
    monkey-patching the standard library. Production callers pay the
    same cost as a direct call (a single function dispatch)."""
    return time.monotonic_ns()


@dataclass(frozen=True)
class QueuedPrompt:
    """One queued user prompt awaiting the runner's worker loop.

    Per ``docs/behavior/prompt-endpoint.md`` §"What the user sees in the
    UI when they POST during an in-flight turn" — "If multiple prompts
    are POSTed back-to-back while a turn is running, they queue in
    arrival order. The agent works through the queue one turn at a
    time." The frozen dataclass carries the persisted message id (for
    correlation with the WS ``message_start`` frame the runner emits
    when it picks the prompt up) plus the user-facing content.
    """

    message_id: str
    content: str


# A buffered (seq, event) pair — sequence number for ``since_seq``
# replay, the event payload itself for fan-out. Aliased so the
# subscriber-side type stays readable at call sites.
type StreamEntry = tuple[int, AgentEvent]


@dataclass(frozen=True)
class RunnerStatus:
    """Arch §4.11 — frozen status snapshot for ``runner_status`` WS frames.

    The :data:`routing_decision` field is new in v1: v0.17.x's
    ``RunnerStatus`` had no routing surface, so the badge (spec §5)
    couldn't render on the first paint after a WS reconnect. Carrying
    the active decision here means the inspector can re-paint the
    badge before the next ``MessageComplete`` arrives.
    """

    is_running: bool
    is_awaiting_user: bool
    routing_decision: RoutingDecision | None


class SessionRunner:
    """Per-session runner: ring buffer + subscriber fan-out + emit.

    Construction takes the session id (load-bearing — every
    :class:`AgentEvent` carries it for client-side routing). The
    optional ``ring_buffer_max`` keyword exists for tests that want a
    smaller buffer to exercise overflow-drop without emitting 5000
    events.

    Lifecycle: the runner is created by
    :class:`bearings.web.runner_factory` (the FastAPI-aware concrete
    factory; cycle break per arch §3.2). The agent-side glue (item
    1.3+) calls :meth:`emit` to publish events; WS handlers call
    :meth:`subscribe` to attach. Idle-reap and worker-loop hooks are
    type-surface only at this stage — item 1.3+ wires the SDK
    subprocess to them.
    """

    def __init__(
        self,
        session_id: str,
        *,
        ring_buffer_max: int = RING_BUFFER_MAX,
    ) -> None:
        if not session_id:
            raise ValueError("SessionRunner.session_id must be non-empty")
        if ring_buffer_max <= 0:
            raise ValueError(f"SessionRunner.ring_buffer_max must be > 0 (got {ring_buffer_max})")
        self.session_id = session_id
        self._ring_buffer_max = ring_buffer_max
        self._buffer: deque[StreamEntry] = deque(maxlen=ring_buffer_max)
        self._next_seq: int = 1
        self._subscribers: set[asyncio.Queue[StreamEntry]] = set()
        # Per-tool-call cumulative chars-streamed counter. Reset on
        # ``ToolCallEnd``. Drives the hard-cap truncation per behavior
        # doc §"Very-long-output truncation rules".
        self._tool_output_chars: dict[str, int] = {}
        # Per-tool-call "already truncated" flag — once a truncation
        # marker has been emitted for a tool_call_id, further deltas
        # are silently dropped (the marker stays at the end of the
        # body per behavior doc).
        self._tool_truncated: set[str] = set()
        # Status snapshot fans out alongside events on subscribe so
        # the WS first frame can paint the badge before the next
        # ``MessageComplete`` arrives (arch §4.11).
        self._status: RunnerStatus = RunnerStatus(
            is_running=False,
            is_awaiting_user=False,
            routing_decision=None,
        )
        # FIFO queue of user prompts awaiting their turn. Per
        # ``docs/behavior/prompt-endpoint.md`` §"What the user sees in
        # the UI when they POST during an in-flight turn" — "queued in
        # arrival order. The agent works through the queue one turn at
        # a time." Item 1.7 lays the enqueue path; the worker-loop side
        # (item 1.3+) drains via :meth:`pop_next_prompt`.
        self._prompt_queue: deque[QueuedPrompt] = deque()
        # Edge-triggered signal the worker loop awaits when the prompt
        # queue is empty. ``enqueue_prompt`` sets it; ``pop_next_prompt``
        # clears it on the transition to empty. Exposed via
        # :attr:`new_prompt_event` so the worker can ``await`` it
        # instead of busy-polling.
        self._new_prompt_event: asyncio.Event = asyncio.Event()
        # Monotonic-clock timestamp the supervisor's reaper polls. Set
        # on construction, refreshed on every emit / enqueue / subscribe
        # so an active session never trips the idle-reap threshold.
        self._last_active_ns: int = _monotonic_ns()
        # Edge-triggered signal set by :meth:`request_stop`. The SDK
        # loop watches this during an in-flight turn and calls
        # :meth:`AgentSession.interrupt` when it fires, then clears it
        # so the next turn starts clean.
        self._stop_event: asyncio.Event = asyncio.Event()
        # Optional synchronous callback invoked on every
        # :meth:`set_status` call. Wired by the runner factory (item
        # 2.6) to fan runner-state changes to ``/ws/sessions``
        # subscribers. Kept as a plain Callable (not async) so
        # ``set_status`` stays synchronous — the factory wraps any
        # async side-effect in ``asyncio.get_event_loop().call_soon``.
        self._status_hook: Callable[[RunnerStatus], None] | None = None

    # -- properties --------------------------------------------------

    @property
    def last_seq(self) -> int:
        """The most recently assigned seq, or ``0`` before any emit."""
        return self._next_seq - 1

    @property
    def status(self) -> RunnerStatus:
        """Current status snapshot. Mutate via :meth:`set_status`."""
        return self._status

    @property
    def subscriber_count(self) -> int:
        """Number of currently-attached subscriber queues."""
        return len(self._subscribers)

    @property
    def ring_buffer_size(self) -> int:
        """Current ring buffer depth (≤ ``ring_buffer_max``)."""
        return len(self._buffer)

    @property
    def prompt_queue_depth(self) -> int:
        """Number of queued prompts awaiting the worker loop.

        Per ``docs/behavior/prompt-endpoint.md`` §"What the user sees in
        the UI when they POST during an in-flight turn" the user
        observes a ``queued`` badge while previous turns drain; the
        depth read here is the count behind the in-flight turn.
        """
        return len(self._prompt_queue)

    @property
    def new_prompt_event(self) -> asyncio.Event:
        """Edge-triggered signal the worker loop awaits when the prompt
        queue is empty.

        Set by :meth:`enqueue_prompt`; cleared by :meth:`pop_next_prompt`
        on the queue→empty transition. The worker reads
        ``await runner.new_prompt_event.wait()`` instead of polling.
        """
        return self._new_prompt_event

    @property
    def last_active_ns(self) -> int:
        """``time.monotonic_ns()`` timestamp of the most recent emit /
        enqueue / subscribe.

        The supervisor's idle reaper (item A5) polls this against
        :data:`bearings.config.constants.IDLE_REAP_THRESHOLD_S` to
        decide which sessions to tear down.
        """
        return self._last_active_ns

    @property
    def stop_event(self) -> asyncio.Event:
        """Edge-triggered signal the SDK loop watches during a turn.

        Set by :meth:`request_stop`; the SDK loop clears it at the
        start of each turn so repeated stop presses on back-to-back
        turns each get a fresh edge.
        """
        return self._stop_event

    def request_stop(self) -> None:
        """Signal the SDK loop to interrupt the current in-flight turn.

        Sets :attr:`stop_event`; the SDK loop's watcher coroutine
        detects the edge and calls :meth:`AgentSession.interrupt`,
        which forwards to :meth:`ClaudeSDKClient.interrupt`. Idempotent
        when no turn is running (the event stays set until the next
        turn clears it at the start).
        """
        self._stop_event.set()

    def enqueue_prompt(self, *, message_id: str, content: str) -> None:
        """Append ``content`` to the FIFO prompt queue.

        Per ``docs/behavior/prompt-endpoint.md`` §"What the user sees in
        the UI when they POST during an in-flight turn":

        * "The new prompt is queued behind the in-flight turn."
        * "If multiple prompts are POSTed back-to-back while a turn is
          running, they queue in arrival order."

        The runner does not start a turn here — that's the worker
        loop's job (item 1.3+ wiring). This method is intentionally
        synchronous + cheap so the prompt-endpoint route handler
        returns 202 in O(1) once persistence has succeeded.
        """
        if not message_id:
            raise ValueError("enqueue_prompt: message_id must be non-empty")
        if not content:
            raise ValueError("enqueue_prompt: content must be non-empty")
        self._prompt_queue.append(QueuedPrompt(message_id=message_id, content=content))
        self._new_prompt_event.set()
        self._last_active_ns = _monotonic_ns()

    def pop_next_prompt(self) -> QueuedPrompt | None:
        """Drain one prompt from the FIFO; ``None`` when empty.

        Used by the worker loop (item 1.3+) to pick the next turn's
        prompt. The behavior doc's "queue in arrival order" ordering
        is FIFO; :class:`collections.deque` ``popleft`` matches.
        """
        if not self._prompt_queue:
            return None
        item = self._prompt_queue.popleft()
        if not self._prompt_queue:
            # Queue drained — clear the gate so the worker awaits again
            # next time around. enqueue_prompt re-sets it on the next
            # arrival.
            self._new_prompt_event.clear()
        return item

    def peek_next_prompt(self) -> QueuedPrompt | None:
        """Return the next prompt without dequeuing; ``None`` when empty.

        Used by tests + the WS handler's "next-up" introspection
        surface; the worker loop drains via :meth:`pop_next_prompt`.
        """
        if not self._prompt_queue:
            return None
        return self._prompt_queue[0]

    # -- mutation ----------------------------------------------------

    def wire_status_hook(self, hook: Callable[[RunnerStatus], None]) -> None:
        """Register a synchronous callback invoked on every :meth:`set_status`
        call. Replaces any previously registered hook — only one hook
        is supported (the runner factory is the sole caller).

        The hook is called with the **new** status value after
        ``_status`` has been updated, so the hook observes a consistent
        snapshot. Injected by
        :class:`bearings.web.runner_factory.InProcessRunnerRegistry`
        to fan state changes to :class:`SessionsBroadcaster`.
        """
        self._status_hook = hook

    def set_status(self, status: RunnerStatus) -> None:
        """Replace the status snapshot and notify the optional hook.

        Future subscribers see the new snapshot. The optional
        ``_status_hook`` (wired by the runner factory for item 2.6)
        is called synchronously so the sessions-broadcast channel
        reflects the change without an extra event-loop tick.
        """
        self._status = status
        if self._status_hook is not None:
            self._status_hook(status)

    def get_status_event(self) -> RunnerStatusEvent:
        """Synthesise a :class:`RunnerStatusEvent` from current status.

        Walks the ring buffer in reverse to find the most recent
        :class:`MessageStart` when ``is_running`` is true — that
        gives the ``current_turn_id`` without requiring the SDK loop to
        track it separately. Returns ``None`` for ``current_turn_id``
        when the ring buffer holds no unfinished ``MessageStart`` (e.g.
        the buffer was evicted, or no turn has started yet).

        Called by :func:`bearings.web.streaming.serve_session_stream`
        after the replay drain so the client can reconcile
        ``streamingActive`` on reconnect.
        """
        current_turn_id: str | None = None
        if self._status.is_running:
            for _seq, event in reversed(list(self._buffer)):
                if isinstance(event, MessageStart):
                    current_turn_id = event.message_id
                    break
        return RunnerStatusEvent(
            session_id=self.session_id,
            streaming_active=self._status.is_running,
            current_turn_id=current_turn_id,
        )

    async def emit(self, event: AgentEvent) -> int:
        """Append ``event`` to the ring buffer and fan out to subscribers.

        Returns the seq the event was assigned (or, for chunked /
        truncated emissions, the seq of the last sub-event published).

        Behaviour by event type:

        * :class:`ToolOutputDelta` — chunked at
          :data:`bearings.config.constants.STREAM_MAX_DELTA_CHARS` and
          hard-capped at
          :data:`bearings.config.constants.STREAM_MAX_TOOL_OUTPUT_CHARS`
          per behavior doc.
        * :class:`ToolCallEnd` — resets the per-tool-call counter so a
          subsequent tool call with the same id (extremely rare; only
          possible if the SDK reuses an id) starts fresh.
        * Every other event — published as-is, one seq, no chunking.

        Single-threaded asyncio: no awaits inside the critical section,
        so this method is atomic w.r.t. concurrent :meth:`subscribe`
        calls in the same event loop.
        """
        if isinstance(event, ToolOutputDelta):
            return await self._emit_tool_output_delta(event)
        if isinstance(event, ToolCallEnd):
            self._tool_output_chars.pop(event.tool_call_id, None)
            self._tool_truncated.discard(event.tool_call_id)
            return self._publish(event)
        return self._publish(event)

    # -- subscribe / unsubscribe ------------------------------------

    def subscribe(
        self,
        *,
        since_seq: int = 0,
    ) -> tuple[list[StreamEntry], asyncio.Queue[StreamEntry]]:
        """Atomic snapshot + queue registration.

        Returns a pair: the list of buffered entries with seq >
        ``since_seq`` (oldest first), and a new :class:`asyncio.Queue`
        the subscriber drains for live events arriving after the
        snapshot. Caller is responsible for calling :meth:`unsubscribe`
        on disconnect; :class:`bearings.web.streaming.serve_session_stream`
        does this from a ``try/finally``.

        ``since_seq=0`` (the default) replays everything still in the
        ring buffer. A larger value resumes from a known point —
        per behavior doc §"Reconnect / replay" the user sees "any
        chunks the agent emitted while the client was away are
        replayed in order."

        Single-threaded asyncio: synchronous body (no awaits) means
        emit and subscribe never interleave. The replay snapshot is
        therefore exactly the ring buffer's state at the moment of
        the call, and the queue captures every event from that
        moment forward.
        """
        if since_seq < 0:
            raise ValueError(f"since_seq must be >= 0 (got {since_seq})")
        queue: asyncio.Queue[StreamEntry] = asyncio.Queue()
        replay: list[StreamEntry] = [(seq, event) for seq, event in self._buffer if seq > since_seq]
        self._subscribers.add(queue)
        self._last_active_ns = _monotonic_ns()
        return replay, queue

    def unsubscribe(self, queue: asyncio.Queue[StreamEntry]) -> None:
        """Remove ``queue`` from the subscriber set; idempotent."""
        self._subscribers.discard(queue)

    # -- internal helpers -------------------------------------------

    async def _emit_tool_output_delta(self, event: ToolOutputDelta) -> int:
        """Apply hard-cap truncation + chunking per behavior doc."""
        tool_call_id = event.tool_call_id
        # Already truncated — drop further deltas until ToolCallEnd.
        if tool_call_id in self._tool_truncated:
            return self.last_seq
        already = self._tool_output_chars.get(tool_call_id, 0)
        remaining = STREAM_MAX_TOOL_OUTPUT_CHARS - already
        if remaining <= 0:
            # Should not be reachable (we set the truncated flag the
            # moment we cross the cap below), but guard defensively.
            self._tool_truncated.add(tool_call_id)
            return self.last_seq
        delta = event.delta
        # Trim to the per-tool-call cap.
        if len(delta) > remaining:
            head = delta[:remaining]
            elided = len(delta) - remaining
            self._tool_truncated.add(tool_call_id)
            self._tool_output_chars[tool_call_id] = STREAM_MAX_TOOL_OUTPUT_CHARS
            self._publish_chunked_delta(
                tool_call_id=tool_call_id,
                session_id=event.session_id,
                payload=head,
            )
            marker = STREAM_TRUNCATION_MARKER_TEMPLATE.format(n=elided)
            return self._publish(
                ToolOutputDelta(
                    session_id=event.session_id,
                    tool_call_id=tool_call_id,
                    delta=marker,
                )
            )
        # Within the cap — chunk and publish.
        self._tool_output_chars[tool_call_id] = already + len(delta)
        last_seq = self._publish_chunked_delta(
            tool_call_id=tool_call_id,
            session_id=event.session_id,
            payload=delta,
        )
        return self.last_seq if last_seq is None else last_seq

    def _publish_chunked_delta(
        self,
        *,
        tool_call_id: str,
        session_id: str,
        payload: str,
    ) -> int | None:
        """Split ``payload`` into ≤ STREAM_MAX_DELTA_CHARS chunks and
        publish each as its own :class:`ToolOutputDelta`.

        Returns the seq of the last published chunk, or ``None`` if the
        payload was empty (no event published).
        """
        if not payload:
            return None
        last: int | None = None
        for chunk in _chunk(payload, STREAM_MAX_DELTA_CHARS):
            last = self._publish(
                ToolOutputDelta(
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    delta=chunk,
                )
            )
        return last

    def _publish(self, event: AgentEvent) -> int:
        """Assign a seq, append to ring buffer, fan out to subscribers."""
        seq = self._next_seq
        self._next_seq += 1
        entry: StreamEntry = (seq, event)
        self._buffer.append(entry)
        self._last_active_ns = _monotonic_ns()
        # ``put_nowait`` is correct: the queues are unbounded
        # (default-constructed in :meth:`subscribe`) so the call never
        # raises :class:`asyncio.QueueFull`. A future bound on the
        # subscriber queue would change this contract; the auditor on
        # any such change must revisit backpressure semantics.
        for queue in self._subscribers:
            queue.put_nowait(entry)
        return seq


def _chunk(payload: str, size: int) -> Iterable[str]:
    """Yield ``payload`` in ``size``-character slices.

    Python ``str`` indexing is codepoint-safe, so this never splits a
    multibyte UTF-8 codepoint mid-sequence (per behavior doc
    §"Multi-byte safety"). Bytes-level boundary safety is the SDK's
    responsibility upstream; once we have a Python ``str``, codepoint
    safety is guaranteed by the language.
    """
    if size <= 0:
        raise ValueError(f"_chunk size must be > 0 (got {size})")
    for offset in range(0, len(payload), size):
        yield payload[offset : offset + size]


class RunnerFactory(Protocol):
    """Arch §4.5 — async factory that materialises a runner for ``session_id``.

    The concrete binding lives in ``web/runner_factory.py``
    (FastAPI-aware: reads ``app.state``); the ``agent`` layer takes
    this Protocol as a constructor argument so it never imports
    ``bearings.web``. Per arch §3.1 rule #4 there are no lazy
    cross-layer imports anywhere in the ``agent`` package; the cycle
    is broken by injection at app construction, not by deferred
    binding.
    """

    async def __call__(self, session_id: str) -> SessionRunner: ...


@dataclass(frozen=True)
class SessionSetup:
    """Per-session bootstrap payload — what the worker-loop supervisor
    needs to spawn :func:`bearings.agent.sdk_loop.run_session_loop`.

    Lives in the ``agent`` layer (not ``web``) so the runner-factory
    binding can import it without violating arch §3.1 layer rules.
    Production callers materialise these via
    :func:`bearings.agent.session_bootstrap.build_session_setup`;
    tests construct synthetic instances directly.

    The ``session``, ``options``, and ``approval_broker`` fields are
    typed as ``Any`` to avoid an upward import from this module to
    ``agent.session`` / ``agent.options`` / ``agent.approval`` (per
    arch §3.1 #2 — ``runner.py`` is the layer floor; importing
    higher-up agent modules would introduce a sibling-cycle the AST
    cycle-prevention guard rejects). Concrete consumers
    (sdk_loop.py + the runner-factory supervisor + the approvals
    REST/WS routes) read these fields under their own typed
    wrappers.

    :attr:`approval_broker` is ``None`` before A4 wires the
    :class:`ApprovalBroker`; populated for sessions whose options
    enable can_use_tool. The route layer pulls it off ``app.state``
    via the registry to resolve REST/WS approvals.
    """

    session: Any
    options: Any
    approval_broker: Any = None


# Async callable: takes a session id + the freshly-materialised
# :class:`SessionRunner`, returns the per-session :class:`SessionSetup`,
# or ``None`` when the session row is absent or unsupported (e.g.
# checklist sessions, which have their own driver). The runner is
# threaded so the bootstrap can construct per-session collaborators
# that need ``runner.emit`` (e.g. :class:`bearings.agent.approval.ApprovalBroker`).
# Lives in the ``agent`` layer so the web-layer registry binding can
# read it without cross-layer imports.
SessionSetupFn = Callable[[str, "SessionRunner"], Awaitable[SessionSetup | None]]


__all__ = [
    "QueuedPrompt",
    "RunnerFactory",
    "RunnerStatus",
    "SessionRunner",
    "SessionSetup",
    "SessionSetupFn",
    "StreamEntry",
]
