"""Per-session runner that owns agent execution independently of any
WebSocket connection.

Why: in v0.2.x the agent loop lived inside the WS handler, so closing
the socket (navigate-away, session switch, tab close) killed the
in-flight stream. Sessions are meant to be independent — you should be
able to kick off work in one and walk away. The runner owns the
`AgentSession`, the streaming task, and a ring buffer of recent events.
WebSocket handlers become thin subscribers that can come and go without
disturbing execution. Completed messages/tool calls are already
persisted to SQLite (see `turn_executor.execute_turn`), so "closed the
tab, came back an hour later" also works across server restarts.

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

Module layout: this file owns the `SessionRunner` class — public API,
subscriber set, ring buffer, approval forwarding, reaper hook. Worker-
loop and per-turn execution live in `turn_executor.py`. Wire types
(_Envelope, _Replay, _Submit, _Shutdown) and tunables (RING_MAX,
SUBSCRIBER_QUEUE_MAX, TOOL_PROGRESS_INTERVAL_S) live in `runner_types`
and are re-exported here for backwards compatibility (tests + ws_agent
import them from this module). Ticker management is delegated to
`progress_ticker.ProgressTickerManager`. Assistant-turn persistence is
delegated to `persist.persist_assistant_turn`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

import aiosqlite
from claude_agent_sdk import ClaudeSDKError

from bearings.agent.approval_broker import ApprovalBroker
from bearings.agent.event_fanout import emit_ephemeral, emit_event
from bearings.agent.events import AgentEvent
from bearings.agent.progress_ticker import ProgressTickerManager
from bearings.agent.runner_types import (
    _SHUTDOWN,
    RING_MAX,
    SUBSCRIBER_QUEUE_MAX,
    TOOL_PROGRESS_INTERVAL_S,
    RunnerStatus,
    _Envelope,
    _Replay,
    _Shutdown,
    _Submit,
)
from bearings.agent.session import AgentSession
from bearings.agent.sessions_broker import SessionsBroker, publish_runner_state
from bearings.agent.tool_output_coalescer import ToolOutputCoalescer
from bearings.config import ArtifactsCfg
from bearings.db import store

log = logging.getLogger(__name__)

# Re-exported for backwards compatibility — tests, `ws_agent`, and
# downstream callers import these names from `bearings.agent.runner`.
# Keeping the symbols rebound at module level (rather than only via
# `from ... import ...`) makes them visible to both static type
# checkers and runtime `getattr` callers (sessions broker, monkey-
# patched test fixtures).
__all__ = [
    "RING_MAX",
    "SUBSCRIBER_QUEUE_MAX",
    "TOOL_PROGRESS_INTERVAL_S",
    "RunnerStatus",
    "SessionRunner",
    "_Envelope",
    "_Replay",
    "_SHUTDOWN",
    "_Shutdown",
    "_Submit",
]


def _get_progress_interval() -> float:
    """Module-level lookup of `TOOL_PROGRESS_INTERVAL_S`.

    Used as the `interval_getter` callable for every runner's progress
    manager. Reading via this function (rather than capturing the
    constant at construction) keeps the test contract:
    `monkeypatch.setattr(runner_mod, "TOOL_PROGRESS_INTERVAL_S", X)`
    is observed on the very next sleep, because every loop iteration
    re-reads the module global from inside this function."""
    return TOOL_PROGRESS_INTERVAL_S


class SessionRunner:
    """Owns one session's agent execution. Long-lived; decoupled from
    WebSocket connections so sessions keep running when the UI walks
    away."""

    def __init__(
        self,
        session_id: str,
        agent: AgentSession,
        db: aiosqlite.Connection,
        *,
        sessions_broker: SessionsBroker | None = None,
        artifacts_cfg: ArtifactsCfg | None = None,
    ) -> None:
        self.session_id = session_id
        self.agent = agent
        self.db = db
        # Server-wide sessions pubsub. `None` is valid — tests that
        # don't care about the broadcast channel (most runner tests)
        # pass it through. The publish helpers no-op on None so the
        # turn loop stays oblivious.
        self._sessions_broker = sessions_broker
        # Phase-1 File Display: settings sub-block consumed by the
        # auto-register hook in `agent/_artifacts.py`. `None` disables
        # auto-register cleanly (every test that doesn't care about
        # artifacts skips the wiring), keeping the new feature dormant
        # in any harness that constructs a runner without app settings.
        self._artifacts_cfg = artifacts_cfg
        self._prompts: asyncio.Queue[str | _Submit | _Replay | _Shutdown] = asyncio.Queue()
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
        #
        # The `mode_getter` closure reads the agent's live
        # `permission_mode` so the broker can fast-path auto-allow when
        # the mode is `bypassPermissions` (or `acceptEdits` for edit
        # tools). Without this, a turn under bypassPermissions still
        # parks the SDK callback on a Future — which is what made the
        # 2026-04-24 fae8f1a8 Settings-UX run hang for 4 hours on a
        # single Edit tool call. Closure (not stored value) so a
        # mid-turn `set_permission_mode` flip is observed on the very
        # next `can_use_tool` invocation.
        self._approval = ApprovalBroker(
            session_id,
            self._emit_event,
            mode_getter=lambda: self.agent.permission_mode,
        )
        # Count of `can_use_tool` calls currently parked on a user
        # decision. Bumped on entry to the wrapped callback (see
        # `can_use_tool` property) and decremented in the finally.
        # A non-zero count drives `is_awaiting_user` → sidebar red
        # flash. Counter (not bool) because the SDK can stack parks
        # — e.g. an approval prompt immediately followed by an
        # AskUserQuestion in the same turn; both should keep the
        # indicator lit until ALL of them resolve.
        self._awaiting_count: int = 0
        # Coalesces `ToolOutputDelta` → `append_tool_output` writes
        # per `tool_call_id`. Owned by this runner's worker task; the
        # runner just forwards `buffer` / `drop` / `flush_all` and
        # stays oblivious to flush cadence and DB write plumbing.
        self._coalescer = ToolOutputCoalescer(db, session_id)
        # Per-tool-call keepalive ticker manager. Started from the
        # `ToolCallStart` arm of `execute_turn`, cancelled from the
        # `ToolCallEnd` arm and from the turn's `finally` block so an
        # interrupted or exception-exited turn doesn't strand timers.
        # Cadence read via `_get_progress_interval` so test
        # monkeypatching of `TOOL_PROGRESS_INTERVAL_S` flows through.
        self._progress = ProgressTickerManager(
            session_id,
            self._emit_ephemeral,
            _get_progress_interval,
        )
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

    # ---- backwards-compat ticker accessors ------------------------
    #
    # `test_runner_tool_progress.py` reads `runner._progress_tickers`
    # and `runner._progress_started` directly. Keep that surface as
    # property forwards onto the manager so the tests keep passing
    # without churn.

    @property
    def _progress_tickers(self) -> dict[str, asyncio.Task[None]]:
        return self._progress.tickers

    @property
    def _progress_started(self) -> dict[str, float]:
        return self._progress.started

    def _start_progress_ticker(self, tool_call_id: str) -> None:
        self._progress.start(tool_call_id)

    def _stop_progress_ticker(self, tool_call_id: str) -> None:
        self._progress.stop(tool_call_id)

    async def _stop_all_progress_tickers(self) -> None:
        await self._progress.stop_all()

    # ---- lifecycle -------------------------------------------------

    def start(self) -> None:
        """Spawn the worker task. Idempotent — safe to call twice."""
        if self._worker is None or self._worker.done():
            # Late import to break the runner ↔ turn_executor cycle.
            from bearings.agent.turn_executor import run_worker

            self._worker = asyncio.create_task(run_worker(self), name=f"runner:{self.session_id}")

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
        except (ClaudeSDKError, OSError):
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

    @property
    def is_awaiting_user(self) -> bool:
        """True iff the runner is currently parked inside a
        `can_use_tool` callback, waiting for a user decision. Covers
        both the native tool-use permission path and the
        AskUserQuestion flow, because both ride the approval broker
        and flow through the wrapped `can_use_tool` below. Drives the
        sidebar's red-flashing "look at this now" indicator — distinct
        from `is_running`, which stays true across the whole turn
        including the park itself.
        """
        return self._awaiting_count > 0

    async def submit_prompt(
        self,
        prompt: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        """Queue a prompt for this session. Prompts are processed
        sequentially — if a turn is already in flight, this one waits.

        `attachments` is the sidecar list from the composer's
        `[File N]` tokens (see `agent/_attachments.py`); None or empty
        means a plain text prompt and is queued as a raw string so
        attachment-free submits keep the historical queue shape. With
        attachments, the prompt is wrapped in `_Submit` so the worker
        can persist the sidecar and substitute paths for the SDK.

        If the session has `max_budget_usd` set and `total_cost_usd`
        has already met or exceeded it, the prompt is refused with a
        wire `ErrorEvent` instead of being queued. The SDK's
        `max_budget_usd` advisory only fires *during* a turn once
        cost accrues, so without this pre-check a user who's past
        their cap can kick off another turn that runs to completion
        before the advisory bites. Fail-closed at the gate."""
        from bearings.agent.events import ErrorEvent

        row = await store.get_session(self.db, self.session_id)
        if row is not None:
            cap = row.get("max_budget_usd")
            spent = row.get("total_cost_usd") or 0.0
            if cap is not None and float(spent) >= float(cap):
                await self._emit_event(
                    ErrorEvent(
                        session_id=self.session_id,
                        message=(
                            f"Budget cap reached: ${float(spent):.2f} of "
                            f"${float(cap):.2f}. Raise the cap in session "
                            "settings or fork to a new session to continue."
                        ),
                    )
                )
                return
        if attachments:
            await self._prompts.put(_Submit(prompt, attachments))
        else:
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
        except (ClaudeSDKError, OSError):
            pass

    # ---- tool-use approval ----------------------------------------

    @property
    def can_use_tool(self) -> Any:
        """Callback bound onto `AgentSession.can_use_tool` by
        `ws_agent._build_runner`. Forwarding property so callers don't
        need to know a broker exists; the runner remains the single
        public surface the WS layer talks to.

        Wraps the broker's callback so each entry/exit broadcasts an
        updated `runner_state` frame to every connected sidebar. The
        sidebar reads `awaiting_user` off that frame and flips the
        session's indicator to the red-flashing "needs attention"
        state for the duration of the park. The broker itself remains
        ignorant of the broadcast — this keeps the approval protocol
        transport-agnostic and avoids a second code path to coordinate
        with the AskUserQuestion work parked in approval_broker.py."""
        broker_cb = self._approval.can_use_tool

        async def wrapped(tool_name: Any, tool_input: Any, context: Any) -> Any:
            self._awaiting_count += 1
            self._publish_runner_state()
            try:
                return await broker_cb(tool_name, tool_input, context)
            finally:
                # Decrement THEN broadcast so the published frame
                # reflects the post-resolve count. A stacked approval
                # + AskUserQuestion keeps the indicator lit until the
                # last one resolves — the counter's whole point.
                self._awaiting_count -= 1
                self._publish_runner_state()

        return wrapped

    def _publish_runner_state(self) -> None:
        """Broadcast this runner's current `(is_running, is_awaiting_user)`
        tuple on the sessions broker. No-op when no broker is wired
        (test runners). Idempotent — a frame identical to the last one
        is harmless; subscribers just re-apply the same state."""
        publish_runner_state(
            self._sessions_broker,
            self.session_id,
            is_running=self.is_running,
            is_awaiting_user=self.is_awaiting_user,
        )

    async def resolve_approval(
        self,
        request_id: str,
        decision: str,
        reason: str | None = None,
        updated_input: dict[str, object] | None = None,
    ) -> None:
        """WS → broker forwarder. Kept on the runner so the WS handler
        has one object to hold (runner), not two (runner + broker).
        `updated_input` is the UI-collected override the SDK will pass
        to the tool under an allow decision — see `ApprovalBroker.resolve`
        for the AskUserQuestion motivation."""
        await self._approval.resolve(request_id, decision, reason, updated_input)

    async def subscribe(
        self, since_seq: int = 0
    ) -> tuple[asyncio.Queue[_Envelope], list[_Envelope]]:
        """Register a subscriber queue and return buffered events with
        seq > since_seq for replay. Reconnecting clients pass the last
        seq they saw; fresh clients pass 0 to replay the whole window.

        Queue is bounded by `SUBSCRIBER_QUEUE_MAX` — see `_emit_event`
        for the back-pressure / eviction policy."""
        queue: asyncio.Queue[_Envelope] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAX)
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

    # ---- event fan-out --------------------------------------------
    #
    # Thin forwarders onto `event_fanout.emit_event` / `emit_ephemeral`.
    # Kept as methods (rather than swapping every `self._emit_event(...)`
    # call site to the free function) so the broker, ticker manager,
    # and turn executor can treat the runner as a callback target.

    async def _emit_event(self, event: AgentEvent) -> None:
        await emit_event(self, event)

    async def _emit_ephemeral(self, event: AgentEvent) -> None:
        await emit_ephemeral(self, event)


# Re-export for tests that historically reach for `runner._persist_assistant_turn`.
# The active call sites moved to `bearings.agent.persist.persist_assistant_turn`;
# this alias keeps any external introspection working.
from bearings.agent.persist import (  # noqa: E402, F401
    persist_assistant_turn as _persist_assistant_turn,
)
