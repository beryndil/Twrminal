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

from bearings.agent.runner import (
    RunnerFactory,
    SessionRunner,
    SessionSetup,
    SessionSetupFn,
)
from bearings.agent.sdk_loop import run_session_loop


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

    def __init__(self, session_setup: SessionSetupFn | None = None) -> None:
        self._runners: dict[str, SessionRunner] = {}
        self._supervisors: dict[str, asyncio.Task[None]] = {}
        self._session_setup = session_setup
        self._spawn_lock = asyncio.Lock()

    async def __call__(self, session_id: str) -> SessionRunner:
        """Return the sticky runner for ``session_id``, creating one
        on first call. Spawns a supervisor task on first call when
        ``session_setup`` is wired (production); otherwise returns
        the runner without a worker (test-only — the ring buffer
        still works for emit-from-anywhere unit tests)."""
        if not session_id:
            raise ValueError("runner-factory session_id must be non-empty")
        runner = self._runners.get(session_id)
        if runner is not None:
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
        setup = await self._session_setup(session_id) if self._session_setup else None
        if setup is None:
            return
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

    def get_supervisor(self, session_id: str) -> asyncio.Task[None] | None:
        """Return the supervisor task for ``session_id`` if running.
        Test introspection — production code does not reach for
        worker handles directly."""
        return self._supervisors.get(session_id)

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
