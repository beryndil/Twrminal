"""Concrete :class:`RunnerFactory` binding — FastAPI-aware.

Per ``docs/architecture-v1.md`` §1.1.5 and §3.2 (cycle catalogue),
this module is the **rebuild's solution** to v0.17.x's lazy-import
cycle ``agent/auto_driver_runtime.py → api.ws_agent.build_runner``.
The factory lives here, in the ``web`` layer; the
:class:`bearings.agent.runner.RunnerFactory` Protocol lets the
``agent`` layer accept the binding by injection without ever
importing :mod:`bearings.web`.

Per Slice A1.3 of ``~/.claude/plans/wiring-agent-loop.md`` the factory
becomes the **worker-loop supervisor**: when a session id is requested
for the first time, the registry materialises a fresh
:class:`SessionRunner` AND spawns
``asyncio.create_task(run_session_loop(...))`` so the SDK client
connects + the prompt queue drains. The runner is sticky across WS
disconnects (the ring buffer survives close); the supervisor task is
sticky too — one per session for the session's lifetime.

The ``session_setup`` constructor argument is a callable that
materialises the per-session :class:`AgentSession` + composed
:class:`OptionsKwargs` from a session id. Production callers (item
1.10 ``cli/serve.py``) wire a real bootstrap that reads the row + DB
connection + ``compose_session_options`` output. Tests pass a fake
that returns synthetic values OR omit the argument entirely (no
supervisor spawned — the runner just sits there for ring-buffer-only
tests).

References:

* ``docs/architecture-v1.md`` §1.1.5 — ``web/runner_factory.py``.
* ``docs/architecture-v1.md`` §3.1 / §3.2 — layer rules + cycle break.
* ``docs/architecture-v1.md`` §4.5 — :class:`RunnerFactory` Protocol.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from bearings.agent.runner import (
    RunnerFactory,
    SessionRunner,
    SessionSetup,
    SessionSetupFn,
)
from bearings.agent.sdk_loop import run_session_loop
from bearings.config.constants import (
    IDLE_REAP_POLL_INTERVAL_S,
    IDLE_REAP_THRESHOLD_S,
)


class InProcessRunnerRegistry:
    """In-process ``session_id`` → :class:`SessionRunner` registry +
    per-session :func:`run_session_loop` supervisor.

    Implements the :class:`bearings.agent.runner.RunnerFactory`
    Protocol structurally — the async ``__call__`` returns a sticky
    runner per session id. Sticky runners are what behavior doc
    §"Reconnect / replay" assumes: the ring buffer lives on the
    runner, so the runner has to outlive the WS connection.

    Worker-loop ownership: when ``session_setup`` is provided at
    construction, every first-touch ``__call__`` spawns
    ``asyncio.create_task(run_session_loop(...))`` and stashes the
    handle. :meth:`aclose` cancels and awaits every supervisor on app
    shutdown so the SDK subprocess transports tear down cleanly.

    This class is **not** the per-WS-session SDK wrapper (that's
    :class:`bearings.agent.session.AgentSession`); it is the *runner
    registry* that the WS layer asks for a runner against a session
    id and gets a long-lived per-session worker back.
    """

    def __init__(
        self,
        session_setup: SessionSetupFn | None = None,
        *,
        idle_reap_threshold_s: float = IDLE_REAP_THRESHOLD_S,
        idle_reap_poll_interval_s: float = IDLE_REAP_POLL_INTERVAL_S,
    ) -> None:
        self._runners: dict[str, SessionRunner] = {}
        self._supervisors: dict[str, asyncio.Task[None]] = {}
        # Per-session ApprovalBroker handles, populated when the
        # bootstrap wires can_use_tool. Keyed by session id so the
        # /api/sessions/{id}/approvals route + the WS approval-resolved
        # frame can resolve the right broker. ``object`` typing avoids
        # a cross-layer ApprovalBroker import here — the route layer
        # narrows back at the call site.
        self._approval_brokers: dict[str, object] = {}
        self._session_setup = session_setup
        self._spawn_lock = asyncio.Lock()
        self._idle_reap_threshold_s = idle_reap_threshold_s
        self._idle_reap_poll_interval_s = idle_reap_poll_interval_s
        self._reaper_task: asyncio.Task[None] | None = None

    async def __call__(self, session_id: str) -> SessionRunner:
        """Return the sticky runner for ``session_id``, creating one
        on first call. Spawns a supervisor task on first call when
        ``session_setup`` is wired (production); otherwise returns
        the runner without a worker (test-only — the ring buffer
        still works for emit-from-anywhere unit tests).

        Reap-recovery: if the runner is registered but its
        supervisor has been reaped (idle-reap, fatal SDK error),
        re-spawn the worker on the next call. Per behavior doc
        §"long-idle teardown" this is server-side transparent —
        the user sends a prompt and the agent loop re-spawns
        without a UX surface.
        """
        if not session_id:
            raise ValueError("runner-factory session_id must be non-empty")
        runner = self._runners.get(session_id)
        if runner is not None:
            # Re-spawn supervisor if it was reaped.
            if self._session_setup is not None and session_id not in self._supervisors:
                async with self._spawn_lock:
                    if session_id not in self._supervisors:
                        await self._spawn_supervisor(session_id, runner)
            return runner
        # First-touch path. Hold the spawn-lock so concurrent
        # callers (two WS connects racing for the same session id)
        # see the same materialised runner + the same supervisor.
        async with self._spawn_lock:
            runner = self._runners.get(session_id)
            if runner is not None:
                return runner
            runner = SessionRunner(session_id)
            self._runners[session_id] = runner
            if self._session_setup is not None:
                await self._spawn_supervisor(session_id, runner)
        return runner

    async def _spawn_supervisor(
        self,
        session_id: str,
        runner: SessionRunner,
    ) -> None:
        """Materialise the per-session :class:`SessionSetup` and
        spawn the worker task. Silently no-ops if the setup callable
        returns ``None`` (session row missing)."""
        setup = await self._session_setup(session_id, runner) if self._session_setup else None
        if setup is None:
            return
        if setup.approval_broker is not None:
            self._approval_brokers[session_id] = setup.approval_broker
        task = asyncio.create_task(
            run_session_loop(runner, setup.session, setup.options),
            name=f"sdk_loop:{session_id}",
        )
        self._supervisors[session_id] = task

    def get(self, session_id: str) -> SessionRunner | None:
        """Return the runner for ``session_id`` if registered, else
        ``None``. Synchronous accessor for tests / introspection
        (``__call__`` is async to satisfy the Protocol)."""
        return self._runners.get(session_id)

    def start_reaper(self) -> None:
        """Spawn the idle-reap polling task. Idempotent.

        Per Slice A5 of ``~/.claude/plans/wiring-agent-loop.md`` and
        sign-off Q3 (accepted 2026-05-01): a session whose runner
        has had zero subscribers AND zero queued prompts for the
        past :data:`idle_reap_threshold_s` is teardown-eligible. The
        reaper polls every :data:`idle_reap_poll_interval_s`. App
        startup wires this through ``create_app``.
        """
        if self._reaper_task is not None and not self._reaper_task.done():
            return
        self._reaper_task = asyncio.create_task(
            self._reap_loop(),
            name="runner-factory-reaper",
        )

    async def _reap_loop(self) -> None:
        """Periodic-poll body for the reaper.

        Cancellation discipline: ``asyncio.CancelledError`` is NOT
        caught — it propagates straight out so the task observes its
        cancellation and exits cleanly. Other exceptions are
        swallowed so a transient reap-time error doesn't take the
        whole supervisor surface offline.
        """
        while True:
            try:
                await asyncio.sleep(self._idle_reap_poll_interval_s)
                await self._reap_idle_sessions()
            except Exception:  # pragma: no cover — defensive
                # Caller-level exceptions only. asyncio.CancelledError
                # is BaseException-derived in Python 3.8+ so this
                # ``except Exception`` does NOT catch it; the
                # cancellation propagates out of the loop and ends
                # the task as expected.
                continue

    async def _reap_idle_sessions(self) -> None:
        """Cancel + reap every supervisor whose runner has been
        idle past the threshold."""
        now_ns = time.monotonic_ns()
        threshold_ns = int(self._idle_reap_threshold_s * 1_000_000_000)
        to_reap: list[str] = []
        for session_id, runner in self._runners.items():
            if session_id not in self._supervisors:
                continue
            if runner.subscriber_count > 0 or runner.prompt_queue_depth > 0:
                continue
            if now_ns - runner.last_active_ns >= threshold_ns:
                to_reap.append(session_id)
        for session_id in to_reap:
            await self._reap_one(session_id)

    async def _reap_one(self, session_id: str) -> None:
        """Cancel + await one supervisor + cancel its broker."""
        broker = self._approval_brokers.pop(session_id, None)
        if broker is not None:
            cancel_all = getattr(broker, "cancel_all", None)
            if callable(cancel_all):
                cancel_all()
        task = self._supervisors.pop(session_id, None)
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    def get_supervisor(self, session_id: str) -> asyncio.Task[None] | None:
        """Return the supervisor task for ``session_id`` if running.
        Test introspection — production code does not reach for
        worker handles directly."""
        return self._supervisors.get(session_id)

    def get_approval_broker(self, session_id: str) -> object | None:
        """Return the per-session ApprovalBroker if one is wired.

        ``object`` typed to avoid a cross-layer import; the route
        layer (``web/routes/approvals.py``) narrows back to the
        :class:`bearings.agent.approval.ApprovalBroker` concrete
        class at the call site.
        """
        return self._approval_brokers.get(session_id)

    def close_all(self) -> None:
        """Drop every registered runner. For test teardown only —
        production callers use :meth:`aclose` to also reap the
        supervisor tasks."""
        self._runners.clear()
        self._supervisors.clear()

    async def aclose(self) -> None:
        """Cancel every supervisor task + await its teardown.

        Called on app shutdown so the SDK subprocess transports get
        ``__aexit__``ed cleanly. Idempotent — safe to call multiple
        times. Tasks that have already completed (e.g. via fatal
        SDK error) are skipped. The runner registry is NOT cleared —
        post-shutdown introspection (test assertions, debug
        endpoints) can still read the ring buffer for a session even
        after the worker has been reaped.
        """
        # Stop the reaper first so it doesn't race the supervisor
        # cancellation below. The pattern is:
        # 1. ``task.cancel()`` schedules CancelledError into the
        #    task's next await point.
        # 2. Yield via ``asyncio.sleep`` long enough for the event
        #    loop to deliver the cancellation. ``asyncio.sleep(0)``
        #    yields once but does not always trigger delivery on
        #    pending sleep futures inside the cancelled task.
        # 3. ``asyncio.wait`` blocks until the task is in done state
        #    (cancelled / finished); the ``return_when=FIRST_COMPLETED``
        #    semantics give us the await without re-raising the
        #    task's CancelledError on the awaiter coroutine.
        if self._reaper_task is not None and not self._reaper_task.done():
            self._reaper_task.cancel()
            # Drive the event loop until the task actually completes.
            # Using ``asyncio.sleep(0)`` in a small polling loop is
            # the most portable way to yield repeatedly so the
            # cancelled task gets the CPU to observe its cancellation
            # and unwind. ``asyncio.wait`` / bare ``await task`` can
            # both wedge inside pytest-asyncio's event-loop
            # supervision.
            for _ in range(200):
                if self._reaper_task.done():
                    break
                await asyncio.sleep(0)
        self._reaper_task = None
        # Cancel any in-flight approval futures first so the
        # SDK-side can_use_tool callbacks unblock and let the
        # supervisor task observe the cancellation cleanly.
        for broker in self._approval_brokers.values():
            cancel_all = getattr(broker, "cancel_all", None)
            if callable(cancel_all):
                cancel_all()
        self._approval_brokers.clear()
        tasks = list(self._supervisors.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._supervisors.clear()


def build_in_process_factory(
    session_setup: SessionSetupFn | None = None,
) -> RunnerFactory:
    """Construct a fresh :class:`InProcessRunnerRegistry` typed at
    the :class:`RunnerFactory` Protocol so call sites pass it through
    parameters typed against the Protocol.

    Equivalent to ``InProcessRunnerRegistry(session_setup)`` but the
    explicit return-type annotation forces mypy to verify the
    structural typing — if the registry's ``__call__`` signature
    drifts from the Protocol the project fails type-check at this
    function rather than at the consumer.
    """
    return InProcessRunnerRegistry(session_setup=session_setup)


__all__ = [
    "InProcessRunnerRegistry",
    "SessionSetup",
    "SessionSetupFn",
    "build_in_process_factory",
]
