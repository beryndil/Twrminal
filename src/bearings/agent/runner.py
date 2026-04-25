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
import orjson

from bearings import metrics
from bearings.agent._attachments import prune_and_serialize, substitute_tokens
from bearings.agent.approval_broker import ApprovalBroker
from bearings.agent.events import (
    AgentEvent,
    ContextUsage,
    ErrorEvent,
    MessageComplete,
    MessageStart,
    Thinking,
    TodoWriteUpdate,
    Token,
    ToolCallEnd,
    ToolCallStart,
    ToolOutputDelta,
    ToolProgress,
    TurnReplayed,
)
from bearings.agent.session import AgentSession
from bearings.agent.sessions_broker import (
    SessionsBroker,
    publish_runner_state,
    publish_session_upsert,
)
from bearings.agent.tool_output_coalescer import ToolOutputCoalescer
from bearings.db import store

log = logging.getLogger(__name__)

# How many recent events to keep for reconnect replay. Five thousand
# comfortably covers a long multi-tool turn where each token is a
# separate event; old entries roll off the front. If a client is away
# longer than this buffer's window, it misses intermediate tokens but
# still catches the final `message_complete` (and the completed
# assistant message is in the DB either way).
RING_MAX = 5000

# Cadence for `ToolProgress` keepalive events emitted while a tool call
# is still running. Covers the "SDK surfaces nothing for tens of
# seconds during a Task/Agent sub-agent" class of silence that would
# otherwise read as a dead spinner. At 3s per tick per in-flight tool,
# a turn with up to ~3 concurrent tools stays under 1 msg/sec fan-out
# — comfortably below anything the WS + reducer have to worry about.
# Events are fan-out only (never persisted to the ring buffer), so
# this cadence does not eat the 5000-entry replay window either.
TOOL_PROGRESS_INTERVAL_S = 3.0


# Sentinel queued into `_prompts` by `shutdown()` so the worker exits
# its blocking `get()` and winds down cleanly.
class _Shutdown:
    pass


_SHUTDOWN = _Shutdown()


class _Replay:
    """Queue marker for a prompt that was recovered from a prior
    runner's unfinished turn. The difference from a plain string: the
    user row is already in the `messages` table — `_execute_turn` must
    NOT insert it a second time or history will show the user's prompt
    twice after a restart-mid-turn event."""

    __slots__ = ("prompt", "attachments")

    def __init__(self, prompt: str, attachments: list[dict[str, Any]] | None) -> None:
        self.prompt = prompt
        # Parsed list (or None) — the replay row carries the same
        # token→path mapping so `_execute_turn` can re-substitute
        # exactly what the SDK saw on the original interrupted turn.
        self.attachments = attachments


class _Submit:
    """Queue marker for a freshly submitted prompt carrying terminal-
    style `[File N]` attachments. Plain strings still work for
    attachment-free prompts — the worker treats them identically — but
    once a prompt has attachments we need to ride them through the
    queue so `_execute_turn` can both persist the sidecar and build the
    substituted SDK text. Kept separate from `_Replay` so the replay
    path's "don't re-persist user row" rule stays untangled from
    attachment handling."""

    __slots__ = ("prompt", "attachments")

    def __init__(self, prompt: str, attachments: list[dict[str, Any]]) -> None:
        self.prompt = prompt
        self.attachments = attachments


RunnerStatus = Literal["idle", "running"]


class _Envelope:
    """Event plus its monotonically-increasing sequence number.

    Subscribers receive envelopes so they can update their own
    `lastSeq` cursor for future reconnects. Using a small class rather
    than a tuple to keep attribute access obvious at call sites.

    `wire` holds the pre-encoded text-frame JSON (payload merged with
    `_seq`). Encoding the frame once at emit time instead of per
    subscriber avoids an `orjson.dumps(...).decode()` hop on every
    WebSocket send — non-trivial on tool-heavy turns where a single
    event fans out to N tabs plus buffered replay. `payload` is still
    exposed for tests and for the approval/session-broker code paths
    that peek at event types without serializing.
    """

    __slots__ = ("seq", "payload", "wire")

    def __init__(self, seq: int, payload: dict[str, Any]) -> None:
        self.seq = seq
        self.payload = payload
        # Merge `_seq` into the frame once. Subscribers + replay use
        # `env.wire` directly; see `ws_agent._forward_events`.
        self.wire = orjson.dumps({**payload, "_seq": seq}).decode()


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
    ) -> None:
        self.session_id = session_id
        self.agent = agent
        self.db = db
        # Server-wide sessions pubsub. `None` is valid — tests that
        # don't care about the broadcast channel (most runner tests)
        # pass it through. The publish helpers no-op on None so the
        # turn loop stays oblivious.
        self._sessions_broker = sessions_broker
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
        self._approval = ApprovalBroker(session_id, self._emit_event)
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
        # Per-tool-call keepalive tickers. One task per in-flight
        # tool call; each fires a `ToolProgress` event every
        # `TOOL_PROGRESS_INTERVAL_S` for fan-out only (no ring buffer
        # append, no DB write). Started from the `ToolCallStart` arm
        # of `_execute_turn`, cancelled from the `ToolCallEnd` arm and
        # from the turn's `finally` block so an interrupted or
        # exception-exited turn doesn't strand timers. `_progress_started`
        # records the monotonic start so the event's `elapsed_ms` is
        # self-contained — the UI doesn't need the original start
        # timestamp to render the readout. Managed only by the worker
        # task (tickers are spawned on the runner's loop); no locking.
        self._progress_tickers: dict[str, asyncio.Task[None]] = {}
        self._progress_started: dict[str, float] = {}
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
        # TEMP 2026-04-23: session-switch interrupt probe — see
        # bearings.agent._interrupt_probe docstring.
        from bearings.agent._interrupt_probe import probe

        probe(
            "runner.shutdown",
            self.session_id,
            status=self._status,
            subscribers=len(self._subscribers),
        )
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
        # TEMP 2026-04-23: session-switch interrupt probe — see
        # bearings.agent._interrupt_probe docstring.
        from bearings.agent._interrupt_probe import probe

        probe(
            "runner.request_stop",
            self.session_id,
            status=self._status,
            subscribers=len(self._subscribers),
        )
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

    async def _maybe_replay_orphaned_prompt(self) -> None:
        """If the DB shows a user message with no assistant reply and
        no prior replay attempt, re-queue it as this runner's first
        turn and emit a `TurnReplayed` event for any subscriber to
        notice.

        The failure mode this recovers from: the service was stopped
        (SIGTERM, OOM, crash) after persisting the user's prompt but
        before the SDK produced an assistant reply. Without this hook
        the orphaned prompt sits in history forever with no follow-up
        unless the user types it again — and the original ask loses
        its wall-clock urgency ("I came back and nothing happened").

        Best-effort: any DB failure is logged and swallowed. A broken
        replay scan must never block a fresh runner from accepting new
        user prompts.
        """
        try:
            orphan = await store.find_replayable_prompt(self.db, self.session_id)
        except Exception:
            log.exception(
                "runner %s: replay scan failed; continuing without replay",
                self.session_id,
            )
            return
        if orphan is None:
            return
        try:
            marked = await store.mark_replay_attempted(self.db, orphan["id"])
        except Exception:
            log.exception(
                "runner %s: replay mark failed; skipping replay to avoid loop",
                self.session_id,
            )
            return
        if not marked:
            # Row vanished or another actor marked it first — treat as
            # "handled elsewhere" and do nothing.
            return
        await self._emit_event(TurnReplayed(session_id=self.session_id, message_id=orphan["id"]))
        # `attachments` is a JSON string (or None) from the DB column;
        # parse eagerly so the worker can feed it straight into the
        # substitute_tokens helper without a second decode path.
        raw_attachments = orphan.get("attachments")
        parsed_attachments: list[dict[str, Any]] | None = None
        if raw_attachments:
            try:
                parsed = json.loads(raw_attachments)
                if isinstance(parsed, list):
                    parsed_attachments = parsed
            except (json.JSONDecodeError, TypeError):
                # A malformed JSON row is a surprise but not a
                # show-stopper — fall through and replay without
                # substitution (the text still carries `[File N]`
                # tokens, which Claude will just see as literal).
                log.warning(
                    "runner %s: orphan %s has unparseable attachments JSON",
                    self.session_id,
                    orphan["id"],
                )
        await self._prompts.put(_Replay(orphan["content"], parsed_attachments))
        log.info(
            "runner %s: replayed orphaned user prompt id=%s",
            self.session_id,
            orphan["id"],
        )

    async def _run_forever(self) -> None:
        # Recover orphaned prompts from prior-crash / prior-restart.
        # Must run before the first `get()` so the replayed prompt is
        # the first turn this worker executes — any real user prompt
        # submitted after reconnect naturally queues behind it.
        await self._maybe_replay_orphaned_prompt()
        while True:
            item = await self._prompts.get()
            if isinstance(item, _Shutdown):
                return
            attachments: list[dict[str, Any]] | None
            if isinstance(item, _Replay):
                prompt = item.prompt
                attachments = item.attachments
                persist_user = False
            elif isinstance(item, _Submit):
                prompt = item.prompt
                attachments = item.attachments
                persist_user = True
            else:
                prompt = item
                attachments = None
                persist_user = True
            self._status = "running"
            # A turn is live — not quiet regardless of subscriber count.
            # Clear here rather than spread the condition through every
            # status mutation site.
            self._quiet_since = None
            self._stop_requested = False
            # Bump updated_at the moment the runner starts work so the
            # sidebar floats this session to the top immediately — not
            # after MessageComplete lands. Covers the replay-path too:
            # `_Replay` skips `insert_message`, so without this touch
            # the sort wouldn't move on a resumed orphan prompt. DB
            # hiccup here must not abort the turn — swallow.
            try:
                await store.touch_session(self.db, self.session_id)
            except Exception:
                log.exception(
                    "runner %s: touch_session on turn-start failed",
                    self.session_id,
                )
            # Phase-2 broadcast: every connected sidebar sees the
            # updated_at bump + the running badge without waiting for
            # the poll tick. Publish AFTER touch_session so the upsert
            # payload carries the bumped timestamp.
            await publish_session_upsert(self._sessions_broker, self.db, self.session_id)
            self._publish_runner_state()
            turn_ok = False
            try:
                await self._execute_turn(prompt, persist_user=persist_user, attachments=attachments)
                turn_ok = True
            except Exception as exc:
                log.exception("runner %s: turn failed", self.session_id)
                await self._emit_event(ErrorEvent(session_id=self.session_id, message=str(exc)))
                # Latch the red-flashing error state onto the session
                # row so the sidebar surfaces the crash without the
                # user having to open the conversation to find it.
                # Cleared on the next successful MessageComplete by
                # the `_execute_turn` path below, or implicitly by a
                # subsequent successful turn in this same loop. Swallow
                # DB errors — missing the latch just means the sidebar
                # indicator doesn't light, which is a worse UX than
                # the current (non-existent) state but not a data loss.
                try:
                    await store.set_session_error_pending(self.db, self.session_id, pending=True)
                except Exception:
                    log.exception(
                        "runner %s: failed to latch error_pending",
                        self.session_id,
                    )
            finally:
                self._status = "idle"
                # If nobody's watching, start the reaper clock. A
                # connected subscriber keeps the clock off until it
                # unsubscribes.
                if not self._subscribers:
                    self._quiet_since = time.monotonic()
                # A clean turn clears any stale error_pending latched
                # by an earlier crash on this session — the red dot
                # disappears the moment the user's retry lands a
                # successful reply. Kept inside the finally so an
                # exception-free turn still gets the clear before we
                # broadcast the idle upsert.
                if turn_ok:
                    try:
                        await store.set_session_error_pending(
                            self.db, self.session_id, pending=False
                        )
                    except Exception:
                        log.exception(
                            "runner %s: failed to clear error_pending",
                            self.session_id,
                        )
                # Broadcast idle so the sidebar clears the running ping
                # and picks up any cost / message_count / completed
                # bumps (plus the error_pending transition above) from
                # _persist_assistant_turn in one upsert.
                await publish_session_upsert(self._sessions_broker, self.db, self.session_id)
                self._publish_runner_state()

    async def _execute_turn(
        self,
        prompt: str,
        *,
        persist_user: bool = True,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:  # noqa: C901
        """Run one agent turn end-to-end. Mirrors the pre-runner
        ws_agent loop: persist user message, stream agent events,
        persist assistant turn + tool calls as they complete. Events
        are fanned out to subscribers via `_emit_event`.

        `persist_user=False` is used by the runner-boot replay path
        when recovering an orphaned prompt: the user row is already in
        `messages` from the original (interrupted) turn, so inserting
        again would duplicate history.

        `attachments` carries the composer's `[File N]` sidecar (parsed
        list or None). When present, the SDK receives the same prompt
        with tokens replaced by absolute paths; the persisted user row
        keeps the tokenised form so the transcript renders chips on
        reload. Replay path sends the same list through so the
        recovered turn hits the SDK identically to its original.
        """
        pruned_attachments, attachments_json = prune_and_serialize(prompt, attachments or [])
        # The SDK only ever sees the substituted text; we don't
        # substitute in-place on `prompt` because we want to persist
        # the tokenised form (and we need `prompt` unchanged for the
        # replay-row content column, which is already tokenised).
        agent_prompt = substitute_tokens(prompt, pruned_attachments)
        if persist_user:
            await store.insert_message(
                self.db,
                session_id=self.session_id,
                role="user",
                content=prompt,
                attachments=attachments_json,
            )
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

        try:
            async for event in self.agent.stream(agent_prompt):
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
                    # Start the keepalive ticker for this call. See
                    # `_progress_ticker` for the fan-out contract; the
                    # ticker is torn down in the `ToolCallEnd` arm or
                    # by `_stop_all_progress_tickers` on turn teardown.
                    self._start_progress_ticker(event.tool_call_id)
                    # TodoWrite is a first-class UI signal, not just a
                    # generic tool call: fire a higher-level
                    # `TodoWriteUpdate` so the frontend sticky widget
                    # updates without hand-parsing `tool_calls[*].input`.
                    # The raw `ToolCallStart` already went out above, so
                    # Inspector / audit paths keep seeing it verbatim.
                    if event.name == "TodoWrite":
                        await self._emit_todo_write_update(event.input)
                elif isinstance(event, ToolOutputDelta):
                    # Buffer the chunk instead of writing immediately.
                    # The coalescer flushes on count/time thresholds so
                    # a chatty tool doesn't cost one UPDATE + commit
                    # per delta. History endpoint + reconnecting
                    # WebSocket see cumulative output within one flush
                    # window of the live stream. `finish_tool_call`
                    # later overwrites with the canonical final string,
                    # so a dropped flush can't leave a permanent gap.
                    await self._coalescer.buffer(event.tool_call_id, event.delta)
                elif isinstance(event, ToolCallEnd):
                    # Stop the keepalive ticker first so a stray tick
                    # can't race the canonical end frame onto the wire.
                    self._stop_progress_ticker(event.tool_call_id)
                    # Drop any buffered deltas before writing the
                    # canonical output — `finish_tool_call` fully
                    # overwrites `output` so the buffered chunks
                    # would be clobbered anyway. Doing it in this
                    # order also prevents a late timer from racing
                    # past the canonical write.
                    self._coalescer.drop(event.tool_call_id)
                    await store.finish_tool_call(
                        self.db,
                        tool_call_id=event.tool_call_id,
                        output=event.output,
                        error=event.error,
                    )
                    metrics.tool_calls_finished.labels(ok=str(event.ok).lower()).inc()
                elif isinstance(event, ContextUsage):
                    # Persist the latest snapshot on the session row
                    # so a fresh page load / reconnect has a number
                    # to paint before the next turn's live event
                    # arrives. Failure here must not drop the event
                    # for live subscribers — the fan-out to
                    # `_emit_event` already happened at the top of
                    # the loop. Swallow DB errors quietly.
                    try:
                        await store.set_session_context_usage(
                            self.db,
                            self.session_id,
                            pct=event.percentage,
                            tokens=event.total_tokens,
                            max_tokens=event.max_tokens,
                        )
                    except Exception:
                        log.exception(
                            "runner %s: failed to persist context usage",
                            self.session_id,
                        )
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
        finally:
            # Flush any buffered tool-output deltas on every exit
            # path (normal completion, stop-requested break, or an
            # exception bubbling out of the stream). If a `ToolCallEnd`
            # arrives later — e.g. after a reconnecting turn — the
            # canonical output still overwrites; this just keeps
            # mid-stream progress visible for the interrupted case.
            await self._coalescer.flush_all()
            # Cancel any in-flight progress tickers. Normal completion
            # cancels each one in the `ToolCallEnd` arm; this guards
            # the stop / exception paths where tools were still
            # running when the turn exited.
            await self._stop_all_progress_tickers()

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

    # ---- tool-progress keepalive ----------------------------------

    def _start_progress_ticker(self, tool_call_id: str) -> None:
        """Spawn a per-call keepalive task on the runner's loop.

        Idempotent: a duplicate `ToolCallStart` for the same id (which
        the turn loop already treats as a no-op) keeps the original
        ticker rather than leaking a second one. Records the monotonic
        start so each tick's `elapsed_ms` can be self-contained."""
        if tool_call_id in self._progress_tickers:
            return
        self._progress_started[tool_call_id] = time.monotonic()
        self._progress_tickers[tool_call_id] = asyncio.create_task(
            self._progress_ticker(tool_call_id),
            name=f"tool-progress:{self.session_id}:{tool_call_id}",
        )

    def _stop_progress_ticker(self, tool_call_id: str) -> None:
        """Cancel the ticker for one call. Safe to call for an id that
        has no ticker (never started, or already stopped)."""
        task = self._progress_tickers.pop(tool_call_id, None)
        self._progress_started.pop(tool_call_id, None)
        if task is not None:
            task.cancel()

    async def _stop_all_progress_tickers(self) -> None:
        """Cancel every ticker and wait for the cancellations to take
        effect before returning. Called from the turn's `finally` so
        an interrupted or exception-exited turn doesn't strand timers.

        Awaiting the gather ensures we don't leave tasks half-cancelled
        when `_run_forever` flips `_status` back to idle — a dangling
        `Task` could still try to `put_nowait` onto a subscriber queue
        after the runner's subscribers set has been mutated elsewhere.
        `return_exceptions=True` swallows the expected
        `CancelledError`s from each task."""
        tasks = list(self._progress_tickers.values())
        self._progress_tickers.clear()
        self._progress_started.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _progress_ticker(self, tool_call_id: str) -> None:
        """Emit a `ToolProgress` event every `TOOL_PROGRESS_INTERVAL_S`
        until cancelled.

        Intentionally robust against late cancellation: if the ticker
        is cancelled while blocked in `asyncio.sleep`, the raise
        propagates out cleanly; if the start time was cleared under
        us (e.g. `_stop_all_progress_tickers` ran first), the loop
        exits without emitting anything.

        Errors during `_emit_ephemeral` are logged and swallowed — the
        keepalive is advisory, and a broken fan-out must never kill
        the user's turn."""
        while True:
            try:
                await asyncio.sleep(TOOL_PROGRESS_INTERVAL_S)
            except asyncio.CancelledError:
                return
            started = self._progress_started.get(tool_call_id)
            if started is None:
                return
            elapsed_ms = int((time.monotonic() - started) * 1000)
            try:
                await self._emit_ephemeral(
                    ToolProgress(
                        session_id=self.session_id,
                        tool_call_id=tool_call_id,
                        elapsed_ms=elapsed_ms,
                    )
                )
            except Exception:
                log.exception(
                    "runner %s: tool_progress emit failed for %s",
                    self.session_id,
                    tool_call_id,
                )

    async def _emit_todo_write_update(self, tool_input: dict[str, Any]) -> None:
        """Translate a raw `TodoWrite` tool input into a
        `TodoWriteUpdate` event and fan it out through `_emit_event`.

        Tolerant of malformed payloads: if the SDK (or a future schema
        bump) sends something we can't parse, we log at warning and
        skip the emit rather than fail the turn. The underlying
        `tool_call_start` already landed — subscribers still have the
        raw version via the Inspector pane, so "live widget doesn't
        update" is recoverable; "turn crashes on unexpected shape" is
        not."""
        try:
            update = TodoWriteUpdate.model_validate({"session_id": self.session_id, **tool_input})
        except Exception as exc:  # noqa: BLE001 — intentional broad catch
            log.warning(
                "todo_write_update parse failed for session %s: %s",
                self.session_id,
                exc,
            )
            return
        await self._emit_event(update)

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

    async def _emit_ephemeral(self, event: AgentEvent) -> None:
        """Fan an event out to live subscribers WITHOUT appending to
        the ring buffer.

        Used for keepalives (`ToolProgress`) that need to arrive at
        connected clients in real time but have no value on replay —
        a reconnecting client's own clock takes over on the next live
        tick, and skipping the ring buffer prevents a long turn from
        chewing through the 5000-entry replay window with throwaway
        ticks. Seq advances so `_seq` stays monotonic for currently-
        connected clients; the skipped seqs simply aren't deliverable
        on future reconnects, which is what makes the event
        ephemeral."""
        payload = event.model_dump()
        env = _Envelope(self._next_seq, payload)
        self._next_seq += 1
        metrics.ws_events_sent.labels(type=event.type).inc()
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(env)
            except Exception:
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
    # Stamp last_completed_at for the sidebar's "finished but unviewed"
    # amber dot. Runs on every assistant turn persist including the
    # stop-requested synthetic, so an interrupted turn still counts as
    # completed output for the viewer to read.
    await store.mark_session_completed(conn, session_id)
